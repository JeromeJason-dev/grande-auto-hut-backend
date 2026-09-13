import re
from rest_framework import serializers
from .models import Payment


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


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ["id", "order", "method", "status", "amount", "phone_number", "mpesa_receipt_number", "created_at"]
        read_only_fields = fields
