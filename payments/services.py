"""
M-Pesa Daraja STK Push client.

All secrets come from environment variables only (see auto_project/settings.py) -
never hardcode MPESA_CONSUMER_KEY/SECRET/PASSKEY. Sandbox and production use
different base URLs, toggled by MPESA_ENV.
"""
import base64
import datetime
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
        print("DEBUG PAYLOAD:", payload)
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
