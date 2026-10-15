"""Tests for the allauth adapters in wafer_space.users.adapters."""

from __future__ import annotations

import logging
import typing
from unittest.mock import patch
from urllib.parse import parse_qs
from urllib.parse import urlparse

import pytest
from allauth.account.adapter import get_adapter
from allauth.socialaccount.providers.base import AuthError
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from allauth.socialaccount.providers.oauth2.client import OAuth2Error
from django.contrib.messages import get_messages
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import Client
from django.test import RequestFactory
from django.test import override_settings
from django.urls import reverse

from wafer_space.core.log import RateLimitedAdminEmailHandler
from wafer_space.users.adapters import SocialAccountAdapter

if typing.TYPE_CHECKING:
    from django.core.mail import EmailMessage
    from django.http import HttpRequest

ADAPTER_LOGGER = "wafer_space.users.adapters"
# allauth's default ACCOUNT_RATE_LIMITS["login"] is "30/m/ip".
LOGIN_RATE_LIMIT_PER_MINUTE = 30
HTTP_TOO_MANY_REQUESTS = 429
HTTP_FOUND = 302


def _dummy_get_response(request: HttpRequest) -> HttpResponse:
    return HttpResponse()


@pytest.fixture
def auth_request() -> HttpRequest:
    """A request with session and messages support, like a real callback."""
    request = RequestFactory().get("/accounts/google/login/callback/")
    SessionMiddleware(_dummy_get_response).process_request(request)
    MessageMiddleware(_dummy_get_response).process_request(request)
    return request


def _flash_messages(request: HttpRequest) -> list[str]:
    return [str(message) for message in get_messages(request)]


