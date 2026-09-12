from rest_framework import serializers
from .models import Ticket, TicketMessage


class TicketMessageSerializer(serializers.ModelSerializer):
    sender_email = serializers.CharField(source="sender.email", read_only=True)
    is_staff_reply = serializers.BooleanField(source="sender.is_staff_role", read_only=True)

    class Meta:
        model = TicketMessage
        fields = ["id", "sender_email", "is_staff_reply", "message", "created_at"]
        read_only_fields = fields


class TicketMessageCreateSerializer(serializers.Serializer):
    message = serializers.CharField()


class TicketListSerializer(serializers.ModelSerializer):
    message_count = serializers.IntegerField(source="messages.count", read_only=True)

    class Meta:
        model = Ticket
        fields = ["id", "subject", "category", "status", "order", "message_count", "created_at", "updated_at"]


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
