from django_filters.rest_framework import DjangoFilterBackend, FilterSet, filters
from rest_framework import generics, filters as drf_filters
from accounts.permissions import AllowAnyReadOnlyOrStaffWrite
from .models import Category, Brand, Product
from .serializers import (
    CategorySerializer, BrandSerializer, 
    ProductListSerializer, ProductDetailSerializer, ProductWriteSerializer,
)

# --- Categories ---
class CategoryListView(generics.ListCreateAPIView):
    """GET: public list of active categories.
    POST (staff/admin only): create a new part category, e.g. {"name": "Brake Pads"}.
    'slug' is optional and auto-generated from 'name' if omitted."""
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
    """GET: public list of active brands.
    POST (staff/admin only): create a new brand, e.g. {"name": "Bosch"}.
    'slug' is optional and auto-generated from 'name' if omitted."""
    queryset = Brand.objects.filter(is_active=True)
    serializer_class = BrandSerializer
    permission_classes = [AllowAnyReadOnlyOrStaffWrite]

class BrandDetailView(generics.RetrieveAPIView):
    queryset = Brand.objects.filter(is_active=True)
    serializer_class = BrandSerializer
    permission_classes = [AllowAnyReadOnlyOrStaffWrite]
    lookup_field = "pk"  # Matches <uuid:pk> in urls.py


# --- Products Filter ---
class ProductFilter(FilterSet):
    min_price = filters.NumberFilter(field_name="price", lookup_expr="gte")
    max_price = filters.NumberFilter(field_name="price", lookup_expr="lte")
    category = filters.CharFilter(field_name="category__slug")
    brand = filters.CharFilter(field_name="brand__slug")
    condition = filters.ChoiceFilter(choices=Product.Condition.choices)
    in_stock = filters.BooleanFilter(method="filter_in_stock")

    def filter_in_stock(self, queryset, name, value):
        return queryset.filter(stock_quantity__gt=0) if value else queryset.filter(stock_quantity=0)

    class Meta:
        model = Product
        fields = ["category", "brand", "condition", "min_price", "max_price", "in_stock"]


# --- Products ---
class ProductListView(generics.ListCreateAPIView):
    """GET: public, filterable/searchable product list.
    POST (staff/admin only): create a new product. Required fields: sku, name,
    category (id), brand (id), price. 'slug' is optional and auto-generated
    from 'name' if omitted. This only creates the product itself - link it to
    the vehicles it fits separately via POST /fitments/ (see FitmentViewSet)."""

    queryset = Product.objects.filter(is_active=True).select_related("category", "brand")
    permission_classes = [AllowAnyReadOnlyOrStaffWrite]
    filter_backends = [DjangoFilterBackend, drf_filters.SearchFilter, drf_filters.OrderingFilter]
    filterset_class = ProductFilter
    search_fields = ["name", "sku", "description"]
    ordering_fields = ["price", "created_at", "name"]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        return ProductWriteSerializer if self.request.method == "POST" else ProductListSerializer

class ProductDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET: public read product detail.
    PUT/PATCH (staff/admin only): update product fields.
    DELETE (staff/admin only): delete product record.
    """
    queryset = Product.objects.filter(is_active=True).select_related("category", "brand").prefetch_related(
        "images", "fitments__vehicle_year__model__make"
    )
    permission_classes = [AllowAnyReadOnlyOrStaffWrite]
    lookup_field = "pk"

    def get_serializer_class(self):
        return ProductWriteSerializer if self.request.method in ("PUT", "PATCH") else ProductDetailSerializer