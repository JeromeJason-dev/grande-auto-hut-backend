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