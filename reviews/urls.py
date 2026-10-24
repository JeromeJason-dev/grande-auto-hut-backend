from django.urls import path
from .views import ProductReviewListCreateView, MyReviewDeleteView, StaffReviewListView

urlpatterns = [
    path("reviews/", StaffReviewListView.as_view(), name="staff-review-list"),
    path("products/<uuid:product_id>/reviews/", ProductReviewListCreateView.as_view(), name="product-reviews"),
    path("reviews/<uuid:id>/", MyReviewDeleteView.as_view(), name="review-delete"),
]