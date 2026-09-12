from django.urls import path
from .views import (
    CartView, CartItemCreateView, CartItemDetailView,
    CheckoutView, OrderListView, OrderDetailView, OrderStatusUpdateView,
)

urlpatterns = [
    path("cart/", CartView.as_view(), name="cart"),
    path("cart/items/", CartItemCreateView.as_view(), name="cart-item-add"),
    path("cart/items/<uuid:pk>/", CartItemDetailView.as_view(), name="cart-item-detail"),

    path("orders/checkout/", CheckoutView.as_view(), name="order-checkout"),
    path("orders/", OrderListView.as_view(), name="order-list"),
    path("orders/<uuid:id>/", OrderDetailView.as_view(), name="order-detail"),
    path("orders/<uuid:id>/status/", OrderStatusUpdateView.as_view(), name="order-status-update"),
]
