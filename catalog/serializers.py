from rest_framework import serializers
from .models import Category, Brand, Product, ProductImage


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "slug", "parent", "is_active"]


class BrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = ["id", "name", "slug", "logo", "is_active"]


class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ["id", "image", "alt_text", "is_primary", "sort_order"]


class FitmentSummarySerializer(serializers.Serializer):
    """Lightweight 'this part fits' summary, used on the product detail page."""
    make = serializers.CharField(source="vehicle_year.model.make.name")
    model = serializers.CharField(source="vehicle_year.model.name")
    year = serializers.IntegerField(source="vehicle_year.year")
    notes = serializers.CharField()


class ProductListSerializer(serializers.ModelSerializer):
    """Compact representation for catalog grids / search results."""
    category = serializers.CharField(source="category.name", read_only=True)
    brand = serializers.CharField(source="brand.name", read_only=True)
    primary_image = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id", "sku", "name", "slug", "category", "brand", "condition",
            "price", "is_in_stock", "is_low_stock", "primary_image",
        ]

    def get_primary_image(self, obj):
        image = obj.images.filter(is_primary=True).first() or obj.images.first()
        return image.image.url if image and image.image else None


class ProductDetailSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    brand = BrandSerializer(read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)
    fitments = FitmentSummarySerializer(many=True, read_only=True)

    class Meta:
        model = Product
        fields = [
            "id", "sku", "name", "slug", "category", "brand", "description",
            "condition", "price", "stock_quantity", "is_in_stock", "is_low_stock",
            "images", "fitments", "created_at", "updated_at",
        ]


class ProductWriteSerializer(serializers.ModelSerializer):
    """Staff/admin create & update. Stock changes here are for corrections only
    - normal stock movement goes through the inventory app's transaction log."""

    class Meta:
        model = Product
        fields = [
            "id", "sku", "name", "slug", "category", "brand", "description",
            "condition", "price", "stock_quantity", "low_stock_threshold", "is_active",
        ]
        read_only_fields = ["id"]
