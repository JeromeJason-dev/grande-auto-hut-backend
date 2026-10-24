from django.contrib import admin
from .models import Payment, PaymentAuditLog


class _ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class PaymentAuditLogInline(admin.TabularInline):
    model = PaymentAuditLog
    extra = 0
    can_delete = False
    fields = ("created_at", "action", "from_status", "to_status", "amount", "reference", "reason", "performed_by")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Payment)
class PaymentAdmin(_ReadOnlyAdmin):
    list_display = (
        "order", "method", "status", "amount", "phone_number", "mpesa_receipt_number",
        "card_reference", "recorded_manually", "created_at",
    )
    list_filter = ("method", "status", "recorded_manually")
    search_fields = ("order__order_number", "mpesa_checkout_request_id", "mpesa_receipt_number", "card_reference")
    inlines = [PaymentAuditLogInline]


@admin.register(PaymentAuditLog)
class PaymentAuditLogAdmin(_ReadOnlyAdmin):
    list_display = ("created_at", "order", "action", "from_status", "to_status", "amount", "performed_by", "reason")
    list_filter = ("action",)
    search_fields = ("order__order_number", "reference", "reason", "performed_by__email")