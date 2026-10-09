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


class ProductSpecificationSerializer(serializers.Serializer):
    """
    Generic label/value row for the spec table on the product detail page.
    Assumes a related model (e.g. ProductSpecification with a FK to Product)
    exposed via a `specifications` related_name/manager on Product.
    """
    label = serializers.CharField()
    value = serializers.CharField()


class FitmentSummarySerializer(serializers.Serializer):
    """Lightweight 'this part fits' summary, used on the product detail page."""
    make = serializers.CharField(source="vehicle_year.model.make.name")
    model = serializers.CharField(source="vehicle_year.model.name")
    year = serializers.IntegerField(source="vehicle_year.year")
    notes = serializers.CharField()


class ProductListSerializer(serializers.ModelSerializer):
    """
    Compact representation for catalog grids / search results.

    It also carries everything the admin edit form needs to pre-fill
    (ids, description, stock, threshold, is_active).
    """
    category = serializers.CharField(source="category.name", read_only=True)
    brand = serializers.CharField(source="brand.name", read_only=True)
    category_id = serializers.UUIDField(read_only=True)
    brand_id = serializers.UUIDField(read_only=True)
    primary_image = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id", "sku", "name", "slug", "category", "category_id",
            "brand", "brand_id", "description", "condition",
            "price", "stock_quantity", "low_stock_threshold", "is_active",
            "is_in_stock", "is_low_stock", "primary_image",
        ]

    def get_primary_image(self, obj):
        image = obj.images.filter(is_primary=True).first() or obj.images.first()
        return image.image.url if image and image.image else None


class ProductDetailSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    brand = BrandSerializer(read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)
    fitments = FitmentSummarySerializer(many=True, read_only=True)

    # Extra product-detail fields. Each uses getattr(..., default) so this
    # won't crash if the underlying model field/relation doesn't exist yet.
    oem_number = serializers.SerializerMethodField()
    weight_kg = serializers.SerializerMethodField()
    warranty_months = serializers.SerializerMethodField()
    specifications = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id", "sku", "name", "slug", "category", "brand", "description",
            "condition", "price", "stock_quantity", "is_in_stock", "is_low_stock",
            "images", "fitments", "created_at", "updated_at",
            "oem_number", "weight_kg", "warranty_months", "specifications",
        ]

    def get_oem_number(self, obj):
        return getattr(obj, "oem_number", None)

    def get_weight_kg(self, obj):
        value = getattr(obj, "weight_kg", None)
        return str(value) if value is not None else None

    def get_warranty_months(self, obj):
        return getattr(obj, "warranty_months", None)

    def get_specifications(self, obj):
        specs = getattr(obj, "specifications", None)
        if specs is None:
            return []
        if hasattr(specs, "all"):
            return ProductSpecificationSerializer(specs.all(), many=True).data
        return specs


class ProductWriteSerializer(serializers.ModelSerializer):
    slug = serializers.SlugField(max_length=280, required=False, help_text="Auto-generated from name if omitted.")

    class Meta:
        model = Product
        fields = [
            "id", "sku", "name", "slug", "category", "brand", "description",
            "condition", "price", "stock_quantity", "low_stock_threshold", "is_active",
        ]
        read_only_fields = ["id"]

    def validate_slug(self, value):
        qs = Product.objects.filter(slug=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A product with this slug already exists.")
        return value

    def create(self, validated_data):
        if not validated_data.get("slug"):
            validated_data["slug"] = unique_slug(Product, validated_data["name"])
        return super().create(validated_data)