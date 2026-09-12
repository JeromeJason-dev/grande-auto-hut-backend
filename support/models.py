import uuid
from django.db import models


class Ticket(models.Model):
    class Category(models.TextChoices):
        ORDER = "order", "Order Issue"
        PRODUCT = "product", "Product Question"
        PAYMENT = "payment", "Payment Issue"
        ACCOUNT = "account", "Account"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In Progress"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey("accounts.User", related_name="tickets", on_delete=models.CASCADE)
    order = models.ForeignKey("orders.Order", null=True, blank=True, related_name="tickets", on_delete=models.SET_NULL)
    subject = models.CharField(max_length=255)
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"[{self.status}] {self.subject}"


class TicketMessage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(Ticket, related_name="messages", on_delete=models.CASCADE)
    sender = models.ForeignKey("accounts.User", on_delete=models.CASCADE)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Message on {self.ticket_id} by {self.sender.email}"
