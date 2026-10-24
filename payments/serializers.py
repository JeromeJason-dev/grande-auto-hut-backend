import re
from rest_framework import serializers
from .models import Payment, PaymentAuditLog


class MpesaInitiateSerializer(serializers.Serializer):
    order_id = serializers.UUIDField()
    phone_number = serializers.CharField(max_length=15)

    def validate_phone_number(self, value):
        digits = re.sub(r"\D", "", value)
        if digits.startswith("0") and len(digits) == 10:
            digits = "254" + digits[1:]
        elif digits.startswith("254") and len(digits) == 12:
            pass
        elif digits.startswith("7") and len(digits) == 9:
            digits = "254" + digits
        else:
            raise serializers.ValidationError("Enter a valid Kenyan phone number, e.g. 0712345678 or 254712345678.")
        return digits


class MpesaStatusSerializer(serializers.Serializer):
    order_id = serializers.UUIDField()


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ["id", "order", "method", "status", "amount", "phone_number", "mpesa_receipt_number", "card_brand", "card_last4", "created_at"]
        read_only_fields = fields


class CardInitiateSerializer(serializers.Serializer):
    order_id = serializers.UUIDField()


class CardVerifySerializer(serializers.Serializer):
    order_id = serializers.UUIDField()
    reference = serializers.CharField(max_length=100, required=False, allow_blank=True)


class PaymentDetailSerializer(serializers.ModelSerializer):
    """Everything staff may *see* about a payment attempt. Read-only by design."""
    method_label = serializers.CharField(source="get_method_display", read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id", "method", "method_label", "status", "amount", "phone_number",
            "mpesa_receipt_number", "mpesa_checkout_request_id",
            "card_brand", "card_last4", "card_reference",
            "recorded_manually", "raw_callback", "created_at", "updated_at",
        ]
        read_only_fields = fields


class PaymentAuditLogSerializer(serializers.ModelSerializer):
    performed_by_name = serializers.SerializerMethodField()
    action_label = serializers.CharField(source="get_action_display", read_only=True)

    class Meta:
        model = PaymentAuditLog
        fields = [
            "id", "action", "action_label", "from_status", "to_status", "amount",
            "reference", "reason", "performed_by_name", "created_at",
        ]
        read_only_fields = fields

    def get_performed_by_name(self, obj):
        user = obj.performed_by
        if not user:
            return "Unknown"
        return user.get_full_name() or user.email


class ManualPaymentSerializer(serializers.Serializer):
    """Body for "mark as paid" and "record refund": a reason is mandatory."""
    reason = serializers.CharField(min_length=5, max_length=255, trim_whitespace=True)
    reference = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    payment_id = serializers.UUIDField(required=False)  # refund only: pick one of several successful payments