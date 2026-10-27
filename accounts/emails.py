import logging
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.core.mail import EmailMultiAlternatives
from django.utils.encoding import force_bytes
from django.utils.html import escape
from django.utils.http import urlsafe_base64_encode

logger = logging.getLogger(__name__)

VERIFY_SALT = "accounts.email-verification"


def make_verification_token(user) -> str:
    # Bound to the email address, so changing the email invalidates old links.
    return signing.dumps({"uid": str(user.pk), "email": user.email.lower()}, salt=VERIFY_SALT)


def read_verification_token(token: str):
    """Returns the payload dict, or None if the token is invalid or expired."""
    try:
        return signing.loads(token, salt=VERIFY_SALT, max_age=settings.EMAIL_VERIFICATION_MAX_AGE)
    except signing.BadSignature:  # includes SignatureExpired
        return None


def _send(to_email: str, subject: str, text: str, html: str) -> bool:
    try:
        msg = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [to_email])
        msg.attach_alternative(html, "text/html")
        msg.send(fail_silently=False)
        return True
    except Exception:
        logger.exception("Failed to send '%s' email to %s", subject, to_email)
        return False


def _wrap_html(heading: str, body: str, button_label: str, link: str) -> str:
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;max-width:520px;margin:0 auto;color:#101B2C">'
        f'<h2 style="margin:0 0 16px">{escape(heading)}</h2>'
        f'<p style="line-height:1.5">{escape(body)}</p>'
        f'<p style="margin:24px 0"><a href="{escape(link)}" '
        'style="background:#101B2C;color:#fff;padding:12px 20px;border-radius:6px;text-decoration:none;display:inline-block">'
        f'{escape(button_label)}</a></p>'
        f'<p style="font-size:13px;color:#7C7669;line-height:1.5">If the button does not work, copy this link into your browser:<br>{escape(link)}</p>'
        '<p style="font-size:13px;color:#7C7669">Grande Auto Hut</p></div>'
    )


def send_verification_email(user) -> bool:
    link = f"{settings.FRONTEND_URL}/verify-email?token={quote(make_verification_token(user))}"
    name = user.first_name or "there"
    text = (
        f"Hi {name},\n\nPlease confirm your email address to start ordering from Grande Auto Hut:\n{link}\n\n"
        "The link is valid for 3 days. If you did not create an account, you can ignore this email."
    )
    html = _wrap_html(
        "Confirm your email",
        f"Hi {name}, please confirm your email address to start ordering from Grande Auto Hut. "
        "The link is valid for 3 days. If you did not create an account, ignore this email.",
        "Confirm my email", link,
    )
    return _send(user.email, "Confirm your Grande Auto Hut email", text, html)


def send_password_reset_email(user) -> bool:
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    link = f"{settings.FRONTEND_URL}/reset-password?uid={uid}&token={token}"
    minutes = max(1, settings.PASSWORD_RESET_TIMEOUT // 60)
    text = (
        f"We received a request to reset your Grande Auto Hut password.\n\nSet a new password here:\n{link}\n\n"
        f"The link expires in {minutes} minutes. If you did not ask for this, ignore this email - your password stays the same."
    )
    html = _wrap_html(
        "Reset your password",
        f"We received a request to reset your Grande Auto Hut password. The link expires in {minutes} minutes. "
        "If you did not ask for this, ignore this email; your password stays the same.",
        "Choose a new password", link,
    )
    return _send(user.email, "Reset your Grande Auto Hut password", text, html)