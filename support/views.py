from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, views, status
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from accounts.permissions import IsOwnerOrStaff
from orders.models import Order
from notifications.services import notify
from .models import Ticket, TicketMessage
from .serializers import (
    TicketListSerializer, TicketDetailSerializer, TicketCreateSerializer,
    TicketMessageSerializer, TicketMessageCreateSerializer, TicketStatusUpdateSerializer,
)


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

        ticket = Ticket.objects.create(
            user=request.user, subject=data["subject"], category=data["category"], order=order,
        )
        TicketMessage.objects.create(ticket=ticket, sender=request.user, message=data["message"])
        return Response(TicketDetailSerializer(ticket).data, status=status.HTTP_201_CREATED)


class TicketDetailView(views.APIView):
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrStaff]

    def get_ticket(self, request, id):
        ticket = get_object_or_404(Ticket, id=id)
        self.check_object_permissions(request, ticket)
        return ticket

    def get(self, request, id):
        ticket = self.get_ticket(request, id)
        return Response(TicketDetailSerializer(ticket).data)

    def patch(self, request, id):
        if not request.user.is_staff_role:
            raise PermissionDenied("Only staff can update a ticket's status.")
        ticket = self.get_ticket(request, id)
        serializer = TicketStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket.status = serializer.validated_data["status"]
        ticket.save(update_fields=["status", "updated_at"])
        return Response(TicketDetailSerializer(ticket).data)


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
                serializer.validated_data["message"],
            )
        # Ticket re-opens if support already marked it resolved/closed and the customer follows up.
        if not request.user.is_staff_role and ticket.status in (Ticket.Status.RESOLVED, Ticket.Status.CLOSED):
            ticket.status = Ticket.Status.OPEN
            ticket.save(update_fields=["status", "updated_at"])

        return Response(TicketMessageSerializer(message).data, status=status.HTTP_201_CREATED)
