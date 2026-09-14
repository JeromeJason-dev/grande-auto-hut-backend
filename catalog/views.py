from django_filters.rest_framework import DjangoFilterBackend, FilterSet, filters
from rest_framework import generics, filters as drf_filters
from accounts.permissions import AllowAnyReadOnlyOrStaffWrite
from .models import Category, Brand, Product
from .serializers import (
    CategorySerializer, BrandSerializer, 
    ProductListSerializer, ProductDetailSerializer
)

# --- Categories ---
class CategoryListView(generics.ListAPIView):
    queryset = Category.objects.filter(is_active=True)
    serializer_class = CategorySerializer
    permission_classes = [AllowAnyReadOnlyOrStaffWrite]

class CategoryDetailView(generics.RetrieveAPIView):
    queryset = Category.objects.filter(is_active=True)
    serializer_class = CategorySerializer
    permission_classes = [AllowAnyReadOnlyOrStaffWrite]
    lookup_field = "pk"  # Matches <uuid:pk> in urls.py


# --- Brands ---
class BrandListView(generics.ListAPIView):
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
class ProductListView(generics.ListAPIView):
    queryset = Product.objects.filter(is_active=True).select_related("category", "brand")
    serializer_class = ProductListSerializer
    permission_classes = [AllowAnyReadOnlyOrStaffWrite]
    filter_backends = [DjangoFilterBackend, drf_filters.SearchFilter, drf_filters.OrderingFilter]
    filterset_class = ProductFilter
    search_fields = ["name", "sku", "description"]
    ordering_fields = ["price", "created_at", "name"]
    ordering = ["-created_at"]

class ProductDetailView(generics.RetrieveAPIView):
    queryset = Product.objects.filter(is_active=True).select_related("category", "brand").prefetch_related(
        "images", "fitments__vehicle_year__model__make"
    )
    serializer_class = ProductDetailSerializer
    permission_classes = [AllowAnyReadOnlyOrStaffWrite]
    lookup_field = "pk"  