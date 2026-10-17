import logging
from django.conf import settings
from django.core.mail import send_mail
from .models import Notification

logger = logging.getLogger(__name__)


def notify(user, notification_type, title, message, send_email=True, link=""):
    notification = Notification.objects.create(
        user=user, notification_type=notification_type, title=title, message=message, link=link,
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


def notify_staff(notification_type, title, message, link="", exclude_user=None):
    """
    In-app notification for every active staff/admin user (one bulk insert).

    The admin's toast system polls notifications, so this is what pops a toast
    up for the team. No email is sent: it's a heads-up, not a message to a customer.
    `exclude_user` skips the person who triggered it (a staff member who opens a
    ticket themselves doesn't need telling).
    """
    from accounts.models import User

    recipients = User.objects.filter(role__in=[User.Role.STAFF, User.Role.ADMIN], is_active=True)
    if exclude_user is not None:
        recipients = recipients.exclude(pk=exclude_user.pk)
    return Notification.objects.bulk_create([
        Notification(user=u, notification_type=notification_type, title=title, message=message, link=link)
        for u in recipients
    ])
