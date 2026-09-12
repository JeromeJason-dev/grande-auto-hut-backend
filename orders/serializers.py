from rest_framework import serializers
from accounts.models import Address
from catalog.models import Product
from catalog.serializers import ProductListSerializer
from .models import Cart, CartItem, Order, OrderItem, OrderStatusHistory


# Cart

class CartItemSerializer(serializers.ModelSerializer):
    product = ProductListSerializer(read_only=True)
    line_total = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = CartItem
        fields = ["id", "product", "quantity", "line_total", "added_at"]


class CartSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(many=True, read_only=True)
    subtotal = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = Cart
        fields = ["id", "items", "subtotal", "updated_at"]


class AddCartItemSerializer(serializers.Serializer):
    product = serializers.SlugRelatedField(slug_field="id", queryset=Product.objects.filter(is_active=True))
    quantity = serializers.IntegerField(min_value=1, default=1)


class UpdateCartItemSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=1)


# Checkout / Orders

class CheckoutSerializer(serializers.Serializer):
    payment_method = serializers.ChoiceField(choices=Order.PaymentMethod.choices)

    # Option A: reuse a saved address
    address_id = serializers.UUIDField(required=False)

    # Option B: one-off inline address
    recipient_name = serializers.CharField(required=False, max_length=150)
    phone_number = serializers.CharField(required=False, max_length=15)
    county = serializers.CharField(required=False, max_length=100)
    town = serializers.CharField(required=False, max_length=100)
    street_address = serializers.CharField(required=False, max_length=255)
    building_or_estate = serializers.CharField(required=False, allow_blank=True, max_length=255, default="")

    def validate(self, attrs):
        request = self.context["request"]
        if attrs.get("address_id"):
            address = Address.objects.filter(id=attrs["address_id"], user=request.user).first()
            if not address:
                raise serializers.ValidationError({"address_id": "Address not found on your account."})
            attrs["_resolved_address"] = {
                "recipient_name": address.recipient_name,
                "phone_number": address.phone_number,
                "county": address.county,
                "town": address.town,
                "street_address": address.street_address,
                "building_or_estate": address.building_or_estate,
            }
        else:
            required = ["recipient_name", "phone_number", "county", "town", "street_address"]
            missing = [f for f in required if not attrs.get(f)]
            if missing:
                raise serializers.ValidationError(
                    {"address": f"Provide address_id or all of: {', '.join(required)}. Missing: {', '.join(missing)}"}
                )
            attrs["_resolved_address"] = {
                "recipient_name": attrs["recipient_name"],
                "phone_number": attrs["phone_number"],
                "county": attrs["county"],
                "town": attrs["town"],
                "street_address": attrs["street_address"],
                "building_or_estate": attrs.get("building_or_estate", ""),
            }
        return attrs


class OrderItemSerializer(serializers.ModelSerializer):
    line_total = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = OrderItem
        fields = ["id", "product", "product_name", "product_sku", "unit_price", "quantity", "line_total"]


class OrderStatusHistorySerializer(serializers.ModelSerializer):
    changed_by_email = serializers.CharField(source="changed_by.email", read_only=True, default=None)

    class Meta:
        model = OrderStatusHistory
        fields = ["status", "note", "changed_by_email", "created_at"]


class OrderListSerializer(serializers.ModelSerializer):
    items_count = serializers.IntegerField(source="items.count", read_only=True)

    class Meta:
        model = Order
        fields = ["id", "order_number", "status", "payment_method", "total", "items_count", "created_at"]


class OrderDetailSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    status_history = OrderStatusHistorySerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = [
            "id", "order_number", "status", "payment_method",
            "recipient_name", "phone_number", "county", "town", "street_address", "building_or_estate",
            "subtotal", "shipping_fee", "total", "items", "status_history", "created_at", "updated_at",
        ]


class OrderStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Order.Status.choices)
    note = serializers.CharField(required=False, allow_blank=True, default="")
