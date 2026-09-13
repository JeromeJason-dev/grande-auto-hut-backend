from django.urls import path
from .views import MpesaInitiateView, MpesaCallbackView

urlpatterns = [
    path("payments/mpesa/initiate/", MpesaInitiateView.as_view(), name="mpesa-initiate"),
    path("payments/mpesa/callback/", MpesaCallbackView.as_view(), name="mpesa-callback"),
]
