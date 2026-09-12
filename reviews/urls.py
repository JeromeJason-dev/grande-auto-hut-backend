from django.urls import path
from .views import ProductReviewListCreateView, MyReviewDeleteView

urlpatterns = [
    path("products/<uuid:product_id>/reviews/", ProductReviewListCreateView.as_view(), name="product-reviews"),
    path("reviews/<uuid:id>/", MyReviewDeleteView.as_view(), name="review-delete"),
]
