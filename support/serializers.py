from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Ticket, TicketMessage, TicketAttachment, Task

User = get_user_model()


def display_name(user):
    if user is None:
        return ""
    return (user.get_full_name() or "").strip() or user.email


# --------------------------------------------------------------------------- messages

class TicketAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketAttachment
        fields = ["id", "filename", "content_type", "size", "created_at"]
        read_only_fields = fields


class TicketMessageSerializer(serializers.ModelSerializer):
    sender_email = serializers.CharField(source="sender.email", read_only=True)
    sender_name = serializers.SerializerMethodField()
    is_staff_reply = serializers.BooleanField(source="sender.is_staff_role", read_only=True)
    attachments = TicketAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = TicketMessage
        fields = ["id", "sender_email", "sender_name", "is_staff_reply", "message", "attachments", "created_at"]
        read_only_fields = fields

    def get_sender_name(self, obj):
        return display_name(obj.sender)


class TicketMessageCreateSerializer(serializers.Serializer):
    message = serializers.CharField(required=False, allow_blank=True, default="")
    attachments = serializers.ListField(
        child=serializers.FileField(allow_empty_file=False),
        required=False, allow_empty=True, write_only=True,
    )

    def validate_attachments(self, files):
        if len(files) > TicketAttachment.MAX_FILES_PER_MESSAGE:
            raise serializers.ValidationError(
                f"You can attach up to {TicketAttachment.MAX_FILES_PER_MESSAGE} files per message."
            )
        for f in files:
            ext = f.name.rsplit(".", 1)[-1].lower() if "." in f.name else ""
            if ext not in TicketAttachment.ALLOWED_EXTENSIONS:
                raise serializers.ValidationError(f"“{f.name}”: this file type isn't allowed.")
            if f.size > TicketAttachment.MAX_BYTES:
                limit_mb = TicketAttachment.MAX_BYTES // (1024 * 1024)
                raise serializers.ValidationError(f"“{f.name}” is larger than {limit_mb} MB.")
        return files

    def validate(self, attrs):
        text = (attrs.get("message") or "").strip()
        if not text and not attrs.get("attachments"):
            raise serializers.ValidationError({"message": "Write a message or attach a file."})
        attrs["message"] = text
        return attrs


# --------------------------------------------------------------------------- tickets (customer side)

class TicketListSerializer(serializers.ModelSerializer):
    message_count = serializers.IntegerField(source="messages.count", read_only=True)
    customer_email = serializers.CharField(source="user.email", read_only=True)

    class Meta:
        model = Ticket
        fields = ["id", "subject", "category", "status", "order", "customer_email", "message_count", "created_at", "updated_at"]


class TicketDetailSerializer(serializers.ModelSerializer):
    messages = TicketMessageSerializer(many=True, read_only=True)

    class Meta:
        model = Ticket
        fields = ["id", "subject", "category", "status", "order", "messages", "created_at", "updated_at"]


class TicketCreateSerializer(serializers.Serializer):
    subject = serializers.CharField(max_length=255)
    category = serializers.ChoiceField(choices=Ticket.Category.choices, default=Ticket.Category.OTHER)
    order = serializers.UUIDField(required=False, allow_null=True)
    message = serializers.CharField()


class TicketStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Ticket.Status.choices)


# --------------------------------------------------------------------------- tickets (staff side)

class StaffTicketListSerializer(serializers.ModelSerializer):
    message_count = serializers.IntegerField(source="message_total", read_only=True)
    customer_email = serializers.CharField(source="user.email", read_only=True)
    customer_name = serializers.SerializerMethodField()
    assigned_to_name = serializers.SerializerMethodField()
    first_response_due = serializers.DateTimeField(read_only=True)
    resolution_due = serializers.DateTimeField(read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)

    class Meta:
        model = Ticket
        fields = [
            "id", "subject", "category", "status", "priority", "order",
            "customer_email", "customer_name", "assigned_to", "assigned_to_name",
            "is_unread", "is_archived", "is_spam", "is_overdue",
            "first_response_due", "resolution_due", "message_count", "created_at", "updated_at",
        ]
        read_only_fields = fields

    def get_customer_name(self, obj):
        return display_name(obj.user)

    def get_assigned_to_name(self, obj):
        return display_name(obj.assigned_to) if obj.assigned_to_id else ""


