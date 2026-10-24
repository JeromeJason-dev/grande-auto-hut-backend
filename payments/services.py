"""
M-Pesa Daraja STK Push client.

All secrets come from environment variables only (see auto_project/settings.py) -
never hardcode MPESA_CONSUMER_KEY/SECRET/PASSKEY. Sandbox and production use
different base URLs, toggled by MPESA_ENV.
"""
import base64
import datetime
import hashlib
import hmac
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import quote

import requests
from django.conf import settings


class MpesaError(Exception):
    pass


class MpesaClient:
    def __init__(self):
        self.base_url = (
            "https://sandbox.safaricom.co.ke" if settings.MPESA_ENV == "sandbox"
            else "https://api.safaricom.co.ke"
        )

    def _get_access_token(self) -> str:
        url = f"{self.base_url}/oauth/v1/generate?grant_type=client_credentials"
        resp = requests.get(
            url,
            auth=(settings.MPESA_CONSUMER_KEY, settings.MPESA_CONSUMER_SECRET),
            timeout=15,
        )
        if resp.status_code != 200:
            raise MpesaError(f"Failed to obtain M-Pesa access token: {resp.status_code} {resp.text}")
        try:
            data = resp.json()
        except requests.exceptions.JSONDecodeError as exc:
            raise MpesaError(
                f"M-Pesa token endpoint returned a non-JSON response ({resp.status_code})"
            ) from exc
        access_token = data.get("access_token")
        if not access_token:
            raise MpesaError("M-Pesa token response did not include access_token")
        return access_token

    def _password_and_timestamp(self):
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        raw = f"{settings.MPESA_SHORTCODE}{settings.MPESA_PASSKEY}{timestamp}"
        password = base64.b64encode(raw.encode()).decode()
        return password, timestamp

    def stk_push(self, phone_number: str, amount, account_reference: str, transaction_desc: str) -> dict:
        """
        Initiates an STK Push prompt on the customer's phone. `phone_number`
        must be in 2547XXXXXXXX format. Returns Safaricom's raw JSON response,
        which includes CheckoutRequestID - the id we key our Payment row on
        and later match the async callback against.
        """
        token = self._get_access_token()
        password, timestamp = self._password_and_timestamp()

        payload = {
            "BusinessShortCode": settings.MPESA_SHORTCODE,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": int(amount),
            "PartyA": phone_number,
            "PartyB": settings.MPESA_SHORTCODE,
            "PhoneNumber": phone_number,
            "CallBackURL": f"{settings.MPESA_CALLBACK_BASE_URL.rstrip('/')}/api/payments/mpesa/callback/",
            "AccountReference": account_reference,
            "TransactionDesc": transaction_desc,
        }
        resp = requests.post(
            f"{self.base_url}/mpesa/stkpush/v1/processrequest",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        if resp.status_code != 200:
            raise MpesaError(f"STK push failed: {resp.status_code} {resp.text}")
        return resp.json()

    def stk_query(self, checkout_request_id: str):
        """
        Asks Safaricom for the outcome of an STK push (the "STK Push Query" API).

        Returns {"result_code": int, "result_desc": str} once the transaction has
        reached a final state (0 = paid; 1032 = cancelled by the customer;
        1 = insufficient funds; 2001 = wrong PIN; 1037 = prompt timed out ...),
        or None while the customer is still looking at the prompt.
        """
        token = self._get_access_token()
        password, timestamp = self._password_and_timestamp()
        resp = requests.post(
            f"{self.base_url}/mpesa/stkpushquery/v1/query",
            json={
                "BusinessShortCode": settings.MPESA_SHORTCODE,
                "Password": password,
                "Timestamp": timestamp,
                "CheckoutRequestID": checkout_request_id,
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        try:
            body = resp.json()
        except ValueError as exc:
            raise MpesaError(f"STK query returned a non-JSON response ({resp.status_code})") from exc

        # While the prompt is still open Daraja answers with an *error* payload
        # ("The transaction is being processed") instead of a result.
        if "ResultCode" not in body:
            if body.get("errorCode") == "500.001.1001":
                return None
            raise MpesaError(f"STK query failed: {resp.status_code} {resp.text}")
        try:
            result_code = int(body["ResultCode"])
        except (TypeError, ValueError) as exc:
            raise MpesaError(f"STK query returned an unreadable ResultCode: {body['ResultCode']!r}") from exc
        return {"result_code": result_code, "result_desc": body.get("ResultDesc", "")}


def extract_callback_metadata(stk_callback: dict) -> dict:
    """Flattens Safaricom's {Item: [{Name, Value}, ...]} shape into a plain dict."""
    items = (stk_callback.get("CallbackMetadata") or {}).get("Item", [])
    return {item["Name"]: item.get("Value") for item in items}


# Card payments - Paystack hosted checkout
class CardPaymentError(Exception):
    pass


class PaystackClient:
    def __init__(self):
        if not settings.PAYSTACK_SECRET_KEY:
            raise CardPaymentError("Card payments are not configured (PAYSTACK_SECRET_KEY is missing).")
        self.base_url = settings.PAYSTACK_BASE_URL.rstrip("/")
        self.headers = {"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"}

    @staticmethod
    def to_minor_units(amount) -> int:
        """KES 1,250.50 -> 125050 (Paystack amounts are in the smallest currency unit)."""
        return int((Decimal(amount) * 100).to_integral_value(rounding=ROUND_HALF_UP))

    def _request(self, method, path, **kwargs):
        try:
            resp = requests.request(method, f"{self.base_url}{path}", headers=self.headers, timeout=30, **kwargs)
            body = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise CardPaymentError(f"Could not reach the card payment provider: {exc}") from exc
        if resp.status_code != 200 or not body.get("status"):
            raise CardPaymentError(body.get("message") or f"Card provider error ({resp.status_code}).")
        return body["data"]

    def initialize(self, *, email, amount, reference, callback_url, metadata=None) -> dict:
        """Returns {authorization_url, access_code, reference}."""
        return self._request("POST", "/transaction/initialize", json={
            "email": email,
            "amount": self.to_minor_units(amount),
            "currency": settings.PAYSTACK_CURRENCY,
            "reference": reference,
            "callback_url": callback_url,
            "metadata": metadata or {},
        })

    def verify(self, reference) -> dict:
        return self._request("GET", f"/transaction/verify/{quote(reference, safe='')}")


def valid_paystack_signature(raw_body: bytes, signature: str) -> bool:
    """Paystack signs every webhook: HMAC-SHA512 of the raw body with the secret key."""
    if not settings.PAYSTACK_SECRET_KEY or not signature:
        return False
    expected = hmac.new(settings.PAYSTACK_SECRET_KEY.encode(), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)


def finalize_card_payment(payment_id, tx: dict):
    import logging
    from django.db import transaction
    from inventory.services import InsufficientStockError
    from orders.models import Order
    from orders.services import CheckoutError, InvalidTransitionError, confirm_order
    from .models import Payment

    logger = logging.getLogger(__name__)
    should_confirm = False

    with transaction.atomic():
        payment = Payment.objects.select_for_update(of=("self",)).select_related("order").get(pk=payment_id)
        if payment.status == Payment.Status.SUCCESS:
            return payment

        tx_status = tx.get("status")
        payment.raw_callback = tx

        if tx_status == "success":
            expected_amount = PaystackClient.to_minor_units(payment.amount)
            if tx.get("amount") != expected_amount or (tx.get("currency") or settings.PAYSTACK_CURRENCY) != settings.PAYSTACK_CURRENCY:
                payment.status = Payment.Status.FAILED
                payment.save(update_fields=["status", "raw_callback", "updated_at"])
                logger.error(
                    "Card amount mismatch for order %s: expected %s %s got %s %s - needs manual review.",
                    payment.order.order_number, expected_amount, settings.PAYSTACK_CURRENCY,
                    tx.get("amount"), tx.get("currency"),
                )
                return payment

            auth = tx.get("authorization") or {}
            payment.status = Payment.Status.SUCCESS
            payment.card_brand = (auth.get("brand") or auth.get("card_type") or "").strip()[:30]
            payment.card_last4 = (auth.get("last4") or "")[:4]
            payment.save(update_fields=["status", "card_brand", "card_last4", "raw_callback", "updated_at"])

            order = payment.order
            if order.payments.filter(status=Payment.Status.SUCCESS).exclude(pk=payment.pk).exists():
                logger.error("Order %s was paid twice (reference %s) - refund the duplicate.", order.order_number, payment.card_reference)
            if order.status == Order.Status.CANCELLED:
                logger.error("Order %s was cancelled but a card payment succeeded (reference %s) - refund needed.", order.order_number, payment.card_reference)
            should_confirm = order.status == Order.Status.PENDING

        elif tx_status in ("failed", "abandoned", "reversed") and payment.status == Payment.Status.PENDING:
            payment.status = Payment.Status.FAILED
            payment.save(update_fields=["status", "raw_callback", "updated_at"])
        else:
            # "ongoing" / "pending" / "queued": still in flight, leave it pending.
            payment.save(update_fields=["raw_callback", "updated_at"])

    if should_confirm:
        try:
            confirm_order(payment.order, note=f"Paid by card ({payment.card_brand or 'card'} ending {payment.card_last4 or '----'}), ref {payment.card_reference}.")
        except (CheckoutError, InsufficientStockError, InvalidTransitionError) as exc:
            # Paid but stock ran out in the meantime - needs a human.
            logger.error("Order %s paid by card but could not auto-confirm: %s", payment.order.order_number, exc)
    return payment


def finalize_mpesa_payment(payment_id, result_code, result_desc="", metadata=None, raw=None):
    """
    Applies a final M-Pesa outcome to a Payment. Used by BOTH the Safaricom
    callback and the status-check endpoint, so the two can never disagree.
    Idempotent: safe to call repeatedly, and in any order.

    result_code 0 = paid; anything else = failed/cancelled.

    A callback saying "paid" is authoritative even if we had already marked
    the attempt failed (e.g. a superseded or timed-out prompt the customer
    paid anyway) - the money has moved, so the record must say so.
    The status query carries no amount/receipt, so those checks only run when
    `metadata` (callback-only) is supplied.
    """
    import logging
    from django.db import transaction
    from inventory.services import InsufficientStockError
    from orders.models import Order
    from orders.services import CheckoutError, InvalidTransitionError, confirm_order
    from .models import Payment

    logger = logging.getLogger(__name__)
    metadata = metadata or {}
    should_confirm = False

    with transaction.atomic():
        payment = Payment.objects.select_for_update(of=("self",)).select_related("order").get(pk=payment_id)
        order = payment.order
        # Don't let a stale "failed" notice overwrite the record of a payment that succeeded.
        if raw is not None and not (payment.status == Payment.Status.SUCCESS and result_code != 0):
            payment.raw_callback = raw

        if payment.status == Payment.Status.SUCCESS:
            # Already paid. A late callback may still carry the receipt number.
            if metadata.get("MpesaReceiptNumber") and not payment.mpesa_receipt_number:
                payment.mpesa_receipt_number = metadata["MpesaReceiptNumber"]
            payment.save(update_fields=["mpesa_receipt_number", "raw_callback", "updated_at"])
            return payment

        if result_code == 0:
            paid_amount = metadata.get("Amount")
            # We send int(amount) to Daraja (whole shillings only), so compare against that.
            if paid_amount is not None and int(float(paid_amount)) != int(payment.amount):
                payment.status = Payment.Status.FAILED
                payment.save(update_fields=["status", "raw_callback", "updated_at"])
                logger.error(
                    "M-Pesa amount mismatch for order %s: expected %s got %s - needs manual review.",
                    order.order_number, int(payment.amount), paid_amount,
                )
                return payment

            payment.status = Payment.Status.SUCCESS
            payment.mpesa_receipt_number = metadata.get("MpesaReceiptNumber", "") or payment.mpesa_receipt_number
            payment.save(update_fields=["status", "mpesa_receipt_number", "raw_callback", "updated_at"])

            if order.payments.filter(status=Payment.Status.SUCCESS).exclude(pk=payment.pk).exists():
                logger.error("Order %s was paid twice (%s) - refund the duplicate.",
                             order.order_number, payment.mpesa_checkout_request_id)
            if order.status == Order.Status.CANCELLED:
                logger.error("Order %s was cancelled but an M-Pesa payment succeeded (%s) - refund needed.",
                             order.order_number, payment.mpesa_checkout_request_id)
            should_confirm = order.status == Order.Status.PENDING

        elif payment.status == Payment.Status.PENDING:
            payment.status = Payment.Status.FAILED
            payment.save(update_fields=["status", "raw_callback", "updated_at"])
            logger.info("M-Pesa payment failed/cancelled for order %s: %s (code %s)",
                        order.order_number, result_desc, result_code)
        else:
            payment.save(update_fields=["raw_callback", "updated_at"])

    if should_confirm:
        receipt = payment.mpesa_receipt_number
        try:
            confirm_order(order, note=f"Paid via M-Pesa{f', receipt {receipt}' if receipt else ''}.")
        except (CheckoutError, InsufficientStockError, InvalidTransitionError) as exc:
            # Paid, but stock ran out (or the order moved on) in the meantime - needs a human.
            logger.error("Order %s paid but could not auto-confirm: %s", order.order_number, exc)
    return payment


def reconcile_pending_mpesa_payments(order):
    """
    Asks Safaricom about every still-pending M-Pesa attempt on an order and
    applies any final outcome. Returns the order's most recent M-Pesa payment
    (refreshed), or None if it has none. Network/Daraja errors leave the
    attempt pending so the caller can simply poll again.
    """
    import logging
    from .models import Payment

    logger = logging.getLogger(__name__)
    pending = order.payments.filter(
        method="mpesa", status=Payment.Status.PENDING,
    ).exclude(mpesa_checkout_request_id__isnull=True).exclude(mpesa_checkout_request_id="")

    for payment in pending:
        try:
            outcome = MpesaClient().stk_query(payment.mpesa_checkout_request_id)
        except (MpesaError, requests.RequestException) as exc:
            logger.warning("STK query failed for order %s: %s", order.order_number, exc)
            continue
        if outcome is not None:
            finalize_mpesa_payment(
                payment.pk, outcome["result_code"], outcome["result_desc"], raw={"stk_query": outcome},
            )
    return order.payments.filter(method="mpesa").order_by("-created_at").first()



class PaymentActionError(Exception):
    """A staff/admin payment action isn't allowed in the order's current state."""


def _audit(order, action, *, user, payment=None, from_status="", to_status="", amount=None, reference="", reason=""):
    from .models import PaymentAuditLog

    return PaymentAuditLog.objects.create(
        order=order, payment=payment, action=action,
        from_status=from_status, to_status=to_status, amount=amount,
        reference=(reference or "")[:100], reason=(reason or "")[:255], performed_by=user,
    )


def recheck_order_payments(order, user):
    import logging
    from .models import Payment

    logger = logging.getLogger(__name__)

    if order.payment_method == "cod":
        raise PaymentActionError("Pay on Delivery orders have no gateway to re-check.")
    if not order.payments.exists():
        raise PaymentActionError("No payment was ever started for this order, so there is nothing to re-check.")

    before = {p.pk: p.status for p in order.payments.all()}
    problem = ""

    if order.payment_method == "mpesa":
        reconcile_pending_mpesa_payments(order)
    else:
        candidates = order.payments.filter(method="card", status__in=[Payment.Status.PENDING, Payment.Status.FAILED]) \
            .exclude(card_reference__isnull=True).exclude(card_reference="")
        for payment in candidates:
            try:
                tx = PaystackClient().verify(payment.card_reference)
            except CardPaymentError as exc:
                logger.warning("Card re-check failed for order %s: %s", order.order_number, exc)
                problem = str(exc)
                continue
            if tx.get("reference") == payment.card_reference:
                finalize_card_payment(payment.pk, tx)

    changed = []
    for payment in order.payments.all():
        old = before.get(payment.pk)
        if old != payment.status:
            changed.append(payment)
            _audit(order, "recheck", user=user, payment=payment, from_status=old or "", to_status=payment.status,
                   amount=payment.amount, reason="Re-checked with the payment gateway.")

    if changed:
        return "Payment updated: " + ", ".join(f"{p.get_method_display()} is now {p.get_status_display().lower()}" for p in changed) + "."
    if problem:
        return f"Couldn't reach the payment gateway ({problem}). Nothing was changed; try again shortly."
    if order.payments.filter(status=Payment.Status.PENDING).exists():
        return "The gateway reports the payment is still waiting for the customer. Nothing changed."
    return "The gateway confirms the current payment status. Nothing changed."


def mark_order_paid_manually(order, user, reason, reference=""):
    from django.db import transaction
    from inventory.services import InsufficientStockError
    from orders.models import Order
    from orders.services import CheckoutError, InvalidTransitionError, confirm_order
    from .models import Payment

    # The gateway's word beats a manual entry: settle any open attempt first.
    if order.payment_method == "mpesa":
        reconcile_pending_mpesa_payments(order)

    with transaction.atomic():
        locked = Order.objects.select_for_update(of=("self",)).get(pk=order.pk)
        if locked.status == Order.Status.CANCELLED:
            raise PaymentActionError("This order is cancelled, so it can't be marked as paid.")
        if locked.payments.filter(status=Payment.Status.SUCCESS).exists():
            raise PaymentActionError("This order is already paid.")

        previous = locked.payment_status
        payment = Payment.objects.create(
            order=locked, method=locked.payment_method, status=Payment.Status.SUCCESS,
            amount=locked.total, recorded_manually=True,
            mpesa_receipt_number=(reference or "")[:50] if locked.payment_method == "mpesa" else "",
        )
        # Anything still "pending" is now superseded. (A late gateway success is still logged as a duplicate.)
        locked.payments.filter(status=Payment.Status.PENDING).update(status=Payment.Status.FAILED)

        if locked.status == Order.Status.PENDING:
            try:
                confirm_order(locked, user=user, note=f"Payment recorded manually by staff. {reason}"[:255])
            except (CheckoutError, InsufficientStockError, InvalidTransitionError) as exc:
                raise PaymentActionError(f"Couldn't mark as paid: {exc}") from exc

        _audit(locked, "mark_paid", user=user, payment=payment, from_status=previous, to_status="paid",
               amount=payment.amount, reference=reference, reason=reason)

    from notifications.services import notify
    notify(
        order.user, "order_update", f"Payment received for {order.order_number}",
        f"We have recorded your payment for order {order.order_number}. Thank you!",
    )
    return Order.objects.select_related("user").get(pk=order.pk)


def refund_order_payment(order, user, reason, reference="", payment_id=None):
    from django.db import transaction
    from .models import Payment

    with transaction.atomic():
        payments = order.payments.select_for_update().filter(status=Payment.Status.SUCCESS).order_by("-created_at")
        if payment_id:
            payments = payments.filter(pk=payment_id)
        payment = payments.first()
        if payment is None:
            raise PaymentActionError("There is no successful payment on this order to refund.")

        previous = order.payment_status
        payment.status = Payment.Status.REFUNDED
        payment.save(update_fields=["status", "updated_at"])
        order = type(order).objects.select_related("user").get(pk=order.pk)
        _audit(order, "refund", user=user, payment=payment, from_status=previous, to_status=order.payment_status,
               amount=payment.amount, reference=reference, reason=reason)

    from notifications.services import notify
    notify(
        order.user, "order_update", f"Refund recorded for {order.order_number}",
        f"A refund of KES {payment.amount:,.2f} has been recorded for order {order.order_number}.",
    )
    return order