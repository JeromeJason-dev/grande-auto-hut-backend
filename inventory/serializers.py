from rest_framework import serializers
from .models import InventoryTransaction


class InventoryTransactionSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)

    class Meta:
        model = InventoryTransaction
        fields = [
            "id", "product", "product_name", "product_sku", "transaction_type",
            "quantity_change", "resulting_stock", "order", "note", "created_by", "created_at",
        ]
        read_only_fields = fields


class RestockSerializer(serializers.Serializer):
    product = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1)
    note = serializers.CharField(required=False, allow_blank=True, default="")
