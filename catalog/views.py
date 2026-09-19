from django_filters.rest_framework import DjangoFilterBackend, FilterSet, filters
from rest_framework import generics, filters as drf_filters
from accounts.permissions import AllowAnyReadOnlyOrStaffWrite
from .models import Category, Brand, Product, ProductFamily
from .serializers import (
    CategorySerializer, BrandSerializer,
    ProductListSerializer, ProductDetailSerializer, ProductWriteSerializer,
    ProductFamilySerializer,
)

# --- Categories ---
class CategoryListView(generics.ListCreateAPIView):
    queryset = Category.objects.filter(is_active=True)
    serializer_class = CategorySerializer
    permission_classes = [AllowAnyReadOnlyOrStaffWrite]

class CategoryDetailView(generics.RetrieveAPIView):
    queryset = Category.objects.filter(is_active=True)
    serializer_class = CategorySerializer
    permission_classes = [AllowAnyReadOnlyOrStaffWrite]
    lookup_field = "pk"  # Matches <uuid:pk> in urls.py


# --- Brands ---
class BrandListView(generics.ListCreateAPIView):
    queryset = Brand.objects.filter(is_active=True)
    serializer_class = BrandSerializer
    permission_classes = [AllowAnyReadOnlyOrStaffWrite]

class BrandDetailView(generics.RetrieveAPIView):
    queryset = Brand.objects.filter(is_active=True)
    serializer_class = BrandSerializer
    permission_classes = [AllowAnyReadOnlyOrStaffWrite]
    lookup_field = "pk"  # Matches <uuid:pk> in urls.py


# --- Product Families ---
class ProductFamilyListView(generics.ListCreateAPIView):
    """
    Create a family here first (e.g. POST {"name": "Aluminum Engine
    Coolant Radiator", "category": <category-id>}), then attach products
    to it by setting `family` to this family's id on each Product, 
    or passing `product_ids` directly.
    """
    queryset = ProductFamily.objects.filter(is_active=True).select_related("category").prefetch_related("variants__images")
    serializer_class = ProductFamilySerializer
    permission_classes = [AllowAnyReadOnlyOrStaffWrite]

class ProductFamilyDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = ProductFamily.objects.filter(is_active=True).select_related("category").prefetch_related("variants__images")
    serializer_class = ProductFamilySerializer
    permission_classes = [AllowAnyReadOnlyOrStaffWrite]
    lookup_field = "pk"


# --- Products Filter ---
class ProductFilter(FilterSet):
    min_price = filters.NumberFilter(field_name="price", lookup_expr="gte")
    max_price = filters.NumberFilter(field_name="price", lookup_expr="lte")
    category = filters.CharFilter(field_name="category__slug")
    brand = filters.CharFilter(field_name="brand__slug")
    condition = filters.ChoiceFilter(choices=Product.Condition.choices)
    in_stock = filters.BooleanFilter(method="filter_in_stock")
    # Lets the frontend fetch every variant that belongs to one family:
    # GET /products/?family_slug=aluminum-engine-coolant-radiator
    family_slug = filters.CharFilter(field_name="family__slug")

    def filter_in_stock(self, queryset, name, value):
        return queryset.filter(stock_quantity__gt=0) if value else queryset.filter(stock_quantity=0)

    class Meta:
        model = Product
        fields = ["category", "brand", "condition", "min_price", "max_price", "in_stock", "family_slug"]


# --- Products ---
class ProductListView(generics.ListCreateAPIView):
    queryset = Product.objects.filter(is_active=True).select_related("category", "brand", "family")
    permission_classes = [AllowAnyReadOnlyOrStaffWrite]
    filter_backends = [DjangoFilterBackend, drf_filters.SearchFilter, drf_filters.OrderingFilter]
    filterset_class = ProductFilter
    search_fields = ["name", "sku", "description"]
    ordering_fields = ["price", "created_at", "name"]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        return ProductWriteSerializer if self.request.method == "POST" else ProductListSerializer

class ProductDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Product.objects.filter(is_active=True).select_related("category", "brand", "family").prefetch_related(
        "images", "fitments__vehicle_year__model__make"
    )
    permission_classes = [AllowAnyReadOnlyOrStaffWrite]
    lookup_field = "pk"

    def get_serializer_class(self):
        return ProductWriteSerializer if self.request.method in ("PUT", "PATCH") else ProductDetailSerializer