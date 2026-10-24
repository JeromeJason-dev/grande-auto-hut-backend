from django.urls import path
from .views import (
    CardInitiateView, CardVerifyView, CardWebhookView, MpesaCallbackView, MpesaInitiateView, MpesaStatusView,
    OrderPaymentMarkPaidView, OrderPaymentRecheckView, OrderPaymentRefundView, OrderPaymentsView,
)

urlpatterns = [
    path("payments/mpesa/initiate/", MpesaInitiateView.as_view(), name="mpesa-initiate"),
    path("payments/mpesa/callback/", MpesaCallbackView.as_view(), name="mpesa-callback"),
    path("payments/mpesa/status/", MpesaStatusView.as_view(), name="mpesa-status"),
    path("payments/card/initiate/", CardInitiateView.as_view(), name="card-initiate"),
    path("payments/card/verify/", CardVerifyView.as_view(), name="card-verify"),
    path("payments/card/webhook/", CardWebhookView.as_view(), name="card-webhook"),

    # Staff / admin payment management (no endpoint sets a status directly).
    path("payments/orders/<uuid:order_id>/", OrderPaymentsView.as_view(), name="order-payments"),
    path("payments/orders/<uuid:order_id>/recheck/", OrderPaymentRecheckView.as_view(), name="order-payments-recheck"),
    path("payments/orders/<uuid:order_id>/mark-paid/", OrderPaymentMarkPaidView.as_view(), name="order-payments-mark-paid"),
    path("payments/orders/<uuid:order_id>/refund/", OrderPaymentRefundView.as_view(), name="order-payments-refund"),
]