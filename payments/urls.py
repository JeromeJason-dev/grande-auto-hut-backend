from django.urls import path
from .views import (
    CardInitiateView, CardVerifyView, CardWebhookView, MpesaCallbackView, MpesaInitiateView,
)

urlpatterns = [
    path("payments/mpesa/initiate/", MpesaInitiateView.as_view(), name="mpesa-initiate"),
    path("payments/mpesa/callback/", MpesaCallbackView.as_view(), name="mpesa-callback"),
    path("payments/card/initiate/", CardInitiateView.as_view(), name="card-initiate"),
    path("payments/card/verify/", CardVerifyView.as_view(), name="card-verify"),
    path("payments/card/webhook/", CardWebhookView.as_view(), name="card-webhook"),
]