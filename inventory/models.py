import uuid
from django.db import models


class InventoryTransaction(models.Model):
    class TransactionType(models.TextChoices):
        ORDER_CONFIRM = "order_confirm", "Order confirmed (stock reserved)"
        ORDER_CANCELLED_RESTOCK = "order_cancelled_restock", "Order cancelled (stock restored)"
        RESTOCK = "restock", "Restock / supplier delivery"
        ADJUSTMENT = "adjustment", "Manual correction"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey("catalog.Product", related_name="inventory_transactions", on_delete=models.CASCADE)
    transaction_type = models.CharField(max_length=30, choices=TransactionType.choices)
    quantity_change = models.IntegerField(help_text="Negative for stock leaving, positive for stock arriving.")
    resulting_stock = models.PositiveIntegerField(help_text="Product.stock_quantity snapshot right after this transaction.")
    order = models.ForeignKey("orders.Order", null=True, blank=True, related_name="inventory_transactions", on_delete=models.SET_NULL)
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey("accounts.User", null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.product.sku} {self.quantity_change:+d} ({self.transaction_type})"
