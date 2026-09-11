from rest_framework import serializers
from catalog.serializers import ProductListSerializer
from catalog.models import Product
from .models import Wishlist


class WishlistItemSerializer(serializers.ModelSerializer):
    product = ProductListSerializer(read_only=True)

    class Meta:
        model = Wishlist
        fields = ["id", "product", "created_at"]


class WishlistAddSerializer(serializers.Serializer):
    product = serializers.SlugRelatedField(slug_field="id", queryset=Product.objects.filter(is_active=True))
