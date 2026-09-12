from rest_framework import generics, viewsets, permissions
from rest_framework.exceptions import ValidationError, NotFound
from accounts.permissions import AllowAnyReadOnlyOrStaffWrite
from catalog.serializers import ProductListSerializer
from catalog.models import Product
from .models import VehicleMake, VehicleModel, VehicleYear, Fitment
from .serializers import (
    VehicleMakeSerializer, VehicleModelSerializer, VehicleYearSerializer, FitmentWriteSerializer,
)


class VehicleMakeListView(generics.ListAPIView):
    queryset = VehicleMake.objects.filter(is_active=True)
    serializer_class = VehicleMakeSerializer
    permission_classes = [permissions.AllowAny]


class VehicleModelListView(generics.ListAPIView):
    serializer_class = VehicleModelSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        make_slug = self.kwargs["make_slug"]
        if not VehicleMake.objects.filter(slug=make_slug, is_active=True).exists():
            raise NotFound(f"Unknown vehicle make '{make_slug}'.")
        return VehicleModel.objects.filter(make__slug=make_slug, is_active=True)


class VehicleYearListView(generics.ListAPIView):
    serializer_class = VehicleYearSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        make_slug = self.kwargs["make_slug"]
        model_slug = self.kwargs["model_slug"]
        if not VehicleModel.objects.filter(make__slug=make_slug, slug=model_slug, is_active=True).exists():
            raise NotFound(f"Unknown vehicle model '{model_slug}' for make '{make_slug}'.")
        return VehicleYear.objects.filter(model__make__slug=make_slug, model__slug=model_slug)


class FitmentProductSearchView(generics.ListAPIView):
    serializer_class = ProductListSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        make = self.request.query_params.get("make")
        model = self.request.query_params.get("model")
        year = self.request.query_params.get("year")

        if not (make and model and year):
            raise ValidationError("Query params 'make', 'model', and 'year' are all required.")

        try:
            year = int(year)
        except ValueError:
            raise ValidationError("'year' must be an integer.")

        vehicle_year = VehicleYear.objects.filter(
            model__make__slug=make, model__slug=model, year=year
        ).first()
        if not vehicle_year:
            raise NotFound("No matching vehicle found for that make/model/year combination.")

        return Product.objects.filter(
            vehicle_years=vehicle_year, is_active=True
        ).select_related("category", "brand").prefetch_related("images").distinct()


class FitmentViewSet(viewsets.ModelViewSet):
    queryset = Fitment.objects.select_related("product", "vehicle_year")
    serializer_class = FitmentWriteSerializer
    permission_classes = [AllowAnyReadOnlyOrStaffWrite]
