"""Logging utilities for admin error reporting."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from django.core.cache import cache
from django.utils.log import AdminEmailHandler

if TYPE_CHECKING:
    import logging

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
    """

    def emit(self, record: logging.LogRecord) -> None:
        signature = f"{record.name}:{record.levelno}:{record.msg}"
        digest = hashlib.sha256(signature.encode()).hexdigest()
        if cache.add(f"admin-email-rate:{digest}", 1, RATE_LIMIT_SECONDS):
            super().emit(record)
