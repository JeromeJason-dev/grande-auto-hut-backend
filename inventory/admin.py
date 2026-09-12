from django.contrib import admin
from .models import InventoryTransaction


@admin.register(InventoryTransaction)
class InventoryTransactionAdmin(admin.ModelAdmin):
    list_display = ("product", "transaction_type", "quantity_change", "resulting_stock", "order", "created_at")
    list_filter = ("transaction_type",)
    search_fields = ("product__name", "product__sku")
    readonly_fields = [f.name for f in InventoryTransaction._meta.fields]

    def has_add_permission(self, request):
        return False  # append-only ledger; use the restock endpoint or order flow

    def has_change_permission(self, request, obj=None):
        return False