class TicketTaskSerializer(serializers.ModelSerializer):
    """Compact task shape for embedding inside a ticket."""
    assigned_to_name = serializers.SerializerMethodField()
    is_overdue = serializers.BooleanField(read_only=True)

    class Meta:
        model = Task
        fields = ["id", "title", "status", "priority", "due_date", "assigned_to", "assigned_to_name", "is_overdue"]
        read_only_fields = fields

    def get_assigned_to_name(self, obj):
        return display_name(obj.assigned_to)


class StaffTicketDetailSerializer(serializers.ModelSerializer):
    messages = TicketMessageSerializer(many=True, read_only=True)
    tasks = TicketTaskSerializer(many=True, read_only=True)
    requester = serializers.SerializerMethodField()
    assigned_to_name = serializers.SerializerMethodField()
    category_display = serializers.CharField(source="get_category_display", read_only=True)
    first_response_due = serializers.DateTimeField(read_only=True)
    resolution_due = serializers.DateTimeField(read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)

    class Meta:
        model = Ticket
        fields = [
            "id", "subject", "category", "category_display", "status", "priority", "order",
            "requester", "assigned_to", "assigned_to_name",
            "is_unread", "is_archived", "is_spam", "is_overdue",
            "first_response_due", "resolution_due", "first_response_at", "resolved_at",
            "messages", "tasks", "created_at", "updated_at",
        ]
        read_only_fields = fields

    def get_requester(self, obj):
        u = obj.user
        return {
            "id": u.id,
            "name": display_name(u),
            "email": u.email,
            "phone_number": u.phone_number,
            "joined": u.created_at,
        }

    def get_assigned_to_name(self, obj):
        return display_name(obj.assigned_to) if obj.assigned_to_id else ""


class StaffTicketUpdateSerializer(serializers.Serializer):
    """Everything a team member can change on a ticket. All fields optional (PATCH)."""
    status = serializers.ChoiceField(choices=Ticket.Status.choices, required=False)
    priority = serializers.ChoiceField(choices=Ticket.Priority.choices, required=False)
    category = serializers.ChoiceField(choices=Ticket.Category.choices, required=False)
    assigned_to = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role__in=[User.Role.STAFF, User.Role.ADMIN], is_active=True),
        required=False, allow_null=True,
    )
    is_archived = serializers.BooleanField(required=False)
    is_spam = serializers.BooleanField(required=False)
    is_unread = serializers.BooleanField(required=False)


# --------------------------------------------------------------------------- staff & tasks

class StaffMemberSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    open_tickets = serializers.IntegerField(read_only=True)
    open_tasks = serializers.IntegerField(read_only=True)
    overdue_tasks = serializers.IntegerField(read_only=True)
    done_tasks = serializers.IntegerField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id", "email", "first_name", "last_name", "full_name", "phone_number", "role", "created_at",
            "open_tickets", "open_tasks", "overdue_tasks", "done_tasks",
        ]
        read_only_fields = fields

    def get_full_name(self, obj):
        return display_name(obj)


class TaskSerializer(serializers.ModelSerializer):
    assigned_to_name = serializers.SerializerMethodField()
    assigned_to_email = serializers.CharField(source="assigned_to.email", read_only=True)
    created_by_name = serializers.SerializerMethodField()
    ticket_subject = serializers.CharField(source="ticket.subject", read_only=True, default=None)
    is_overdue = serializers.BooleanField(read_only=True)
    assigned_to = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role__in=[User.Role.STAFF, User.Role.ADMIN], is_active=True),
        required=False,
    )
    ticket = serializers.PrimaryKeyRelatedField(queryset=Ticket.objects.all(), required=False, allow_null=True)

    class Meta:
        model = Task
        fields = [
            "id", "title", "description", "status", "priority", "due_date",
            "assigned_to", "assigned_to_name", "assigned_to_email",
            "created_by", "created_by_name", "ticket", "ticket_subject",
            "is_overdue", "completed_at", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_by", "completed_at", "created_at", "updated_at"]

    def get_assigned_to_name(self, obj):
        return display_name(obj.assigned_to)

    def get_created_by_name(self, obj):
        return display_name(obj.created_by) if obj.created_by_id else ""

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Give the task a title.")
        return value