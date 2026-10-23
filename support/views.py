import logging
import os
import uuid
from datetime import timedelta

from django.db import transaction
from django.db.models import Case, Count, F, IntegerField, Prefetch, Q, Value, When
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.http import content_disposition_header
from rest_framework import generics, permissions, views, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from accounts.models import User
from accounts.permissions import IsOwnerOrStaff, IsStaffOrAdmin
from orders.models import Order
from notifications.services import notify, notify_staff
from .models import Ticket, TicketMessage, TicketAttachment, Task
from .serializers import (
    TicketListSerializer, TicketDetailSerializer, TicketCreateSerializer,
    TicketMessageSerializer, TicketMessageCreateSerializer,
    StaffTicketListSerializer, StaffTicketDetailSerializer, StaffTicketUpdateSerializer,
    StaffMemberSerializer, TaskSerializer, display_name,
)


logger = logging.getLogger(__name__)

ACTIVE_STATUSES = (Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS)
DONE_STATUSES = (Ticket.Status.RESOLVED, Ticket.Status.CLOSED)


def _customer_label(user):
    return (user.get_full_name() or "").strip() or user.email


def _snippet(text, limit=140):
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _safe_notify(*args, **kwargs):
    """Notifications are a courtesy: a failure must never undo or block the real action."""
    try:
        notify(*args, **kwargs)
    except Exception:
        logger.exception("Couldn't create notification")


def _parse_uuid(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


class FlexiblePagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


# --------------------------------------------------------------------------- tickets

def _ticket_queryset():
    """Ticket + everything the detail serializers touch, without ever loading attachment bytes."""
    messages = TicketMessage.objects.select_related("sender").prefetch_related(
        Prefetch("attachments", queryset=TicketAttachment.objects.defer("data"))
    )
    return Ticket.objects.select_related("user", "assigned_to").prefetch_related(
        Prefetch("messages", queryset=messages),
        Prefetch("tasks", queryset=Task.objects.select_related("assigned_to")),
    )


def _overdue_q():
    """SQL twin of Ticket.is_overdue: active tickets past their first-response or resolution deadline."""
    now = timezone.now()
    q = Q()
    for priority in Ticket.Priority.values:
        first_cutoff = now - timedelta(hours=Ticket.FIRST_RESPONSE_HOURS[priority])
        resolve_cutoff = now - timedelta(hours=Ticket.RESOLUTION_HOURS[priority])
        q |= Q(priority=priority) & (
            Q(first_response_at__isnull=True, created_at__lt=first_cutoff) | Q(created_at__lt=resolve_cutoff)
        )
    return Q(status__in=ACTIVE_STATUSES) & q


def _apply_staff_filters(qs, params, user):
    view = params.get("view")
    inbox = Q(is_archived=False, is_spam=False)
    if view == "inbox":
        qs = qs.filter(inbox)
    elif view == "unread":
        qs = qs.filter(inbox, is_unread=True)
    elif view == "mine":
        qs = qs.filter(inbox, assigned_to=user)
    elif view == "unassigned":
        qs = qs.filter(inbox, assigned_to__isnull=True)
    elif view == "overdue":
        qs = qs.filter(inbox, _overdue_q())
    elif view == "archived":
        qs = qs.filter(is_archived=True, is_spam=False)
    elif view == "spam":
        qs = qs.filter(is_spam=True)
    # "all" / missing -> no folder filtering

    status_param = params.get("status")
    if status_param == "active":
        qs = qs.filter(status__in=ACTIVE_STATUSES)
    elif status_param == "done":
        qs = qs.filter(status__in=DONE_STATUSES)
    elif status_param in Ticket.Status.values:
        qs = qs.filter(status=status_param)

    if params.get("priority") in Ticket.Priority.values:
        qs = qs.filter(priority=params["priority"])
    if params.get("category") in Ticket.Category.values:
        qs = qs.filter(category=params["category"])

    assignee = params.get("assignee")
    if assignee == "none":
        qs = qs.filter(assigned_to__isnull=True)
    elif assignee == "me":
        qs = qs.filter(assigned_to=user)
    elif assignee:
        parsed = _parse_uuid(assignee)
        qs = qs.filter(assigned_to_id=parsed) if parsed else qs.none()

    term = (params.get("q") or "").strip()
    if term:
        qs = qs.filter(
            Q(subject__icontains=term)
            | Q(user__email__icontains=term)
            | Q(user__first_name__icontains=term)
            | Q(user__last_name__icontains=term)
        )
    return qs


class TicketListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = FlexiblePagination

    def get_queryset(self):
        base = Ticket.objects.select_related("user", "assigned_to")
        if not self.request.user.is_staff_role:
            return base.filter(user=self.request.user)
        # Explicit ordering: aggregate queries ignore the model's default Meta.ordering.
        qs = base.annotate(message_total=Count("messages")).order_by("-updated_at", "-created_at")
        return _apply_staff_filters(qs, self.request.query_params, self.request.user)

    def get_serializer_class(self):
        if self.request.method == "POST":
            return TicketCreateSerializer
        return StaffTicketListSerializer if self.request.user.is_staff_role else TicketListSerializer

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
                link=f"/admin/tickets/{ticket.id}",
                exclude_user=request.user,
            )
        except Exception:
            logger.exception("Couldn't notify staff of new ticket %s", ticket.id)
        ticket = _ticket_queryset().get(pk=ticket.pk)
        detail = StaffTicketDetailSerializer if request.user.is_staff_role else TicketDetailSerializer
        return Response(detail(ticket).data, status=status.HTTP_201_CREATED)


class TicketDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrStaff]
    lookup_field = "id"
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self):
        base = _ticket_queryset()
        return base if self.request.user.is_staff_role else base.filter(user=self.request.user)

    def get_serializer_class(self):
        return StaffTicketDetailSerializer if self.request.user.is_staff_role else TicketDetailSerializer

    def patch(self, request, *args, **kwargs):
        if not request.user.is_staff_role:
            raise PermissionDenied("Only staff can update a ticket.")

        ticket = self.get_object()
        serializer = StaffTicketUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        meaningful = False  # a change the customer/team cares about -> bump updated_at
        update_fields = set()
        new_assignee = None

        if "status" in data and data["status"] != ticket.status:
            ticket.set_status(data["status"])
            update_fields.update(["status", "resolved_at"])
            meaningful = True
        for field in ("priority", "category"):
            if field in data and data[field] != getattr(ticket, field):
                setattr(ticket, field, data[field])
                update_fields.add(field)
                meaningful = True
        if "assigned_to" in data and data["assigned_to"] != ticket.assigned_to:
            ticket.assigned_to = data["assigned_to"]
            new_assignee = data["assigned_to"]
            update_fields.add("assigned_to")
            meaningful = True
        for field in ("is_archived", "is_spam", "is_unread"):
            if field in data and data[field] != getattr(ticket, field):
                setattr(ticket, field, data[field])
                update_fields.add(field)
        # A ticket flagged as spam shouldn't also sit in the archive folder.
        if data.get("is_spam") and ticket.is_archived:
            ticket.is_archived = False
            update_fields.add("is_archived")

        if update_fields:
            if meaningful:
                update_fields.add("updated_at")
            ticket.save(update_fields=list(update_fields))

        if new_assignee and new_assignee != request.user:
            _safe_notify(
                new_assignee, "ticket_assigned", f"Ticket assigned to you: {ticket.subject}",
                f"{display_name(request.user)} assigned you a {ticket.get_priority_display().lower()}-priority ticket.",
                send_email=False, link=f"/admin/tickets/{ticket.id}",
            )

        return Response(StaffTicketDetailSerializer(self.get_queryset().get(pk=ticket.pk)).data)

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
        text = serializer.validated_data["message"]
        files = serializer.validated_data.get("attachments", [])
        is_staff = request.user.is_staff_role

        with transaction.atomic():
            message = TicketMessage.objects.create(ticket=ticket, sender=request.user, message=text)
            for f in files:
                TicketAttachment.objects.create(
                    message=message,
                    filename=os.path.basename(f.name)[:255],
                    content_type=(getattr(f, "content_type", "") or "application/octet-stream")[:100],
                    size=f.size,
                    data=f.read(),
                )

            fields = ["updated_at"]
            if is_staff:
                # Team reply: stamps the first response, moves a fresh ticket into progress, marks it read.
                if request.user != ticket.user and ticket.first_response_at is None:
                    ticket.first_response_at = timezone.now()
                    fields.append("first_response_at")
                if ticket.status == Ticket.Status.OPEN:
                    ticket.set_status(Ticket.Status.IN_PROGRESS)
                    fields += ["status", "resolved_at"]
                ticket.is_unread = False
                fields.append("is_unread")
            else:
                # Customer follow-up: re-open if it was wrapped up, resurface if archived, flag unread.
                if ticket.status in DONE_STATUSES:
                    ticket.set_status(Ticket.Status.OPEN)
                    fields += ["status", "resolved_at"]
                ticket.is_archived = False
                ticket.is_unread = True
                fields += ["is_archived", "is_unread"]
            ticket.save(update_fields=fields)

        preview = text or f"Sent {len(files)} attachment{'s' if len(files) != 1 else ''}."
        if is_staff and request.user != ticket.user:
            _safe_notify(
                ticket.user, "ticket_reply", f"New reply on ticket: {ticket.subject}",
                preview, link=f"/support/{ticket.id}",
            )
        if not is_staff:
            try:
                notify_staff(
                    "ticket_message",
                    f"Customer replied: {ticket.subject}",
                    f"{_customer_label(request.user)}: {_snippet(preview)}",
                    link=f"/admin/tickets/{ticket.id}",
                )
            except Exception:
                logger.exception("Couldn't notify staff of reply on ticket %s", ticket.id)

        message = TicketMessage.objects.select_related("sender").prefetch_related(
            Prefetch("attachments", queryset=TicketAttachment.objects.defer("data"))
        ).get(pk=message.pk)
        return Response(TicketMessageSerializer(message).data, status=status.HTTP_201_CREATED)


