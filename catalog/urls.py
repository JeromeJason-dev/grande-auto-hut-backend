from django.urls import path
from .views import (
    CategoryListView, CategoryDetailView,
    BrandListView, BrandDetailView,
    ProductListView, ProductDetailView
)

urlpatterns = [
    # --- Categories ---
    path("categories/", CategoryListView.as_view(), name="category-list"),
    path("categories/<uuid:pk>/", CategoryDetailView.as_view(), name="category-detail"),

    # --- Brands ---
    path("brands/", BrandListView.as_view(), name="brand-list"),
    path("brands/<uuid:pk>/", BrandDetailView.as_view(), name="brand-detail"),

    # --- Products ---
    path("products/", ProductListView.as_view(), name="product-list"),
    path("products/<uuid:pk>/", ProductDetailView.as_view(), name="product-detail"),
]