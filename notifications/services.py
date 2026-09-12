import logging
from django.conf import settings
from django.core.mail import send_mail
from .models import Notification

logger = logging.getLogger(__name__)


def notify(user, notification_type, title, message, send_email=True):
    notification = Notification.objects.create(
        user=user, notification_type=notification_type, title=title, message=message,
    )
    if send_email and user.email:
        try:
            send_mail(
                subject=title,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False,
            )
        except Exception:
            logger.exception("Failed to send notification email to %s", user.email)
    return notification