class TicketAttachmentDownloadView(views.APIView):
    """Authenticated download: only the ticket's owner or the support team can read the bytes."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, id, attachment_id):
        qs = TicketAttachment.objects.filter(id=attachment_id, message__ticket_id=id)
        if not request.user.is_staff_role:
            qs = qs.filter(message__ticket__user=request.user)
        attachment = qs.first()
        if attachment is None:
            raise Http404
        response = HttpResponse(bytes(attachment.data), content_type=attachment.content_type)
        response["Content-Disposition"] = content_disposition_header(True, attachment.filename)
        response["X-Content-Type-Options"] = "nosniff"
        return response


class TicketStatsView(views.APIView):
    """Counts behind the folder tabs on the admin ticket list. 'Active' = open or in progress."""
    permission_classes = [IsStaffOrAdmin]

    def get(self, request):
        inbox_active = Ticket.objects.filter(is_archived=False, is_spam=False, status__in=ACTIVE_STATUSES)
        return Response({
            "inbox": inbox_active.count(),
            "unread": inbox_active.filter(is_unread=True).count(),
            "mine": inbox_active.filter(assigned_to=request.user).count(),
            "unassigned": inbox_active.filter(assigned_to__isnull=True).count(),
            "overdue": inbox_active.filter(_overdue_q()).count(),
            "archived": Ticket.objects.filter(is_archived=True, is_spam=False).count(),
            "spam": Ticket.objects.filter(is_spam=True).count(),
        })


# --------------------------------------------------------------------------- staff & tasks

class StaffListView(generics.ListAPIView):
    """Active team members with workload counts. Feeds the Staff page and every 'assign to' picker."""
    serializer_class = StaffMemberSerializer
    permission_classes = [IsStaffOrAdmin]
    pagination_class = None

    def get_queryset(self):
        today = timezone.localdate()
        not_done = ~Q(tasks__status=Task.Status.DONE)
        return (
            User.objects.filter(role__in=[User.Role.STAFF, User.Role.ADMIN], is_active=True)
            .annotate(
                open_tickets=Count(
                    "assigned_tickets",
                    filter=Q(
                        assigned_tickets__status__in=ACTIVE_STATUSES,
                        assigned_tickets__is_archived=False,
                        assigned_tickets__is_spam=False,
                    ),
                    distinct=True,
                ),
                open_tasks=Count("tasks", filter=not_done, distinct=True),
                overdue_tasks=Count("tasks", filter=not_done & Q(tasks__due_date__lt=today), distinct=True),
                done_tasks=Count("tasks", filter=Q(tasks__status=Task.Status.DONE), distinct=True),
            )
            .order_by("role", "first_name", "email")
        )


class TaskListCreateView(generics.ListCreateAPIView):
    serializer_class = TaskSerializer
    permission_classes = [IsStaffOrAdmin]
    pagination_class = FlexiblePagination

    def get_queryset(self):
        user = self.request.user
        params = self.request.query_params
        qs = Task.objects.select_related("assigned_to", "created_by", "ticket")

        if not user.is_admin_role:
            qs = qs.filter(assigned_to=user)  # staff only ever see their own work
        else:
            assignee = params.get("assignee")
            if assignee == "me":
                qs = qs.filter(assigned_to=user)
            elif assignee:
                parsed = _parse_uuid(assignee)
                qs = qs.filter(assigned_to_id=parsed) if parsed else qs.none()

        status_param = params.get("status")
        if status_param == "open":
            qs = qs.exclude(status=Task.Status.DONE)
        elif status_param in Task.Status.values:
            qs = qs.filter(status=status_param)

        ticket = params.get("ticket")
        if ticket:
            parsed = _parse_uuid(ticket)
            qs = qs.filter(ticket_id=parsed) if parsed else qs.none()

        term = (params.get("q") or "").strip()
        if term:
            qs = qs.filter(Q(title__icontains=term) | Q(description__icontains=term))

        # Unfinished work first, soonest deadline first (no deadline last), newest on ties.
        return qs.annotate(
            _done=Case(When(status=Task.Status.DONE, then=Value(1)), default=Value(0), output_field=IntegerField())
        ).order_by("_done", F("due_date").asc(nulls_last=True), "-created_at")

    def perform_create(self, serializer):
        user = self.request.user
        assignee = serializer.validated_data.get("assigned_to") or user
        if assignee != user and not user.is_admin_role:
            raise PermissionDenied("Only admins can assign tasks to other staff.")
        task = serializer.save(assigned_to=assignee, created_by=user)
        if assignee != user:
            _safe_notify(
                assignee, "task_assigned", f"New task: {task.title}",
                f"{display_name(user)} assigned you a {task.get_priority_display().lower()}-priority task.",
                send_email=False, link="/admin/staff",
            )


class TaskDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = TaskSerializer
    permission_classes = [IsStaffOrAdmin]
    http_method_names = ["get", "patch", "delete", "head", "options"]
    lookup_field = "id"

    def get_queryset(self):
        qs = Task.objects.select_related("assigned_to", "created_by", "ticket")
        return qs if self.request.user.is_admin_role else qs.filter(assigned_to=self.request.user)

    def patch(self, request, *args, **kwargs):
        user = request.user
        task = self.get_object()
        if not user.is_admin_role and set(request.data.keys()) - {"status"}:
            raise PermissionDenied("You can only change the status of your tasks.")

        previous_assignee, previous_status = task.assigned_to_id, task.status
        serializer = self.get_serializer(task, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        new_status = serializer.validated_data.pop("status", None)
        task = serializer.save()
        if new_status and new_status != previous_status:
            task.set_status(new_status)
            task.save(update_fields=["status", "completed_at", "updated_at"])

        if task.assigned_to_id != previous_assignee and task.assigned_to != user:
            _safe_notify(
                task.assigned_to, "task_assigned", f"New task: {task.title}",
                f"{display_name(user)} assigned you a {task.get_priority_display().lower()}-priority task.",
                send_email=False, link="/admin/staff",
            )
        if task.status == Task.Status.DONE and previous_status != Task.Status.DONE:
            if task.created_by_id and task.created_by_id != user.id:
                _safe_notify(
                    task.created_by, "general", f"Task completed: {task.title}",
                    f"{display_name(user)} marked this task as done.", send_email=False, link="/admin/staff",
                )
        return Response(TaskSerializer(self.get_queryset().get(pk=task.pk)).data)

    def delete(self, request, *args, **kwargs):
        if not request.user.is_admin_role:
            raise PermissionDenied("Only admins can delete tasks.")
        return super().delete(request, *args, **kwargs)