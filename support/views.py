import logging

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, views, status
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from accounts.permissions import IsOwnerOrStaff
from orders.models import Order
from notifications.services import notify, notify_staff
from .models import Ticket, TicketMessage
from .serializers import (
    TicketListSerializer, TicketDetailSerializer, TicketCreateSerializer,
    TicketMessageSerializer, TicketMessageCreateSerializer, TicketStatusUpdateSerializer,
)


logger = logging.getLogger(__name__)


def _customer_label(user):
    return (user.get_full_name() or "").strip() or user.email


def _snippet(text, limit=140):
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class TicketListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        base = Ticket.objects.select_related("user")
        return base if self.request.user.is_staff_role else base.filter(user=self.request.user)

    def get_serializer_class(self):
        return TicketCreateSerializer if self.request.method == "POST" else TicketListSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        order = None
        if data.get("order"):
            order = get_object_or_404(Order, id=data["order"], user=request.user)

        # Ticket and its first message are saved together or not at all.
        with transaction.atomic():
            ticket = Ticket.objects.create(
                user=request.user, subject=data["subject"], category=data["category"], order=order,
            )
            TicketMessage.objects.create(ticket=ticket, sender=request.user, message=data["message"])

        # Let the support team know. A failure here must never lose the customer's ticket.
        try:
            notify_staff(
                "new_ticket",
                f"New ticket: {ticket.subject}",
                f"{_customer_label(request.user)} · {ticket.get_category_display()}: {_snippet(data['message'])}",
                link=f"/support/{ticket.id}",
                exclude_user=request.user,
            )
        except Exception:
            logger.exception("Couldn't notify staff of new ticket %s", ticket.id)
        return Response(TicketDetailSerializer(ticket).data, status=status.HTTP_201_CREATED)


class TicketDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Ticket.objects.all()
    serializer_class = TicketDetailSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrStaff]
    lookup_field = "id"

    def get_queryset(self):
        base = Ticket.objects.select_related("user")
        return base if self.request.user.is_staff_role else base.filter(user=self.request.user)

    def patch(self, request, *args, **kwargs):
        if not request.user.is_staff_role:
            raise PermissionDenied("Only staff can update a ticket's status.")
        
        ticket = self.get_object()
        serializer = TicketStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket.status = serializer.validated_data["status"]
        ticket.save(update_fields=["status", "updated_at"])
        return Response(TicketDetailSerializer(ticket).data)

    def delete(self, request, *args, **kwargs):
        ticket = self.get_object()
        self.check_object_permissions(request, ticket)
        ticket.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class TicketMessageCreateView(views.APIView):
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrStaff]

    def post(self, request, id):
        ticket = get_object_or_404(Ticket, id=id)
        self.check_object_permissions(request, ticket)

        serializer = TicketMessageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = TicketMessage.objects.create(ticket=ticket, sender=request.user, message=serializer.validated_data["message"])

        if request.user.is_staff_role and request.user != ticket.user:
            notify(
                ticket.user, "ticket_reply", f"New reply on ticket: {ticket.subject}",
                serializer.validated_data["message"], link=f"/support/{ticket.id}",
            )
        # Ticket re-opens if support already marked it resolved/closed and the customer follows up.
        if not request.user.is_staff_role and ticket.status in (Ticket.Status.RESOLVED, Ticket.Status.CLOSED):
            ticket.status = Ticket.Status.OPEN
            ticket.save(update_fields=["status", "updated_at"])

        # A customer following up (especially on a reopened ticket) needs the team's attention too.
        if not request.user.is_staff_role:
            try:
                notify_staff(
                    "ticket_message",
                    f"Customer replied: {ticket.subject}",
                    f"{_customer_label(request.user)}: {_snippet(serializer.validated_data['message'])}",
                    link=f"/support/{ticket.id}",
                )
            except Exception:
                logger.exception("Couldn't notify staff of reply on ticket %s", ticket.id)

        return Response(TicketMessageSerializer(message).data, status=status.HTTP_201_CREATED)