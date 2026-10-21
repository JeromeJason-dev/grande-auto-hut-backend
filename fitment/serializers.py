from django.utils.text import slugify
from rest_framework import serializers
from catalog.models import Product
from .models import VehicleMake, VehicleModel, VehicleYear, Fitment


def unique_slug(model, name, slug_field="slug", **scope):
    """Slugify `name` and, if it collides within `scope` (e.g. the same make),
    append -2, -3... until it's unique. Mirrors admin's prepopulated_fields
    for API clients that don't send a slug themselves."""
    base = slugify(name)
    slug = base
    suffix = 1
    while model.objects.filter(**{slug_field: slug}, **scope).exists():
        suffix += 1
        slug = f"{base}-{suffix}"
    return slug


class VehicleMakeSerializer(serializers.ModelSerializer):
    slug = serializers.SlugField(max_length=120, required=False, help_text="Auto-generated from name if omitted.")

    class Meta:
        model = VehicleMake
        fields = ["id", "name", "slug"]

    def create(self, validated_data):
        if not validated_data.get("slug"):
            validated_data["slug"] = unique_slug(VehicleMake, validated_data["name"])
        return super().create(validated_data)


class VehicleModelSerializer(serializers.ModelSerializer):
    slug = serializers.SlugField(max_length=120, required=False, help_text="Auto-generated from name if omitted.")

    class Meta:
        model = VehicleModel
        fields = ["id", "name", "slug"]


class VehicleYearSerializer(serializers.ModelSerializer):
    class Meta:
        model = VehicleYear
        fields = ["id", "year"]

    def validate_year(self, value):
        model = self.context.get("model") or getattr(self.instance, "model", None)
        if model is not None:
            duplicates = VehicleYear.objects.filter(model=model, year=value)
            if self.instance is not None:
                duplicates = duplicates.exclude(pk=self.instance.pk)
            if duplicates.exists():
                raise serializers.ValidationError("This year already exists for this model.")
        return value


class FitmentWriteSerializer(serializers.ModelSerializer):
    """Staff/admin: attach a product to a vehicle year."""

    class Meta:
        model = Fitment
        fields = ["id", "product", "vehicle_year", "notes"]
        # We validate uniqueness ourselves for a friendlier message.
        validators = []

    def validate(self, attrs):
        product = attrs.get("product", getattr(self.instance, "product", None))
        vehicle_year = attrs.get("vehicle_year", getattr(self.instance, "vehicle_year", None))
        duplicates = Fitment.objects.filter(product=product, vehicle_year=vehicle_year)
        if self.instance is not None:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise serializers.ValidationError("This product is already assigned to that vehicle.")
        return attrs


class FitmentReadSerializer(serializers.ModelSerializer):
    """Staff/admin: a fitment row with human-readable vehicle + product info."""
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    make = serializers.CharField(source="vehicle_year.model.make.name", read_only=True)
    make_slug = serializers.CharField(source="vehicle_year.model.make.slug", read_only=True)
    model = serializers.CharField(source="vehicle_year.model.name", read_only=True)
    model_slug = serializers.CharField(source="vehicle_year.model.slug", read_only=True)
    year = serializers.IntegerField(source="vehicle_year.year", read_only=True)

    class Meta:
        model = Fitment
        fields = [
            "id", "product", "product_name", "product_sku",
            "vehicle_year", "make", "make_slug", "model", "model_slug", "year",
            "notes", "created_at",
        ]


class FitmentBulkSerializer(serializers.Serializer):
    """Assign one product to many vehicle years in a single request."""
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    vehicle_years = serializers.PrimaryKeyRelatedField(
        queryset=VehicleYear.objects.all(), many=True, allow_empty=False
    )
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class FitmentSearchSerializer(serializers.Serializer):
    """Input fields for the customer-facing Fitment Finder."""

    make = serializers.CharField(
        max_length=120,
        trim_whitespace=True,
        help_text="Vehicle make slug, e.g. 'toyota'.",
    )
    model = serializers.CharField(
        max_length=120,
        trim_whitespace=True,
        help_text="Vehicle model slug, e.g. 'hilux'.",
    )
    year = serializers.IntegerField(
        min_value=1900,
        max_value=2100,
        help_text="Model year, e.g. 2018.",
    )
    part = serializers.CharField(
        max_length=140,
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        help_text="Optional part/category name or slug to narrow results, e.g. 'Brake Pads' or 'brake-pads'.",
    )

    def validate_part(self, value):
        return value.strip() or None