from django.contrib import admin
from .models import Payment


admin.site.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("order", "method", "status", "amount", "phone_number", "mpesa_receipt_number", "created_at")
    list_filter = ("method", "status")
    search_fields = ("order__order_number", "mpesa_checkout_request_id", "mpesa_receipt_number")
    readonly_fields = ("raw_callback",)
