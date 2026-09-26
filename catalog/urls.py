from django.urls import path
from .views import (
    CategoryListView, CategoryDetailView,
    BrandListView, BrandDetailView,
    ProductFamilyListView, ProductFamilyDetailView,
    ProductListView, ProductDetailView
)

urlpatterns = [
    # --- Categories ---
    path("categories/", CategoryListView.as_view(), name="category-list"),
    path("categories/<uuid:pk>/", CategoryDetailView.as_view(), name="category-detail"),

    # --- Brands ---
    path("brands/", BrandListView.as_view(), name="brand-list"),
    path("brands/<uuid:pk>/", BrandDetailView.as_view(), name="brand-detail"),

    # --- Product Families ---
    path("product-families/", ProductFamilyListView.as_view(), name="product-family-list"),
    path("product-families/<uuid:pk>/", ProductFamilyDetailView.as_view(), name="product-family-detail"),

    # --- Products ---
    path("products/", ProductListView.as_view(), name="product-list"),
    # Fixed: ProductDetailView now looks up by slug (see views.py),
    # so the URL converter must accept a slug string, not a UUID.
    path("products/<slug:slug>/", ProductDetailView.as_view(), name="product-detail"),
]