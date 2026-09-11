from rest_framework import serializers
from .models import VehicleMake, VehicleModel, VehicleYear, Fitment


class VehicleMakeSerializer(serializers.ModelSerializer):
    class Meta:
        model = VehicleMake
        fields = ["id", "name", "slug"]


class VehicleModelSerializer(serializers.ModelSerializer):
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
