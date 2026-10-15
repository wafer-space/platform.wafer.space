"""Logging utilities for admin error reporting."""

from __future__ import annotations

import hashlib
import logging
import threading
from typing import TYPE_CHECKING
from typing import Any

from django.core.cache import cache
from django.utils.log import AdminEmailHandler
from kombu.exceptions import KombuError
from sqlalchemy.exc import SQLAlchemyError

from wafer_space.core.debug import scrub_url_credentials
from wafer_space.core.tasks import MAIL_QUEUE
from wafer_space.core.tasks import send_admin_email

if TYPE_CHECKING:
    from django.utils.functional import Promise

# At most one email per error signature per window. A signature is
# (logger name, level, unformatted message template), so a repeating error
# that interpolates changing values (digests, task ids, ...) still counts
# as a single signature.
RATE_LIMIT_SECONDS = 60 * 60

# How long logging an ERROR may wait for its email to reach the broker
# (issue #439). A publish takes milliseconds; a broker that is down or
# wedged must not hold up the task that logged the error, nor the broker
# watchdog's CRITICAL just before it exits the process.
HAND_OFF_TIMEOUT_SECONDS = 5
# Hand-offs still waiting on a hung broker, per process, before further
# emails are dropped (each dropped one is logged to the console)
MAX_PENDING_HAND_OFFS = 4

# Not under "wafer_space": its records reach only root's console handler
# (the Celery worker log), never this handler, so a failed hand-off can't
# loop back into another hand-off.
hand_off_logger = logging.getLogger("admin_email_hand_off")

# The hand-off threads of this process. A forked child inherits the list,
# but not the threads, which then report not alive.
_pending: list[threading.Thread] = []

# What a publish to the broker can raise: kombu's connection and channel
# errors, SQLAlchemy's (the broker is PostgreSQL through kombu's sqla
# transport) and socket errors
HAND_OFF_ERRORS = (KombuError, SQLAlchemyError, OSError)


def publish_admin_email(subject: str, message: str, html_message: str | None) -> None:
    """Publish the email to the mail worker's queue, or log why not."""
    try:
        send_admin_email.apply_async(
            args=(subject, message, html_message),
            queue=MAIL_QUEUE,
            retry=False,
        )
    except HAND_OFF_ERRORS:
        hand_off_logger.exception(
            "ADMINS email not handed to %s, so it is lost. Subject: %s\n%s",
            MAIL_QUEUE,
            subject,
            message,
        )


def hand_off_admin_email(subject: str, message: str, html_message: str | None) -> None:
    """Hand an ADMINS email to the mail worker without blocking (issue #439).

    The publish runs in its own thread, so a broker that is down or wedged
    holds up the caller for at most HAND_OFF_TIMEOUT_SECONDS. The thread
    takes its own broker connection from kombu's pool, never the one a
    wedged consumer is stuck on.
    """
    _pending[:] = [t for t in _pending if t.is_alive()]
    if len(_pending) >= MAX_PENDING_HAND_OFFS:
        hand_off_logger.error(
            "ADMINS email dropped: %d hand-offs to %s are still waiting on the "
            "broker. Subject: %s\n%s",
            len(_pending),
            MAIL_QUEUE,
            subject,
            message,
        )
        return
    thread = threading.Thread(
        target=publish_admin_email,
        args=(subject, message, html_message),
        name="admin-email-hand-off",
        daemon=True,
    )
    _pending.append(thread)
    thread.start()
    thread.join(HAND_OFF_TIMEOUT_SECONDS)
    if thread.is_alive():
        hand_off_logger.error(
            "ADMINS email hand-off to %s still waiting on the broker after %s s; "
            "it may be lost. Subject: %s\n%s",
            MAIL_QUEUE,
            HAND_OFF_TIMEOUT_SECONDS,
            subject,
            message,
        )


class RateLimitedAdminEmailHandler(AdminEmailHandler):
    """AdminEmailHandler that drops repeats of the same error signature.

    Django's AdminEmailHandler mails ADMINS for every record it sees; a
    periodic task failing every few minutes would send hundreds of
    identical emails a day (the failure mode behind issue #293). This
    subclass keys each record by its unformatted message template and
    only forwards the first occurrence per RATE_LIMIT_SECONDS.

    Uses the default Django cache. With a LocMem backend the window is
    per-process, so the effective ceiling is one email per signature per
    window per worker process - still bounded.

    The finished subject, text body and HTML body are passed through
    scrub_url_credentials() before sending: the exception reporter filter
    only cleanses settings, request metadata and frame locals, while the
    exception message, log message and request URL are printed verbatim
    and can carry a ``scheme://user:password@`` URL (issue #339).

    Nothing is sent from this process: the scrubbed email is handed to the
    mail:ro:email worker (issue #439). Six deployed workers have no network
    by design, and an in-process send there waited 30 s, then failed
    silently.
    """

    def emit(self, record: logging.LogRecord) -> None:
        signature = f"{record.name}:{record.levelno}:{record.msg}"
        digest = hashlib.sha256(signature.encode()).hexdigest()
        if cache.add(f"admin-email-rate:{digest}", 1, RATE_LIMIT_SECONDS):
            super().emit(record)

    def send_mail(
        self,
        subject: str | Promise,
        message: str | Promise,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        # AdminEmailHandler passes fail_silently; the hand-off never raises
        del args
        html_message = kwargs.get("html_message")
        hand_off_admin_email(
            scrub_url_credentials(str(subject)),
            scrub_url_credentials(str(message)),
            None if html_message is None else scrub_url_credentials(html_message),
        )
