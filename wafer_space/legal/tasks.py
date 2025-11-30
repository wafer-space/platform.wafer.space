"""Celery tasks for Terms of Service notifications."""

import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)


def _validate_site_url() -> str:
    """Validate that SITE_URL is configured.

    Returns:
        str: The configured SITE_URL

    Raises:
        ValueError: If SITE_URL is not configured

    """
    if settings.SITE_URL is None:
        msg = "SITE_URL must be configured in settings"
        raise ValueError(msg)
    return settings.SITE_URL


@shared_task(bind=True, queue="default", max_retries=3, default_retry_delay=300)
def send_tos_update_email(self, notification_id: int) -> dict[str, str]:
    """Send TOS update notification email to a user.

    Args:
        self: Celery task instance
        notification_id: ID of the TermsOfServiceNotification

    Returns:
        dict: Status information about the email send

    """
    from .models import TermsOfServiceNotification  # noqa: PLC0415

    try:
        notification = TermsOfServiceNotification.objects.select_related(
            "user",
            "tos_version",
        ).get(id=notification_id)

        # Skip if already sent
        if notification.status == TermsOfServiceNotification.Status.SENT:
            return {
                "status": "skipped",
                "message": "Notification already sent",
            }

        # Ensure SITE_URL is configured
        site_url = _validate_site_url()

        # Prepare email context
        # SITE_URL is always set in runtime environments (dev/pytest/stage/prod)
        assert settings.SITE_URL is not None
        context = {
            "user": notification.user,
            "tos_version": notification.tos_version,
            "tos_url": site_url + reverse("legal:tos_display"),
            "accept_url": site_url + reverse("legal:tos_accept"),
            "site_name": "wafer.space",
        }

        # Render email content
        html_message = render_to_string(
            "legal/emails/tos_update_email.html",
            context,
        )
        plain_message = strip_tags(html_message)

        # Send email
        subject = (
            f"Updated Terms of Service - wafer.space "
            f"v{notification.tos_version.version}"
        )
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[notification.user.email],
            html_message=html_message,
            fail_silently=False,
        )

        # Mark notification as sent
        notification.mark_as_sent()

        logger.info(
            "TOS update email sent to %s for version %s",
            notification.user.email,
            notification.tos_version.version,
        )
    except TermsOfServiceNotification.DoesNotExist:
        error_msg = f"TermsOfServiceNotification {notification_id} does not exist"
        logger.exception(error_msg)
        return {
            "status": "error",
            "message": error_msg,
        }
    except Exception as exc:
        error_msg = f"Failed to send TOS update email: {exc!s}"
        logger.exception(
            "Error sending TOS update email for notification %s",
            notification_id,
        )

        # Mark notification as failed
        try:
            notification.mark_as_failed(error_msg)
        except Exception:
            logger.exception("Failed to mark notification as failed")

        # Retry the task
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc) from exc

        return {
            "status": "failed",
            "message": error_msg,
        }
    else:
        return {
            "status": "success",
            "message": f"Email sent to {notification.user.email}",
        }


@shared_task(queue="default")
def send_bulk_tos_notifications(
    tos_version_id: int,
    user_ids: list[int] | None = None,
) -> dict[str, int | str]:
    """Send TOS update notifications to multiple users.

    Args:
        tos_version_id: ID of the TermsOfService version
        user_ids: Optional list of user IDs. If None, sends to all users
            who haven't accepted.

    Returns:
        dict: Count of notifications created and queued

    """
    from django.contrib.auth import get_user_model  # noqa: PLC0415

    from .models import TermsOfService  # noqa: PLC0415
    from .models import TermsOfServiceAcceptance  # noqa: PLC0415
    from .models import TermsOfServiceNotification  # noqa: PLC0415

    user_model = get_user_model()

    try:
        tos_version = TermsOfService.objects.get(id=tos_version_id)

        # Get users who have already accepted (to exclude them)
        accepted_user_ids = TermsOfServiceAcceptance.objects.filter(
            tos_version=tos_version,
        ).values_list("user_id", flat=True)

        # Get users who need to be notified
        if user_ids:
            users = user_model.objects.filter(id__in=user_ids).exclude(
                id__in=accepted_user_ids,
            )
        else:
            # Get all active users who haven't accepted this version
            users = user_model.objects.filter(
                is_active=True,
            ).exclude(
                id__in=accepted_user_ids,
            )

        notifications_created = 0
        notifications_queued = 0

        for user in users:
            # Create or get notification
            notification, created = TermsOfServiceNotification.objects.get_or_create(
                user=user,
                tos_version=tos_version,
                defaults={
                    "status": TermsOfServiceNotification.Status.PENDING,
                },
            )

            if created:
                notifications_created += 1

            # Queue email task if not already sent
            if notification.status != TermsOfServiceNotification.Status.SENT:
                send_tos_update_email.delay(notification.id)
                notifications_queued += 1

        logger.info(
            "Bulk TOS notifications: created=%d, queued=%d for version %s",
            notifications_created,
            notifications_queued,
            tos_version.version,
        )

        return {
            "created": notifications_created,
            "queued": notifications_queued,
            "total_users": users.count(),
        }

    except TermsOfService.DoesNotExist:
        error_msg = f"TermsOfService {tos_version_id} does not exist"
        logger.exception(error_msg)
        return {
            "created": 0,
            "queued": 0,
            "total_users": 0,
            "error": error_msg,
        }

    except Exception as exc:
        error_msg = f"Failed to send bulk TOS notifications: {exc!s}"
        logger.exception("Error in send_bulk_tos_notifications")
        return {
            "created": 0,
            "queued": 0,
            "total_users": 0,
            "error": error_msg,
        }
