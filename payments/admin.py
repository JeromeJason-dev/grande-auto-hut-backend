from django.contrib import admin
from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("order", "method", "status", "amount", "phone_number", "mpesa_receipt_number", "card_reference", "created_at")
    list_filter = ("method", "status")
    search_fields = ("order__order_number", "mpesa_checkout_request_id", "mpesa_receipt_number", "card_reference")
    readonly_fields = ("raw_callback",)