"""Tasks for the core app."""

from __future__ import annotations

from celery import shared_task
from django.core.mail import mail_admins

# The worker built for sending mail: the only one with a route to Mailgun
# (issue #439). The none:ro:* and dock:* workers have no network.
MAIL_QUEUE = "mail:ro:email"


@shared_task(
    queue=MAIL_QUEUE,
    autoretry_for=(OSError,),
    max_retries=3,
    retry_backoff=60,
)
def send_admin_email(subject: str, message: str, html_message: str | None) -> None:
    """Send an ADMINS email that a process handed off (issue #439).

    RateLimitedAdminEmailHandler has already rate-limited and scrubbed it.
    A failed send raises, so Celery retries it and its worker log shows it:
    it is never silent. OSError covers SMTP errors and anymail's HTTP errors
    (requests' RequestException is an OSError).
    """
    mail_admins(subject, message, fail_silently=False, html_message=html_message)
