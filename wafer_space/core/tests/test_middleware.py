"""Tests for RealClientIPMiddleware (issue #274).

Behind gunicorn on a unix socket ``REMOTE_ADDR`` is empty; nginx resolves the
real visitor (Cloudflare-scoped ``real_ip``) and forwards it in ``X-Real-IP``.
The middleware copies that into ``REMOTE_ADDR`` -- but only when
``TRUST_X_REAL_IP`` is on, and never from the client-controlled
``X-Forwarded-For``.
"""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest
from django.http import HttpResponse
from django.test import RequestFactory
from django.test import override_settings

from wafer_space.core.middleware import RealClientIPMiddleware

MIDDLEWARE_PATH = "wafer_space.core.middleware.RealClientIPMiddleware"


def _run(request: HttpRequest) -> str | None:
    """Pass ``request`` through the middleware; return the REMOTE_ADDR it sees."""
    seen: dict[str, str | None] = {}

    def get_response(req: HttpRequest) -> HttpResponse:
        seen["remote_addr"] = req.META.get("REMOTE_ADDR")
        return HttpResponse()

    RealClientIPMiddleware(get_response)(request)
    return seen["remote_addr"]


def _request(**meta: str) -> HttpRequest:
    request = RequestFactory().get("/")
    # Mirror gunicorn-on-a-unix-socket: REMOTE_ADDR present but empty.
    request.META["REMOTE_ADDR"] = ""
    request.META.update(meta)
    return request


def test_registered_first_in_middleware() -> None:
    """It runs before anything else so every later consumer sees the real IP."""
    assert settings.MIDDLEWARE[0] == MIDDLEWARE_PATH


@override_settings(TRUST_X_REAL_IP=True)
def test_rewrites_remote_addr_from_x_real_ip() -> None:
    """A trusted X-Real-IP replaces REMOTE_ADDR."""
    request = _request(HTTP_X_REAL_IP="198.51.100.23")

    assert _run(request) == "198.51.100.23"


@override_settings(TRUST_X_REAL_IP=True)
def test_rewrites_remote_addr_from_ipv6_x_real_ip() -> None:
    """IPv6 visitors (which reach the VM directly) are handled too."""
    request = _request(HTTP_X_REAL_IP="2001:db8:85a3::8a2e:370:7334")

    assert _run(request) == "2001:db8:85a3::8a2e:370:7334"


@override_settings(TRUST_X_REAL_IP=True)
def test_leaves_remote_addr_when_header_absent() -> None:
    """No X-Real-IP -> REMOTE_ADDR untouched (no fallback to anything else)."""
    request = _request()

    assert _run(request) == ""


@override_settings(TRUST_X_REAL_IP=True)
def test_leaves_remote_addr_when_header_malformed() -> None:
    """A non-IP X-Real-IP is ignored rather than stored."""
    request = _request(HTTP_X_REAL_IP="not-an-ip")

    assert _run(request) == ""


@override_settings(TRUST_X_REAL_IP=True)
def test_never_consults_x_forwarded_for() -> None:
    """X-Forwarded-For is client-controlled and must never be trusted."""
    request = _request(HTTP_X_FORWARDED_FOR="203.0.113.99, 10.0.0.1")

    assert _run(request) == ""


@override_settings(TRUST_X_REAL_IP=False)
def test_ignores_x_real_ip_when_trust_disabled() -> None:
    """Without TRUST_X_REAL_IP (dev/test) a supplied X-Real-IP is ignored."""
    request = _request(HTTP_X_REAL_IP="198.51.100.23")

    assert _run(request) == ""
