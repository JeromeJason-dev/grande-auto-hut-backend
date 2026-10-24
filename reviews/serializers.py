from rest_framework import serializers
from orders.models import Order, OrderItem
from .models import Review


class ReviewSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()
    verified_purchase = serializers.BooleanField(source="order_item", read_only=True)

    class Meta:
        model = Review
        fields = ["id", "user_name", "product", "rating", "comment", "verified_purchase", "created_at"]
        read_only_fields = fields

    def get_user_name(self, obj):
        first = obj.user.first_name
        return first if first else obj.user.email.split("@")[0]


class StaffReviewSerializer(serializers.ModelSerializer):
    """Everything the support team needs to read a review in context (staff/admin only)."""
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_slug = serializers.CharField(source="product.slug", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    customer_name = serializers.SerializerMethodField()
    customer_email = serializers.CharField(source="user.email", read_only=True)
    verified_purchase = serializers.SerializerMethodField()
    order_number = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = [
            "id", "product", "product_name", "product_slug", "product_sku",
            "customer_name", "customer_email", "rating", "comment",
            "verified_purchase", "order_number", "created_at", "updated_at",
        ]
        read_only_fields = fields

    def get_customer_name(self, obj):
        return (obj.user.get_full_name() or "").strip() or obj.user.email.split("@")[0]

    def get_verified_purchase(self, obj):
        return obj.order_item_id is not None

    def get_order_number(self, obj):
        return obj.order_item.order.order_number if obj.order_item_id else None


class ReviewWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ["id", "product", "rating", "comment"]
        read_only_fields = ["id"]

    def validate(self, attrs):
        request = self.context["request"]
        product = attrs["product"]

        if Review.objects.filter(user=request.user, product=product).exists():
            raise serializers.ValidationError("You've already reviewed this product.")

        delivered_item = (
            OrderItem.objects.filter(
                order__user=request.user,
                order__status=Order.Status.DELIVERED,
                product=product,
            )
            .order_by("-order__created_at")
            .first()
        )
        if not delivered_item:
            raise serializers.ValidationError(
                "You can only review products from an order that has been delivered to you."
            )
        attrs["_order_item"] = delivered_item
        return attrs

    def create(self, validated_data):
        order_item = validated_data.pop("_order_item")
        return Review.objects.create(user=self.context["request"].user, order_item=order_item, **validated_data)