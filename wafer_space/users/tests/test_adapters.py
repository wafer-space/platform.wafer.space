"""Tests for the allauth adapters in wafer_space.users.adapters."""

from __future__ import annotations

import logging
import typing

import pytest
from allauth.socialaccount.providers.base import AuthError
from allauth.socialaccount.providers.oauth2.client import OAuth2Error
from django.contrib.messages import get_messages
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse
from django.test import RequestFactory

from wafer_space.users.adapters import SocialAccountAdapter

if typing.TYPE_CHECKING:
    from django.http import HttpRequest

ADAPTER_LOGGER = "wafer_space.users.adapters"


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
