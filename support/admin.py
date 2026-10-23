from django.contrib import admin
from .models import Ticket, TicketMessage, TicketAttachment, Task


class TicketMessageInline(admin.TabularInline):
    model = TicketMessage
    extra = 0
    readonly_fields = ("sender", "message", "created_at")


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("subject", "user", "category", "status", "priority", "assigned_to", "created_at")
    list_filter = ("category", "status", "priority", "is_archived", "is_spam")
    search_fields = ("subject", "user__email")
    inlines = [TicketMessageInline]


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("title", "assigned_to", "status", "priority", "due_date", "ticket")
    list_filter = ("status", "priority")
    search_fields = ("title", "assigned_to__email")


@admin.register(TicketAttachment)
class TicketAttachmentAdmin(admin.ModelAdmin):
    list_display = ("filename", "content_type", "size", "created_at")
    exclude = ("data",)
    readonly_fields = ("message", "filename", "content_type", "size", "created_at")