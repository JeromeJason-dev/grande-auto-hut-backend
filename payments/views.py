import logging
import requests
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status, views
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError, PermissionDenied

from orders.models import Order
from orders.services import confirm_order
from inventory.services import InsufficientStockError
from orders.services import CheckoutError
from .models import Payment
from .serializers import MpesaInitiateSerializer, PaymentSerializer
from .services import MpesaClient, MpesaError, extract_callback_metadata

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
        if order.payments.filter(status=Payment.Status.SUCCESS).exists():
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

        payment.raw_callback = request.data

        if payment.status != Payment.Status.PENDING:
            # Duplicate/retried callback - already processed, just ack.
            payment.save(update_fields=["raw_callback"])
            return Response({"ResultCode": 0, "ResultDesc": "Accepted"})

        if result_code == 0:
            metadata = extract_callback_metadata(stk_callback)
            paid_amount = metadata.get("Amount")
            if paid_amount is not None and float(paid_amount) != float(payment.amount):
                # Amount mismatch - do NOT mark paid. Flag for manual review.
                payment.status = Payment.Status.FAILED
                payment.save(update_fields=["status", "raw_callback"])
                logger.error(
                    "M-Pesa amount mismatch for order %s: expected %s got %s",
                    payment.order.order_number, payment.amount, paid_amount,
                )
                return Response({"ResultCode": 0, "ResultDesc": "Accepted"})

            payment.status = Payment.Status.SUCCESS
            payment.mpesa_receipt_number = metadata.get("MpesaReceiptNumber", "")
            payment.save(update_fields=["status", "mpesa_receipt_number", "raw_callback"])

            try:
                confirm_order(payment.order, note=f"Paid via M-Pesa, receipt {payment.mpesa_receipt_number}.")
            except (CheckoutError, InsufficientStockError) as exc:
                # Payment succeeded but stock ran out in the meantime - needs a human.
                logger.error("Order %s paid but could not auto-confirm: %s", payment.order.order_number, exc)
        else:
            payment.status = Payment.Status.FAILED
            payment.save(update_fields=["status", "raw_callback"])
            logger.info("M-Pesa payment failed/cancelled for order %s: %s", payment.order.order_number, result_desc)

        return Response({"ResultCode": 0, "ResultDesc": "Accepted"})
    