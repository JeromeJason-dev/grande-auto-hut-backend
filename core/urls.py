from django.urls import path
from .views import WishlistListView, WishlistAddView, WishlistRemoveView, AdminMetricsView

urlpatterns = [
    path("wishlist/", WishlistListView.as_view(), name="wishlist-list"),
    path("wishlist/items/", WishlistAddView.as_view(), name="wishlist-add"),
    path("wishlist/items/<uuid:product_id>/", WishlistRemoveView.as_view(), name="wishlist-remove"),
    path("admin/metrics/", AdminMetricsView.as_view(), name="admin-metrics"),
]
