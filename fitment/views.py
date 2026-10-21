from django.db.models import Q
from django.db import transaction
from rest_framework import generics, viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import NotFound
from accounts.permissions import AllowAnyReadOnlyOrStaffWrite, IsStaffOrAdmin
from catalog.serializers import ProductListSerializer
from catalog.models import Product
from .models import VehicleMake, VehicleModel, VehicleYear, Fitment
from .serializers import (
    VehicleMakeSerializer, VehicleModelSerializer, VehicleYearSerializer,
    FitmentWriteSerializer, FitmentReadSerializer, FitmentBulkSerializer,
    FitmentSearchSerializer, unique_slug,
)


class VehicleMakeListView(generics.ListCreateAPIView):
    """GET: public list of active vehicle makes.
    POST (staff/admin only): create a new make, e.g. {"name": "Toyota"}."""
    pagination_class = None  # dropdowns need the full list, not page 1 of 20
    queryset = VehicleMake.objects.filter(is_active=True)
    serializer_class = VehicleMakeSerializer
    permission_classes = [AllowAnyReadOnlyOrStaffWrite]


class VehicleModelListView(generics.ListCreateAPIView):
    """GET: public list of active models for the make in the URL.
    POST (staff/admin only): create a new model under that make."""
    pagination_class = None  # dropdowns need the full list, not page 1 of 20
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
    pagination_class = None  # dropdowns need the full list, not page 1 of 20
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

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["model"] = self.get_model()
        return context

    def perform_create(self, serializer):
        serializer.save(model=self.get_model())


class VehicleMakeDetailView(generics.RetrieveUpdateDestroyAPIView):
    """PATCH (staff/admin only): rename a make. DELETE: remove it, along with
    its models, years and fitments (cascade)."""
    queryset = VehicleMake.objects.all()
    serializer_class = VehicleMakeSerializer
    permission_classes = [AllowAnyReadOnlyOrStaffWrite]


class VehicleModelDetailView(generics.RetrieveUpdateDestroyAPIView):
    """PATCH (staff/admin only): rename a model. DELETE: remove it, along with
    its years and fitments (cascade)."""
    queryset = VehicleModel.objects.all()
    serializer_class = VehicleModelSerializer
    permission_classes = [AllowAnyReadOnlyOrStaffWrite]


class VehicleYearDetailView(generics.RetrieveUpdateDestroyAPIView):
    """PATCH (staff/admin only): change a model-year. DELETE: remove it, along
    with its fitments (cascade)."""
    queryset = VehicleYear.objects.all()
    serializer_class = VehicleYearSerializer
    permission_classes = [AllowAnyReadOnlyOrStaffWrite]


class FitmentProductSearchView(generics.ListAPIView):
    serializer_class = ProductListSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None  

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
    permission_classes = [IsStaffOrAdmin]
    pagination_class = None
    filter_backends = []

    def get_queryset(self):
        qs = Fitment.objects.select_related(
            "product", "vehicle_year__model__make"
        ).order_by("vehicle_year__model__make__name", "vehicle_year__model__name", "-vehicle_year__year")
        p = self.request.query_params
        if p.get("product"):
            qs = qs.filter(product_id=p["product"])
        if p.get("vehicle_year"):
            qs = qs.filter(vehicle_year_id=p["vehicle_year"])
        if p.get("make"):
            qs = qs.filter(vehicle_year__model__make__slug=p["make"])
        if p.get("model"):
            qs = qs.filter(vehicle_year__model__slug=p["model"])
        if p.get("year"):
            qs = qs.filter(vehicle_year__year=p["year"])
        return qs

    def get_serializer_class(self):
        if self.action == "bulk":
            return FitmentBulkSerializer
        if self.action in ("list", "retrieve"):
            return FitmentReadSerializer
        return FitmentWriteSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        fitment = serializer.save()
        return Response(FitmentReadSerializer(fitment).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        serializer = self.get_serializer(self.get_object(), data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        fitment = serializer.save()
        return Response(FitmentReadSerializer(fitment).data)

    @action(detail=False, methods=["post"], url_path="bulk")
    def bulk(self, request):
        """Assign a product to several vehicle years at once. Years that are
        already assigned are skipped rather than raising an error."""
        serializer = FitmentBulkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        product = serializer.validated_data["product"]
        notes = serializer.validated_data["notes"]
        created = []
        with transaction.atomic():
            for vehicle_year in serializer.validated_data["vehicle_years"]:
                fitment, was_created = Fitment.objects.get_or_create(
                    product=product, vehicle_year=vehicle_year, defaults={"notes": notes}
                )
                if was_created:
                    created.append(fitment.pk)
        skipped = len(serializer.validated_data["vehicle_years"]) - len(created)
        rows = self.get_queryset().filter(pk__in=created)
        return Response(
            {"created": len(created), "skipped": skipped, "results": FitmentReadSerializer(rows, many=True).data},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )