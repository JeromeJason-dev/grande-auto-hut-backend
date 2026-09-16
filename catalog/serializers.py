from django.utils.text import slugify
from rest_framework import serializers
from .models import Category, Brand, Product, ProductImage


def unique_slug(model, name, slug_field="slug"):
    base = slugify(name)
    slug = base
    suffix = 1
    while model.objects.filter(**{slug_field: slug}).exists():
        suffix += 1
        slug = f"{base}-{suffix}"
    return slug


class CategorySerializer(serializers.ModelSerializer):
    slug = serializers.SlugField(max_length=140, required=False, help_text="Auto-generated from name if omitted.")

    class Meta:
        model = Category
        fields = ["id", "name", "slug", "parent", "is_active"]

    def create(self, validated_data):
        if not validated_data.get("slug"):
            validated_data["slug"] = unique_slug(Category, validated_data["name"])
        return super().create(validated_data)


class BrandSerializer(serializers.ModelSerializer):
    slug = serializers.SlugField(max_length=140, required=False, help_text="Auto-generated from name if omitted.")

    class Meta:
        model = Brand
        fields = ["id", "name", "slug", "logo", "is_active"]

    def create(self, validated_data):
        if not validated_data.get("slug"):
            validated_data["slug"] = unique_slug(Brand, validated_data["name"])
        return super().create(validated_data)


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
    slug = serializers.SlugField(max_length=280, required=False, help_text="Auto-generated from name if omitted.")

    class Meta:
        model = Product
        fields = [
            "id", "sku", "name", "slug", "category", "brand", "description",
            "condition", "price", "stock_quantity", "low_stock_threshold", "is_active",
        ]
        read_only_fields = ["id"]

    def create(self, validated_data):
        if not validated_data.get("slug"):
            validated_data["slug"] = unique_slug(Product, validated_data["name"])
        return super().create(validated_data)