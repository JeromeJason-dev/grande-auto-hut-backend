from django.contrib import admin
from .models import Cart, CartItem, Order, OrderItem, OrderStatusHistory


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "session_key", "updated_at")
    inlines = [CartItemInline]


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("product", "product_name", "product_sku", "unit_price", "quantity")
    can_delete = False


class OrderStatusHistoryInline(admin.TabularInline):
    model = OrderStatusHistory
    extra = 0
    readonly_fields = ("status", "changed_by", "note", "created_at")
    can_delete = False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("order_number", "user", "status", "payment_method", "total", "stock_reserved", "needs_attention", "created_at")
    list_filter = ("status", "payment_method", "stock_reserved", "cancelled_by_expiry")
    search_fields = ("order_number", "user__email")
    readonly_fields = (
        "order_number", "subtotal", "shipping_fee", "total", "stock_reserved",
        "reservation_expires_at", "cancelled_by_expiry", "created_at", "updated_at",
    )

    @admin.display(boolean=True, description="Needs attention")
    def needs_attention(self, obj):
        return bool(obj.attention_note)
    inlines = [OrderItemInline, OrderStatusHistoryInline]