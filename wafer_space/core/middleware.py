"""Middleware for running behind the nginx proxy: real client IP, user header."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from ipware import get_client_ip as ipware_get_client_ip

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest
    from django.http import HttpResponse

# Only X-Real-IP is consulted. nginx sets it authoritatively from its own
# (Cloudflare-scoped real_ip) resolution and gunicorn is reachable only via
# a local unix socket, so nothing else can inject it. X-Forwarded-For is
# deliberately excluded: its first entry is client-controlled.
_TRUSTED_HEADERS = ("HTTP_X_REAL_IP",)


class RealClientIPMiddleware:
    """Copy the nginx-resolved visitor IP from X-Real-IP into REMOTE_ADDR.

    Behind gunicorn on a unix socket REMOTE_ADDR is empty, so anything that
    reads it (audit logs, TOS acceptance records, rate limiting) records the
    wrong value. Gated by ``TRUST_X_REAL_IP`` (off in dev/test, on where nginx
    is the sole ingress); when off, or when the header is absent or malformed,
    REMOTE_ADDR is left untouched -- there is no fallback to a spoofable source.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        """Initialize middleware."""
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Rewrite REMOTE_ADDR when a trusted X-Real-IP is present."""
        if settings.TRUST_X_REAL_IP:
            client_ip, _is_routable = ipware_get_client_ip(
                request,
                request_header_order=_TRUSTED_HEADERS,
            )
            if client_ip:
                request.META["REMOTE_ADDR"] = client_ip
        return self.get_response(request)


# nginx logs this header and strips it from what the client receives
# (hetzner-ansible #165: $upstream_http_x_platform_user, proxy_hide_header).
PLATFORM_USER_HEADER = "X-Platform-User"


class PlatformUserHeaderMiddleware:
    """Put the authenticated user's primary key in an X-Platform-User header.

    It lets the nginx and gunicorn access logs record which account made a
    request (issue #379) without the app storing anything. The header is
    set from the user at response time, so a login response carries the
    newly logged-in user and a logout response carries none. Anonymous
    responses never carry it.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        """Initialize middleware."""
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Add the header to an authenticated user's response."""
        response = self.get_response(request)
        if request.user.is_authenticated:
            response[PLATFORM_USER_HEADER] = str(request.user.pk)
        return response
