"""Exception-report filtering for admin error emails.

Django's :class:`~django.views.debug.SafeExceptionReporterFilter` redacts
settings by *name* only (``API|AUTH|TOKEN|KEY|SECRET|PASS|...``). A
setting such as ``CELERY_BROKER_URL`` matches none of those, so the
database password embedded in ``sqla+postgresql://user:password@/db``
was mailed to ADMINS in every error report (issue #339).

:class:`CredentialScrubbingReporterFilter` keeps Django's name-based
rules and additionally scrubs ``scheme://user:password@`` credentials
out of every string value, recursing through dicts/lists/tuples via the
parent implementation. Only the password is replaced, so the host and
scheme stay readable in the report.
"""

from __future__ import annotations

import re
from typing import Any

from django.views.debug import SafeExceptionReporterFilter

# ``scheme://user:password@`` - the userinfo part of an RFC 3986 URL. The
# scheme may contain ``+`` (``sqla+postgresql``). Passwords cannot contain
# an unescaped ``@`` or ``/``; the ``\s`` exclusion stops the match running
# across whitespace-separated words in prose settings.
_URL_CREDENTIALS = re.compile(
    r"(?P<prefix>[A-Za-z][A-Za-z0-9+.\-]*://[^:/@\s]*:)(?P<password>[^@/\s]+)@",
)


class CredentialScrubbingReporterFilter(SafeExceptionReporterFilter):
    """SafeExceptionReporterFilter that also scrubs URL-embedded passwords."""

    def cleanse_setting(self, key: Any, value: Any) -> Any:
        cleansed = super().cleanse_setting(key, value)
        if isinstance(cleansed, str):
            return self.scrub_url_credentials(cleansed)
        return cleansed

    def scrub_url_credentials(self, value: str) -> str:
        """Replace the password in any ``scheme://user:password@`` with stars."""
        return _URL_CREDENTIALS.sub(
            lambda m: f"{m.group('prefix')}{self.cleansed_substitute}@",
            value,
        )
