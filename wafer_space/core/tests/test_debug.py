"""Tests for credential scrubbing in admin error reports."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest
from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from django.views.debug import get_default_exception_reporter_filter

from wafer_space.core.debug import CredentialScrubbingReporterFilter
from wafer_space.core.log import RateLimitedAdminEmailHandler

if TYPE_CHECKING:
    from collections.abc import Iterator

# Constants so the raw secret only ever appears in the settings override,
# never in a scrubbed value we assert on.
SENTINEL = "hunter2-do-not-leak"
BROKER_URL = f"sqla+postgresql://platform:{SENTINEL}@/platform?host=/var/run/pg"


@pytest.fixture(autouse=True)
def _clean_cache() -> Iterator[None]:
    """Isolate the admin-email handler's rate-limit keys between tests."""
    cache.clear()
    yield
    cache.clear()


class TestCredentialScrubbingReporterFilter:
    """Value-based scrubbing of ``scheme://user:password@`` in settings."""

    def test_is_configured_as_default_reporter_filter(self) -> None:
        """Settings wire our filter in for every environment."""
        assert isinstance(
            get_default_exception_reporter_filter(),
            CredentialScrubbingReporterFilter,
        )

    @override_settings(CELERY_BROKER_URL=BROKER_URL)
    def test_broker_url_password_is_scrubbed(self) -> None:
        """The DB password embedded in CELERY_BROKER_URL never appears."""
        safe = CredentialScrubbingReporterFilter().get_safe_settings()

        value = safe["CELERY_BROKER_URL"]
        assert SENTINEL not in value
        assert value.startswith("sqla+postgresql://platform:")
        assert value.endswith("@/platform?host=/var/run/pg")

    @override_settings(CELERY_BROKER_URL=BROKER_URL)
    def test_password_absent_from_entire_settings_dump(self) -> None:
        """No setting anywhere in the report leaks the credential."""
        safe = CredentialScrubbingReporterFilter().get_safe_settings()

        assert SENTINEL not in repr(safe)

    def test_urls_without_credentials_are_untouched(self) -> None:
        """Ordinary URLs (STATIC_URL, SITE_URL, ...) are not mangled."""
        filt = CredentialScrubbingReporterFilter()

        assert filt.cleanse_setting("SITE_URL", "https://example.com/a?b=c") == (
            "https://example.com/a?b=c"
        )
        assert filt.cleanse_setting("STATIC_URL", "/static/") == "/static/"

    def test_credentials_scrubbed_inside_nested_containers(self) -> None:
        """DOCKER_SERVERS-style lists of dicts are scrubbed recursively."""
        filt = CredentialScrubbingReporterFilter()
        value = [{"id": "x", "url": f"tcp://admin:{SENTINEL}@10.0.0.1:2375"}]

        cleansed = filt.cleanse_setting("DOCKER_SERVERS", value)

        assert SENTINEL not in repr(cleansed)
        assert cleansed[0]["url"].startswith("tcp://admin:")
        assert cleansed[0]["url"].endswith("@10.0.0.1:2375")

    def test_name_based_redaction_still_applies(self) -> None:
        """Django's own key-name rules keep working (SECRET_KEY etc.)."""
        filt = CredentialScrubbingReporterFilter()

        assert filt.cleanse_setting("SECRET_KEY", "abc") == filt.cleansed_substitute
        assert (
            filt.cleanse_setting(settings.SESSION_COOKIE_NAME, "abc")
            == filt.cleansed_substitute
        )

    @override_settings(CELERY_BROKER_URL=BROKER_URL)
    def test_admin_error_email_does_not_contain_password(self) -> None:
        """End to end: the mail ADMINS actually receive is clean."""
        handler = RateLimitedAdminEmailHandler()
        record = logging.LogRecord(
            name="wafer_space.test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="something broke",
            args=(),
            exc_info=None,
        )

        handler.emit(record)

        assert len(mail.outbox) == 1
        body = mail.outbox[0].body
        assert "CELERY_BROKER_URL" in body
        assert SENTINEL not in body

    def test_credentials_scrubbed_from_traceback_local_variables(self) -> None:
        """A local holding a DSN is scrubbed in the traceback section too."""
        filt = CredentialScrubbingReporterFilter()

        with pytest.raises(RuntimeError) as excinfo:
            _fail_holding_broker_url()
        # The innermost frame is _fail_holding_broker_url's.
        tb = excinfo.tb
        while tb.tb_next is not None:
            tb = tb.tb_next

        frame_vars = dict(filt.get_traceback_frame_variables(None, tb.tb_frame))

        assert SENTINEL not in repr(frame_vars)
        assert frame_vars["broker_url"].endswith("@/platform?host=/var/run/pg")


def _fail_holding_broker_url() -> None:
    """Raise while a local variable holds the credential-bearing URL."""
    broker_url = BROKER_URL
    msg = f"cannot connect to {broker_url.split('://', 1)[0]}"
    raise RuntimeError(msg)
