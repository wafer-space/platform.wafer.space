"""Logging utilities for admin error reporting."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING
from typing import Any

from django.core.cache import cache
from django.utils.log import AdminEmailHandler

from wafer_space.core.debug import scrub_url_credentials

if TYPE_CHECKING:
    import logging

    from django.utils.functional import Promise

# At most one email per error signature per window. A signature is
# (logger name, level, unformatted message template), so a repeating error
# that interpolates changing values (digests, task ids, ...) still counts
# as a single signature.
RATE_LIMIT_SECONDS = 60 * 60


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
        html_message = kwargs.get("html_message")
        if html_message is not None:
            kwargs["html_message"] = scrub_url_credentials(html_message)
        super().send_mail(
            scrub_url_credentials(str(subject)),
            scrub_url_credentials(str(message)),
            *args,
            **kwargs,
        )
