import uuid
from django.db import models


class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey("orders.Order", related_name="payments", on_delete=models.CASCADE)
    method = models.CharField(max_length=20, choices=[("mpesa", "M-Pesa"), ("cod", "Pay on Delivery")])
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    phone_number = models.CharField(max_length=15, blank=True)

    # M-Pesa Daraja specific fields
    mpesa_merchant_request_id = models.CharField(max_length=100, blank=True)
    mpesa_checkout_request_id = models.CharField(max_length=100, blank=True, unique=True, null=True)
    mpesa_receipt_number = models.CharField(max_length=50, blank=True)
    raw_callback = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Payment({self.order.order_number}, {self.method}, {self.status})"
