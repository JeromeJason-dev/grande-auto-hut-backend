import json
import logging
import uuid

import requests
from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status, views
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError, PermissionDenied

from orders.models import Order
from .models import Payment
from .serializers import (
    CardInitiateSerializer, CardVerifySerializer, MpesaInitiateSerializer, MpesaStatusSerializer, PaymentSerializer,
)
from .services import (
    CardPaymentError, MpesaClient, MpesaError, PaystackClient,
    extract_callback_metadata, finalize_card_payment, finalize_mpesa_payment,
    reconcile_pending_mpesa_payments, valid_paystack_signature,
)

logger = logging.getLogger(__name__)


class MpesaInitiateView(views.APIView):
    """
    POST /api/payments/mpesa/initiate/
    Body: {"order_id": "...", "phone_number": "0712345678"}
    Triggers an STK push prompt on the customer's phone for a pending,
    M-Pesa-method order they own. Does NOT mark anything paid - only the
    callback (below) does that, after Safaricom confirms the transaction.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = MpesaInitiateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = get_object_or_404(Order, id=serializer.validated_data["order_id"])

        if order.user_id != request.user.id and not request.user.is_staff_role:
            raise PermissionDenied("This is not your order.")
        if order.payment_method != Order.PaymentMethod.MPESA:
            raise ValidationError("This order is not set up for M-Pesa payment.")
        if order.status != Order.Status.PENDING:
            raise ValidationError(f"Order is '{order.status}' - only pending orders can be paid.")
        # A previous prompt may have been paid/cancelled without us hearing about it yet.
        reconcile_pending_mpesa_payments(order)
        order.refresh_from_db()
        if order.status != Order.Status.PENDING or order.payments.filter(status=Payment.Status.SUCCESS).exists():
            raise ValidationError("This order has already been paid.")

        phone_number = serializer.validated_data["phone_number"]

        try:
            response = MpesaClient().stk_push(
                phone_number=phone_number,
                amount=order.total,
                account_reference=order.order_number,
                transaction_desc=f"Grande Auto Hut order {order.order_number}",
            )
        except (MpesaError, requests.RequestException, ValueError) as exc:
            logger.exception("M-Pesa STK push failed for order %s", order.order_number)
            raise ValidationError(f"Could not initiate M-Pesa payment: {exc}")

        payment = Payment.objects.create(
            order=order,
            method="mpesa",
            status=Payment.Status.PENDING,
            amount=order.total,
            phone_number=phone_number,
            mpesa_merchant_request_id=response.get("MerchantRequestID", ""),
            mpesa_checkout_request_id=response.get("CheckoutRequestID", ""),
        )
        return Response(
            {
                "detail": "STK push sent. Ask the customer to check their phone and enter their M-Pesa PIN.",
                "payment": PaymentSerializer(payment).data,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class MpesaCallbackView(views.APIView):
    """
    POST /api/payments/mpesa/callback/ - called by Safaricom's servers, not
    the frontend. No user auth (Safaricom can't hold a JWT), so instead we
    verify by matching CheckoutRequestID against a Payment WE created, and
    cross-check the paid amount against what we expected before crediting
    anything. In production, also restrict this URL at the network/WAF layer
    to Safaricom's published IP ranges.
    """
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        body = request.data.get("Body", {})
        stk_callback = body.get("stkCallback", {})
        checkout_request_id = stk_callback.get("CheckoutRequestID")
        result_code = stk_callback.get("ResultCode")
        result_desc = stk_callback.get("ResultDesc", "")

        payment = Payment.objects.filter(mpesa_checkout_request_id=checkout_request_id).select_related("order").first()
        if not payment:
            logger.warning("M-Pesa callback for unknown CheckoutRequestID: %s", checkout_request_id)
            # Still ack 200 so Safaricom doesn't retry indefinitely on a request we'll never match.
            return Response({"ResultCode": 0, "ResultDesc": "Accepted"})

        # Shared with the status endpoint below, so both apply outcomes identically.
        finalize_mpesa_payment(
            payment.pk,
            result_code=int(result_code) if result_code is not None else -1,
            result_desc=result_desc,
            metadata=extract_callback_metadata(stk_callback) if result_code == 0 else {},
            raw=request.data,
        )
        return Response({"ResultCode": 0, "ResultDesc": "Accepted"})


class MpesaStatusView(views.APIView):
    """
    POST /api/payments/mpesa/status/   Body: {"order_id": "..."}
    Called (polled) by the frontend after an STK push. Asks Safaricom directly
    what happened to the prompt and applies it, so the page shows paid / failed /
    cancelled even when the callback is delayed or can't reach us (local dev).
    Safe to call repeatedly. Returns the latest M-Pesa payment, or
    {"status": "none"} if no STK push was ever sent for this order.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = MpesaStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = _get_owned_order(request, serializer.validated_data["order_id"])

        payment = reconcile_pending_mpesa_payments(order)
        if payment is None:
            return Response({"status": "none"})
        # Any successful attempt wins over a later failed one.
        success = order.payments.filter(method="mpesa", status=Payment.Status.SUCCESS).first()
        return Response(PaymentSerializer(success or payment).data)


# ---------------------------------------------------------------------------
# Card payments (Paystack hosted checkout)
# ---------------------------------------------------------------------------
def _get_owned_order(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    if order.user_id != request.user.id and not request.user.is_staff_role:
        raise PermissionDenied("This is not your order.")
    return order


class CardInitiateView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = CardInitiateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = _get_owned_order(request, serializer.validated_data["order_id"])

        if order.payment_method != Order.PaymentMethod.CARD:
            raise ValidationError("This order is not set up for card payment.")
        if order.status != Order.Status.PENDING:
            raise ValidationError(f"Order is '{order.status}' - only pending orders can be paid.")
        if order.payments.filter(status=Payment.Status.SUCCESS).exists():
            raise ValidationError("This order has already been paid.")

        reference = f"{order.order_number}-{uuid.uuid4().hex[:10]}"
        try:
            client = PaystackClient()
            data = client.initialize(
                email=order.user.email,
                amount=order.total,
                reference=reference,
                callback_url=f"{settings.FRONTEND_URL}/orders/{order.id}",
                metadata={"order_id": str(order.id), "order_number": order.order_number},
            )
        except CardPaymentError as exc:
            logger.exception("Card initiate failed for order %s", order.order_number)
            raise ValidationError(f"Could not start card payment: {exc}")

        payment = Payment.objects.create(
            order=order,
            method="card",
            status=Payment.Status.PENDING,
            amount=order.total,
            card_reference=data.get("reference", reference),
        )
        return Response(
            {
                "payment_url": data["authorization_url"],
                "access_code": data.get("access_code", ""),
                "reference": payment.card_reference,
                "payment": PaymentSerializer(payment).data,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class CardVerifyView(views.APIView):
    """
    POST /api/payments/card/verify/   Body: {"order_id": "...", "reference": "..."(optional)}
    Called by the frontend when the customer returns from Paystack. Asks
    Paystack directly for the transaction result and applies it, so the page
    shows the right state even if the webhook is delayed (or can't reach us,
    e.g. local development). Safe to call repeatedly.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = CardVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = _get_owned_order(request, serializer.validated_data["order_id"])
        reference = serializer.validated_data.get("reference") or ""

        card_payments = order.payments.filter(method="card")
        payment = (
            card_payments.filter(card_reference=reference).first() if reference
            else card_payments.filter(status=Payment.Status.PENDING).first()
        )
        if not payment:
            raise ValidationError("No card payment found for this order.")
        if payment.status == Payment.Status.SUCCESS:
            return Response(PaymentSerializer(payment).data)

        try:
            tx = PaystackClient().verify(payment.card_reference)
        except CardPaymentError as exc:
            raise ValidationError(f"Could not verify card payment: {exc}")
        if tx.get("reference") != payment.card_reference:
            raise ValidationError("Card payment reference mismatch.")

        payment = finalize_card_payment(payment.pk, tx)
        return Response(PaymentSerializer(payment).data)


class CardWebhookView(views.APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        raw_body = request.body  # must be read before request.data touches the stream
        if not valid_paystack_signature(raw_body, request.headers.get("x-paystack-signature", "")):
            logger.warning("Card webhook rejected: bad signature.")
            return Response({"detail": "Invalid signature."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            event = json.loads(raw_body)
        except ValueError:
            return Response({"detail": "Invalid payload."}, status=status.HTTP_400_BAD_REQUEST)

        if event.get("event") not in ("charge.success", "charge.failed"):
            return Response({"ok": True})  # events we don't act on

        reference = (event.get("data") or {}).get("reference")
        payment = Payment.objects.filter(card_reference=reference).first()
        if not payment:
            logger.warning("Card webhook for unknown reference: %s", reference)
            return Response({"ok": True})  # ack so Paystack doesn't retry a reference we'll never match

        try:
            tx = PaystackClient().verify(reference)
        except CardPaymentError:
            logger.exception("Could not verify card webhook %s", reference)
            return Response({"detail": "Verification failed, retry."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        finalize_card_payment(payment.pk, tx)
        return Response({"ok": True})