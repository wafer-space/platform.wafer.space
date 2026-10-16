"""Logging utilities for admin error reporting."""

from __future__ import annotations

import hashlib
import logging
import threading
from datetime import timedelta
from functools import partial
from typing import TYPE_CHECKING
from typing import Any
from typing import cast

from django.apps import apps
from django.conf import settings
from django.core.cache import cache
from django.db import DatabaseError
from django.db import connections
from django.utils import timezone
from django.utils.log import AdminEmailHandler
from kombu.exceptions import KombuError
from sqlalchemy.exc import SQLAlchemyError

from wafer_space.core.debug import scrub_url_credentials
from wafer_space.core.tasks import MAIL_QUEUE
from wafer_space.core.tasks import send_admin_email

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from django.utils.functional import Promise

    from wafer_space.core.models import AdminEmailClaim

# At most one email per error signature per window. A signature is
# (logger name, level, unformatted message template), so a repeating error
# that interpolates changing values (digests, task ids, ...) still counts
# as a single signature.
RATE_LIMIT_SECONDS = 60 * 60
RATE_LIMIT_WINDOW = timedelta(seconds=RATE_LIMIT_SECONDS)

# How long logging an ERROR may wait for the database to say whether
# another process already sent its email (issue #450). A claim takes
# milliseconds; past this, the process decides on its own.
CLAIM_TIMEOUT_SECONDS = 5

# How long logging an ERROR may wait for its email to reach the broker
# (issue #439). A publish takes milliseconds; a broker that is down or
# wedged must not hold up the task that logged the error, nor the broker
# watchdog's CRITICAL just before it exits the process.
HAND_OFF_TIMEOUT_SECONDS = 5
# Hand-offs still waiting on a hung broker, per process, before further
# emails are dropped (each dropped one is logged to the console)
MAX_PENDING_HAND_OFFS = 4

# Not under "wafer_space": its records reach only root's console handler
# (the Celery worker log), never this handler, so a failed hand-off or
# claim can't loop back into another email.
hand_off_logger = logging.getLogger("admin_email_hand_off")

# The hand-off threads of this process. A forked child inherits the list,
# but not the threads, which then report not alive.
pending_hand_offs: list[threading.Thread] = []

# What a publish to the broker can raise: kombu's connection and channel
# errors, SQLAlchemy's (the broker is PostgreSQL through kombu's sqla
# transport) and socket errors
HAND_OFF_ERRORS = (KombuError, SQLAlchemyError, OSError)


def publish_admin_email(
    subject: str,
    message: str,
    html_message: str | None,
    lost: Callable[[], object],
) -> None:
    """Publish the email to the mail worker's queue, or log why not.

    Calls ``lost`` once the email is known to be lost, even when that is
    after the caller stopped waiting.
    """
    published = logged = False
    try:
        send_admin_email.apply_async(
            args=(subject, message, html_message),
            queue=MAIL_QUEUE,
            retry=False,
        )
        published = True
    except HAND_OFF_ERRORS:
        logged = True
        lost()
        hand_off_logger.exception(
            "ADMINS email not handed to %s, so it is lost. Subject: %s\n%s",
            MAIL_QUEUE,
            subject,
            message,
        )
    finally:
        # Any other exception ends the thread with only a bare traceback
        # from threading.excepthook; this says which email it lost
        if not published and not logged:
            lost()
            hand_off_logger.error(
                "ADMINS email not handed to %s, so it is lost (the error "
                "follows). Subject: %s\n%s",
                MAIL_QUEUE,
                subject,
                message,
            )


def hand_off_admin_email(
    subject: str,
    message: str,
    html_message: str | None,
    *,
    lost: Callable[[], object],
) -> None:
    """Hand an ADMINS email to the mail worker without blocking (issue #439).

    The publish runs in its own thread, so a broker that is down or wedged
    holds up the caller for at most HAND_OFF_TIMEOUT_SECONDS. The thread
    takes its own broker connection from kombu's pool, never the one a
    wedged consumer is stuck on.

    ``lost`` is called once the email is known to be lost: dropped here, or
    a failed publish, even one that fails after the caller stopped waiting.
    A publish still pending is not lost: it may yet succeed.
    """
    pending_hand_offs[:] = [t for t in pending_hand_offs if t.is_alive()]
    if len(pending_hand_offs) >= MAX_PENDING_HAND_OFFS:
        hand_off_logger.error(
            "ADMINS email dropped: %d hand-offs to %s are still waiting on the "
            "broker. Subject: %s\n%s",
            len(pending_hand_offs),
            MAIL_QUEUE,
            subject,
            message,
        )
        lost()
        return
    thread = threading.Thread(
        target=publish_admin_email,
        args=(subject, message, html_message, lost),
        name="admin-email-hand-off",
        daemon=True,
    )
    pending_hand_offs.append(thread)
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


