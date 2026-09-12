from django.contrib import admin
from .models import Ticket, TicketMessage


class TicketMessageInline(admin.TabularInline):
    model = TicketMessage
    extra = 0
    readonly_fields = ("sender", "message", "created_at")


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("subject", "user", "category", "status", "created_at")
    list_filter = ("category", "status")
    search_fields = ("subject", "user__email")
    inlines = [TicketMessageInline]
