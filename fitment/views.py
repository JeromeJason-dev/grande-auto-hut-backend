from django.db.models import Q
from rest_framework import generics, viewsets, permissions
from rest_framework.exceptions import NotFound
from accounts.permissions import AllowAnyReadOnlyOrStaffWrite
from catalog.serializers import ProductListSerializer
from catalog.models import Product
from .models import VehicleMake, VehicleModel, VehicleYear, Fitment
from .serializers import (
    VehicleMakeSerializer, VehicleModelSerializer, VehicleYearSerializer,
    FitmentWriteSerializer, FitmentSearchSerializer, unique_slug,
)


class VehicleMakeListView(generics.ListCreateAPIView):
    """GET: public list of active vehicle makes.
    POST (staff/admin only): create a new make, e.g. {"name": "Toyota"}."""
    queryset = VehicleMake.objects.filter(is_active=True)
    serializer_class = VehicleMakeSerializer
    permission_classes = [AllowAnyReadOnlyOrStaffWrite]


class VehicleModelListView(generics.ListCreateAPIView):
    """GET: public list of active models for the make in the URL.
    POST (staff/admin only): create a new model under that make."""
    serializer_class = VehicleModelSerializer
    permission_classes = [AllowAnyReadOnlyOrStaffWrite]

    def get_make(self):
        make_slug = self.kwargs["make_slug"]
        make = VehicleMake.objects.filter(slug=make_slug, is_active=True).first()
        if not make:
            raise NotFound(f"Unknown vehicle make '{make_slug}'.")
        return make

    def get_queryset(self):
        make = self.get_make()
        return VehicleModel.objects.filter(make=make, is_active=True)

    def perform_create(self, serializer):
        make = self.get_make()
        slug = serializer.validated_data.get("slug") or unique_slug(
            VehicleModel, serializer.validated_data["name"], make=make
        )
        serializer.save(make=make, slug=slug)


class VehicleYearListView(generics.ListCreateAPIView):
    """GET: public list of years for the make/model in the URL.
    POST (staff/admin only): create a new model-year."""
    serializer_class = VehicleYearSerializer
    permission_classes = [AllowAnyReadOnlyOrStaffWrite]

    def get_model(self):
        make_slug = self.kwargs["make_slug"]
        model_slug = self.kwargs["model_slug"]
        model = VehicleModel.objects.filter(
            make__slug=make_slug, slug=model_slug, is_active=True
        ).first()
        if not model:
            raise NotFound(f"Unknown vehicle model '{model_slug}' for make '{make_slug}'.")
        return model

    def get_queryset(self):
        model = self.get_model()
        return VehicleYear.objects.filter(model=model)

    def perform_create(self, serializer):
        serializer.save(model=self.get_model())


class FitmentProductSearchView(generics.ListAPIView):
    serializer_class = ProductListSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        params = FitmentSearchSerializer(data=self.request.query_params)
        params.is_valid(raise_exception=True)
        make = params.validated_data["make"]
        model = params.validated_data["model"]
        year = params.validated_data["year"]
        part = params.validated_data.get("part")

        vehicle_year = VehicleYear.objects.filter(
            model__make__slug=make, model__slug=model, year=year
        ).first()
        if not vehicle_year:
            raise NotFound("No matching vehicle found for that make/model/year combination.")

        queryset = Product.objects.filter(
            vehicle_years=vehicle_year, is_active=True
        ).select_related("category", "brand").prefetch_related("images").distinct()

        if part:
            queryset = queryset.filter(
                Q(category__slug__iexact=part) | Q(category__name__icontains=part)
            ).distinct()

        return queryset


class FitmentViewSet(viewsets.ModelViewSet):
    queryset = Fitment.objects.select_related("product", "vehicle_year")
    serializer_class = FitmentWriteSerializer
    permission_classes = [AllowAnyReadOnlyOrStaffWrite]