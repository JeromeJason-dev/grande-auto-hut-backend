import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


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

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    # Hours allowed (from ticket creation) before the team is considered late.
    FIRST_RESPONSE_HOURS = {"urgent": 1, "high": 4, "medium": 8, "low": 24}
    RESOLUTION_HOURS = {"urgent": 8, "high": 24, "medium": 48, "low": 72}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey("accounts.User", related_name="tickets", on_delete=models.CASCADE)
    order = models.ForeignKey("orders.Order", null=True, blank=True, related_name="tickets", on_delete=models.SET_NULL)
    subject = models.CharField(max_length=255)
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)

    # --- Team-side fields. Customers never see these. ---
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    assigned_to = models.ForeignKey(
        "accounts.User", null=True, blank=True, related_name="assigned_tickets", on_delete=models.SET_NULL,
    )
    is_archived = models.BooleanField(default=False)
    is_spam = models.BooleanField(default=False)
    # "Unread" from the support team's point of view: new ticket / new customer message.
    is_unread = models.BooleanField(default=True)
    first_response_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"[{self.status}] {self.subject}"

    @property
    def is_active_status(self):
        return self.status in (self.Status.OPEN, self.Status.IN_PROGRESS)

    @property
    def first_response_due(self):
        return self.created_at + timedelta(hours=self.FIRST_RESPONSE_HOURS[self.priority])

    @property
    def resolution_due(self):
        return self.created_at + timedelta(hours=self.RESOLUTION_HOURS[self.priority])

    @property
    def is_overdue(self):
        if not self.is_active_status:
            return False
        now = timezone.now()
        if self.first_response_at is None and now > self.first_response_due:
            return True
        return now > self.resolution_due

    def set_status(self, new_status):
        """Change status and keep `resolved_at` consistent. Caller saves."""
        self.status = new_status
        if new_status in (self.Status.RESOLVED, self.Status.CLOSED):
            if self.resolved_at is None:
                self.resolved_at = timezone.now()
        else:
            self.resolved_at = None


class TicketMessage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(Ticket, related_name="messages", on_delete=models.CASCADE)
    sender = models.ForeignKey("accounts.User", on_delete=models.CASCADE)
    message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Message on {self.ticket_id} by {self.sender.email}"


class TicketAttachment(models.Model):
    MAX_FILES_PER_MESSAGE = 5
    MAX_BYTES = 5 * 1024 * 1024
    ALLOWED_EXTENSIONS = {
        "pdf", "png", "jpg", "jpeg", "gif", "webp", "txt", "csv", "zip",
        "doc", "docx", "xls", "xlsx",
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(TicketMessage, related_name="attachments", on_delete=models.CASCADE)
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100, default="application/octet-stream")
    size = models.PositiveIntegerField()
    data = models.BinaryField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return self.filename


class Task(models.Model):
    class Status(models.TextChoices):
        TODO = "todo", "To do"
        IN_PROGRESS = "in_progress", "In progress"
        DONE = "done", "Done"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TODO)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    due_date = models.DateField(null=True, blank=True)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="tasks", on_delete=models.CASCADE)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, related_name="created_tasks", on_delete=models.SET_NULL,
    )
    ticket = models.ForeignKey(Ticket, null=True, blank=True, related_name="tasks", on_delete=models.SET_NULL)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"[{self.status}] {self.title}"

    @property
    def is_overdue(self):
        return bool(self.due_date and self.status != self.Status.DONE and self.due_date < timezone.localdate())

    def set_status(self, new_status):
        self.status = new_status
        self.completed_at = timezone.now() if new_status == self.Status.DONE else None