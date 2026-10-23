import uuid
from django.db import models


class Notification(models.Model):
    class Type(models.TextChoices):
        ACCOUNT = "account", "Account"
        ORDER_UPDATE = "order_update", "Order Update"
        TICKET_REPLY = "ticket_reply", "Support Ticket Reply"
        NEW_TICKET = "new_ticket", "New Support Ticket"
        TICKET_MESSAGE = "ticket_message", "Customer Ticket Message"
        TICKET_ASSIGNED = "ticket_assigned", "Ticket Assigned"
        TASK_ASSIGNED = "task_assigned", "Task Assigned"
        GENERAL = "general", "General"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey("accounts.User", related_name="notifications", on_delete=models.CASCADE)
    notification_type = models.CharField(max_length=30, choices=Type.choices, default=Type.GENERAL)
    title = models.CharField(max_length=255)
    message = models.TextField(blank=True)
    link = models.CharField(max_length=255, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.email}: {self.title}"