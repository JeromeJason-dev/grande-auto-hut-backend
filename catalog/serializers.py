from django.utils.text import slugify
from rest_framework import serializers
from .models import Category, Brand, Product, ProductImage, ProductFamily


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


class ProductFamilySerializer(serializers.ModelSerializer):
    """
    Read/write representation of a physical part that groups condition
    variants together. Used both as its own endpoint (so an admin can
    create a family before attaching products to it) and nested inside
    product responses.
    """
    slug = serializers.SlugField(max_length=280, required=False, help_text="Auto-generated from name if omitted.")
    category = serializers.CharField(source="category.name", read_only=True)
    variant_count = serializers.IntegerField(source="variants.count", read_only=True)

    class Meta:
        model = ProductFamily
        fields = ["id", "name", "slug", "category", "is_active", "variant_count"]

    def create(self, validated_data):
        if not validated_data.get("slug"):
            validated_data["slug"] = unique_slug(ProductFamily, validated_data["name"])
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
    # Null when the product hasn't been assigned to a family - the
    # frontend treats that as a "family of one" and doesn't merge it
    # with anything.
    family_slug = serializers.SerializerMethodField()
    family_name = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id", "sku", "name", "slug", "category", "brand", "condition",
            "price", "is_in_stock", "is_low_stock", "primary_image",
            "family_slug", "family_name",
        ]

    def get_primary_image(self, obj):
        image = obj.images.filter(is_primary=True).first() or obj.images.first()
        return image.image.url if image and image.image else None

    def get_family_slug(self, obj):
        return obj.family.slug if obj.family_id else None

    def get_family_name(self, obj):
        return obj.family.name if obj.family_id else None


class ProductDetailSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    brand = BrandSerializer(read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)
    fitments = FitmentSummarySerializer(many=True, read_only=True)
    family = ProductFamilySerializer(read_only=True)

    class Meta:
        model = Product
        fields = [
            "id", "sku", "name", "slug", "category", "brand", "description",
            "condition", "price", "stock_quantity", "is_in_stock", "is_low_stock",
            "images", "fitments", "family", "created_at", "updated_at",
        ]


class ProductWriteSerializer(serializers.ModelSerializer):
    slug = serializers.SlugField(max_length=280, required=False, help_text="Auto-generated from name if omitted.")
    # Accepts a ProductFamily id. Omit or pass null to leave a product
    # standalone; pass the same family id on two products to group them.
    family = serializers.PrimaryKeyRelatedField(
        queryset=ProductFamily.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = Product
        fields = [
            "id", "sku", "name", "slug", "category", "brand", "description",
            "condition", "price", "stock_quantity", "low_stock_threshold", "is_active",
            "family",
        ]
        read_only_fields = ["id"]

    def create(self, validated_data):
        if not validated_data.get("slug"):
            validated_data["slug"] = unique_slug(Product, validated_data["name"])
        return super().create(validated_data)