class TestOnAuthenticationError:
    """SocialAccountAdapter.on_authentication_error handles allauth codes.

    allauth passes ``error`` as an ``AuthError`` *string* constant
    ("unknown", "cancelled", "denied"), never an Exception, and only
    populates ``exception`` for genuine failures.
    """

    def test_error_code_logged_instead_of_python_type_name(
        self,
        auth_request: HttpRequest,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The AuthError code must appear in the log, not the word 'str'."""
        adapter = SocialAccountAdapter()
        with caplog.at_level(logging.INFO, logger=ADAPTER_LOGGER):
            adapter.on_authentication_error(
                auth_request,
                "google",
                error=AuthError.UNKNOWN,
            )
        [record] = caplog.records
        message = record.getMessage()
        assert "unknown" in message
        assert "str" not in message

    def test_string_error_is_not_used_as_exc_info(
        self,
        auth_request: HttpRequest,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A string error code must not be passed to exc_info.

        Passing a truthy non-exception to exc_info makes logging call
        sys.exc_info(), producing the useless "No exception message
        supplied" admin email report.
        """
        adapter = SocialAccountAdapter()
        with caplog.at_level(logging.INFO, logger=ADAPTER_LOGGER):
            adapter.on_authentication_error(
                auth_request,
                "google",
                error=AuthError.UNKNOWN,
            )
        [record] = caplog.records
        assert record.exc_info is None

    def test_real_exception_is_used_as_exc_info(
        self,
        auth_request: HttpRequest,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Genuine exceptions keep their traceback in the log record."""
        adapter = SocialAccountAdapter()
        exc = OAuth2Error("token endpoint unreachable")
        with caplog.at_level(logging.INFO, logger=ADAPTER_LOGGER):
            adapter.on_authentication_error(
                auth_request,
                "google",
                error=AuthError.UNKNOWN,
                exception=exc,
            )
        [record] = caplog.records
        assert record.levelno == logging.ERROR
        assert record.exc_info is not None
        assert record.exc_info[1] is exc

    def test_request_is_attached_to_log_record(
        self,
        auth_request: HttpRequest,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """AdminEmailHandler needs record.request to include request data."""
        adapter = SocialAccountAdapter()
        with caplog.at_level(logging.INFO, logger=ADAPTER_LOGGER):
            adapter.on_authentication_error(
                auth_request,
                "google",
                error=AuthError.UNKNOWN,
            )
        [record] = caplog.records
        assert getattr(record, "request", None) is auth_request

    def test_cancellation_is_not_logged_as_error(
        self,
        auth_request: HttpRequest,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A user cancelling the consent screen must not email admins."""
        adapter = SocialAccountAdapter()
        with caplog.at_level(logging.INFO, logger=ADAPTER_LOGGER):
            adapter.on_authentication_error(
                auth_request,
                "google",
                error=AuthError.CANCELLED,
            )
        assert all(record.levelno < logging.ERROR for record in caplog.records), (
            "cancellation was logged at ERROR level"
        )

    def test_cancellation_adds_no_flash_message(
        self,
        auth_request: HttpRequest,
    ) -> None:
        """allauth shows its own 'login cancelled' page; no flash needed."""
        adapter = SocialAccountAdapter()
        adapter.on_authentication_error(
            auth_request,
            "google",
            error=AuthError.CANCELLED,
        )
        assert _flash_messages(auth_request) == []

    def test_failure_adds_user_facing_flash_message(
        self,
        auth_request: HttpRequest,
    ) -> None:
        """Genuine failures still tell the user what happened."""
        adapter = SocialAccountAdapter()
        adapter.on_authentication_error(
            auth_request,
            "google",
            error=AuthError.UNKNOWN,
        )
        messages = _flash_messages(auth_request)
        assert len(messages) == 1
        assert "Google login failed" in messages[0]

    def test_provider_instance_is_accepted(
        self,
        auth_request: HttpRequest,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """allauth 65.x passes a Provider instance, not a string id."""

        class FakeProvider:
            id = "google"

        adapter = SocialAccountAdapter()
        with caplog.at_level(logging.INFO, logger=ADAPTER_LOGGER):
            adapter.on_authentication_error(
                auth_request,
                FakeProvider(),
                error=AuthError.UNKNOWN,
            )
        [record] = caplog.records
        assert "google" in record.getMessage()


class TestAccountAdapterClientIP:
    """allauth's rate limits, user sessions and emails use the trusted IP."""

    def test_forged_x_forwarded_for_is_ignored(self) -> None:
        """allauth's default takes the client-controlled first XFF entry."""
        request = RequestFactory().post(
            "/accounts/login/",
            REMOTE_ADDR="203.0.113.9",
            HTTP_X_FORWARDED_FOR="198.51.100.66, 203.0.113.9",
        )

        assert get_adapter(request).get_client_ip(request) == "203.0.113.9"

    def test_missing_client_ip_fails_loudly(self) -> None:
        """No IP means a proxy misconfiguration; never share one bucket."""
        request = RequestFactory().post("/accounts/login/", REMOTE_ADDR="")

        with pytest.raises(PermissionDenied):
            get_adapter(request).get_client_ip(request)


@pytest.mark.django_db
class TestLoginRateLimitUsesTrustedIP:
    """End to end: rotating a forged X-Forwarded-For no longer dodges limits."""

    @pytest.fixture(autouse=True)
    def _clean_cache(self) -> typing.Iterator[None]:
        cache.clear()
        yield
        cache.clear()

    @override_settings(TRUST_X_REAL_IP=True)
    def test_rotating_forged_xff_is_still_rate_limited(self, client: Client) -> None:
        """allauth's per-IP login limit keys on X-Real-IP, not on XFF."""
        statuses = [
            client.post(
                reverse("account_login"),
                {"login": "nobody@example.com", "password": "wrong"},
                HTTP_X_REAL_IP="203.0.113.9",
                HTTP_X_FORWARDED_FOR=f"198.51.100.{attempt}, 203.0.113.9",
            ).status_code
            for attempt in range(LOGIN_RATE_LIMIT_PER_MINUTE + 1)
        ]

        assert HTTP_TOO_MANY_REQUESTS not in statuses[:-1]
        assert statuses[-1] == HTTP_TOO_MANY_REQUESTS

    def test_rate_limited_login_renders_429_page(self, client: Client) -> None:
        """allauth renders 429.html; without it the visitor got a 500."""
        responses = [
            client.post(
                reverse("account_login"),
                {"login": "nobody@example.com", "password": "wrong"},
            )
            for _attempt in range(LOGIN_RATE_LIMIT_PER_MINUTE + 1)
        ]

        assert responses[-1].status_code == HTTP_TOO_MANY_REQUESTS
        assert b"Too many requests (429)" in responses[-1].content


@pytest.mark.django_db
class TestCallbackWithoutProviderResponse:
    """Crawlers fetching the bare OAuth callback must not email ADMINS (#338).

    The adapter logger gets the RateLimitedAdminEmailHandler that prod and
    stage attach to ``wafer_space``, so ``mailoutbox`` shows what ADMINS
    would receive.
    """

    CRAWLER_UA = (
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; "
        "Amazonbot/0.1; +https://developer.amazon.com/support/amazonbot) "
        "Chrome/119.0.6045.214 Safari/537.36"
    )

    @pytest.fixture(autouse=True)
    def _admin_email_handler(self) -> typing.Iterator[None]:
        handler = RateLimitedAdminEmailHandler()
        handler.setLevel(logging.ERROR)
        adapter_logger = logging.getLogger(ADAPTER_LOGGER)
        adapter_logger.addHandler(handler)
        cache.clear()
        yield
        adapter_logger.removeHandler(handler)
        cache.clear()

    @staticmethod
    def _start_login(client: Client) -> str:
        """Begin a real Google login and return the state it stashed."""
        response = client.get(reverse("google_login"))
        assert response.status_code == HTTP_FOUND
        query = parse_qs(urlparse(response["Location"]).query)
        [state] = query["state"]
        return state

    def test_bare_callback_logs_warning_without_email(
        self,
        client: Client,
        caplog: pytest.LogCaptureFixture,
        mailoutbox: list[EmailMessage],
    ) -> None:
        """The exact crawler request from the issue: no query, no cookie."""
        with caplog.at_level(logging.INFO, logger=ADAPTER_LOGGER):
            client.get(reverse("google_callback"), HTTP_USER_AGENT=self.CRAWLER_UA)

        [record] = caplog.records
        assert record.levelno == logging.WARNING
        assert mailoutbox == []

    def test_expired_session_callback_still_emails(
        self,
        client: Client,
        mailoutbox: list[EmailMessage],
    ) -> None:
        """A real redirect back whose session state is gone is a real failure."""
        client.get(reverse("google_callback"), {"state": "lost", "code": "abc"})

        [email] = mailoutbox
        assert "Social authentication error for google" in email.subject

    def test_provider_error_still_emails(
        self,
        client: Client,
        mailoutbox: list[EmailMessage],
    ) -> None:
        """Google redirecting back with ?error= (not a cancel) is reported."""
        state = self._start_login(client)

        client.get(
            reverse("google_callback"),
            {"state": state, "error": "server_error"},
        )

        [email] = mailoutbox
        assert "Social authentication error for google" in email.subject

    def test_bad_code_still_emails(
        self,
        client: Client,
        mailoutbox: list[EmailMessage],
    ) -> None:
        """A code the token endpoint rejects is reported with its traceback."""
        state = self._start_login(client)

        with patch.object(
            OAuth2Client,
            "get_access_token",
            side_effect=OAuth2Error("invalid_grant"),
        ):
            client.get(
                reverse("google_callback"),
                {"state": state, "code": "bad"},
            )

        [email] = mailoutbox
        assert "Social authentication error for google" in email.subject
        assert "OAuth2Error" in email.body
