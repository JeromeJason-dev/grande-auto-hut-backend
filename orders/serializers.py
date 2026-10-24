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


class CustomerFieldsMixin(serializers.Serializer):
    """Shared customer info, read from the order's related user."""

    customer_name = serializers.SerializerMethodField()
    customer_email = serializers.EmailField(source="user.email", read_only=True)

    def get_customer_name(self, obj):
        user = obj.user
        full_name = ""
        get_full_name = getattr(user, "get_full_name", None)
        if callable(get_full_name):
            full_name = (get_full_name() or "").strip()
        # Fall back to the delivery recipient, then the account email.
        return full_name or obj.recipient_name or user.email


class OrderListSerializer(CustomerFieldsMixin, serializers.ModelSerializer):
    payment_status = serializers.CharField(read_only=True)
    items_count = serializers.SerializerMethodField()
    total_quantity = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id", "order_number", "status",
            "customer_name", "customer_email",
            "payment_method", "payment_status",
            "total", "items_count", "total_quantity", "created_at",
        ]

    # OrderListView annotates these so the list costs no per-row queries.
    # The fallbacks keep this serializer correct if used on a plain queryset.
    def get_items_count(self, obj):
        value = getattr(obj, "items_count", None)
        return value if value is not None else obj.items.count()

    def get_total_quantity(self, obj):
        value = getattr(obj, "total_quantity", None)
        if value is not None:
            return value
        return sum(item.quantity for item in obj.items.all())


class OrderDetailSerializer(CustomerFieldsMixin, serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    status_history = OrderStatusHistorySerializer(many=True, read_only=True)
    payment_status = serializers.CharField(read_only=True)

    class Meta:
        model = Order
        fields = [
            "id", "order_number", "status", "payment_method", "payment_status",
            "customer_name", "customer_email",
            "recipient_name", "phone_number", "county", "town", "street_address", "building_or_estate",
            "subtotal", "shipping_fee", "total", "items", "status_history", "created_at", "updated_at",
        ]


class OrderStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Order.Status.choices)
    note = serializers.CharField(required=False, allow_blank=True, default="")