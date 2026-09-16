from django.utils.text import slugify
from rest_framework import serializers
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


class FitmentWriteSerializer(serializers.ModelSerializer):
    """Staff/admin: attach a product to a vehicle year."""

    class Meta:
        model = Fitment
        fields = ["id", "product", "vehicle_year", "notes"]


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