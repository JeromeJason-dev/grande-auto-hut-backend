import uuid
from django.db import models


class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey("orders.Order", related_name="payments", on_delete=models.CASCADE)
    method = models.CharField(
        max_length=20,
        choices=[("mpesa", "M-Pesa"), ("card", "Card"), ("cod", "Pay on Delivery")],
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    phone_number = models.CharField(max_length=15, blank=True)

    # M-Pesa Daraja specific fields
    mpesa_merchant_request_id = models.CharField(max_length=100, blank=True)
    mpesa_checkout_request_id = models.CharField(max_length=100, blank=True, unique=True, null=True)
    mpesa_receipt_number = models.CharField(max_length=50, blank=True)
    raw_callback = models.JSONField(null=True, blank=True)

    card_reference = models.CharField(max_length=100, blank=True, unique=True, null=True)
    card_brand = models.CharField(max_length=30, blank=True)
    card_last4 = models.CharField(max_length=4, blank=True)

    # True when an admin recorded this payment by hand (cash, bank transfer, a payment
    # verified on the M-Pesa statement ...) instead of a gateway confirming it.
    recorded_manually = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Payment({self.order.order_number}, {self.method}, {self.status})"


class PaymentAuditLog(models.Model):
    class Action(models.TextChoices):
        RECHECK = "recheck", "Re-checked with gateway"
        MARK_PAID = "mark_paid", "Marked as paid manually"
        REFUND = "refund", "Refund recorded"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey("orders.Order", related_name="payment_audit_logs", on_delete=models.CASCADE)
    payment = models.ForeignKey(Payment, related_name="audit_logs", null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=20, choices=Action.choices)
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    reference = models.CharField(max_length=100, blank=True)
    reason = models.CharField(max_length=255, blank=True)
    performed_by = models.ForeignKey("accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.order.order_number}: {self.action} ({self.from_status} -> {self.to_status})"