class ClaimUnavailableError(Exception):
    """The database couldn't say whether another process sent the email."""


def on_own_connection[T](work: Callable[[], T]) -> T:
    """Run ``work`` in a thread of its own, so on a connection of its own.

    The caller's connection is never touched, nor any transaction on it,
    even one that has failed: the handler runs inside logging, often while
    the caller's transaction is the thing failing. A claim made inside the
    caller's transaction would also keep its row locked, and other
    processes waiting, until that transaction ended.

    Raises ClaimUnavailableError when ``work`` raised, or took longer than
    CLAIM_TIMEOUT_SECONDS.
    """
    outcome: list[T] = []

    def run() -> None:
        try:
            outcome.append(work())
        except DatabaseError:
            hand_off_logger.exception("ADMINS email claim failed in the database")
        finally:
            connections.close_all()

    thread = threading.Thread(target=run, name="admin-email-claim", daemon=True)
    thread.start()
    thread.join(CLAIM_TIMEOUT_SECONDS)
    if not outcome:
        msg = "no answer from the database"
        raise ClaimUnavailableError(msg)
    return outcome[0]


def admin_email_claims() -> type[AdminEmailClaim]:
    """The claims model; models can't be imported while logging is set up."""
    return cast("type[AdminEmailClaim]", apps.get_model("core", "AdminEmailClaim"))


def claim_admin_email(signature: str, now: datetime) -> datetime | None:
    """Take ``signature``'s slot for every process; see AdminEmailClaim.claim."""
    return on_own_connection(
        lambda: admin_email_claims().objects.claim(
            signature, now=now, window=RATE_LIMIT_WINDOW
        )
    )


def give_back_slot(rate_key: str, signature: str, claimed_at: datetime | None) -> None:
    """A lost email gives its slot back, so the next one is sent."""
    cache.delete(rate_key)
    if claimed_at is None:
        return
    try:
        on_own_connection(
            lambda: admin_email_claims().objects.release(signature, sent_at=claimed_at)
        )
    except ClaimUnavailableError:
        hand_off_logger.warning(
            "A lost ADMINS email's slot stays taken in the database until its "
            "window ends; other processes send none for it until then."
        )


class RateLimitedAdminEmailHandler(AdminEmailHandler):
    """AdminEmailHandler that drops repeats of the same error signature.

    Django's AdminEmailHandler mails ADMINS for every record it sees; a
    periodic task failing every few minutes would send hundreds of
    identical emails a day (the failure mode behind issue #293). This
    subclass keys each record by its unformatted message template and
    only forwards the first occurrence per RATE_LIMIT_SECONDS.

    The window is shared by every process (issue #450): the first process
    to log a signature claims it in the database (AdminEmailClaim), on a
    connection of its own, and only that process sends. The per-process
    LocMem cache still notes what this process has sent or heard about,
    so a repeating error asks the database once per window, not once per
    record. If the database can't answer, the process falls back to its
    own window: the email is sent, never lost.

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

    # The record emit() is sending: its signature, rate-limit key and when
    # it claimed the database slot (None when it couldn't). logging holds
    # the handler's lock around emit(), so one emit() runs at a time.
    digest = ""
    rate_key = ""
    claimed_at: datetime | None = None

    def emit(self, record: logging.LogRecord) -> None:
        signature = f"{record.name}:{record.levelno}:{record.msg}"
        self.digest = hashlib.sha256(signature.encode()).hexdigest()
        self.rate_key = f"admin-email-rate:{self.digest}"
        self.claimed_at = None
        if cache.add(self.rate_key, 1, RATE_LIMIT_SECONDS) and self.first_anywhere():
            super().emit(record)

    def first_anywhere(self) -> bool:
        """Whether no other process sent this signature's email this window."""
        if not settings.ADMIN_EMAIL_RATE_LIMIT_SHARED:
            return True
        now = timezone.now()
        try:
            sent_at = claim_admin_email(self.digest, now)
        except ClaimUnavailableError:
            hand_off_logger.warning(
                "ADMINS email sent on this process's own rate limit: the "
                "database didn't say whether another process sent it."
            )
            return True
        if sent_at is None:
            self.claimed_at = now
            return True
        # Another process sent it; ask again once that window ends
        remaining = sent_at + RATE_LIMIT_WINDOW - now
        cache.set(self.rate_key, 1, remaining.total_seconds())
        return False

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
            lost=partial(give_back_slot, self.rate_key, self.digest, self.claimed_at),
        )
