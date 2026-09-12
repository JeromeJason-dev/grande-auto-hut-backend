from django.db import transaction
from catalog.models import Product
from .models import InventoryTransaction


class InsufficientStockError(Exception):
    def __init__(self, product, requested, available):
        self.product = product
        self.requested = requested
        self.available = available
        super().__init__(f"Insufficient stock for {product.sku}: requested {requested}, available {available}")


def adjust_stock(product_id, delta, transaction_type, order=None, note="", user=None):
    with transaction.atomic():
        product = Product.objects.select_for_update().get(pk=product_id)
        new_stock = product.stock_quantity + delta
        if new_stock < 0:
            raise InsufficientStockError(product, requested=-delta, available=product.stock_quantity)

        product.stock_quantity = new_stock
        product.save(update_fields=["stock_quantity"])

        InventoryTransaction.objects.create(
            product=product,
            transaction_type=transaction_type,
            quantity_change=delta,
            resulting_stock=new_stock,
            order=order,
            note=note,
            created_by=user,
        )
        return product
