"""Write one RequestLog row per logged request (#379)."""

from __future__ import annotations

import logging
import re
import time
import uuid
from typing import TYPE_CHECKING
from typing import Any
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

from django.conf import settings
from django.db import DatabaseError
from django.utils import timezone

from wafer_space.analytics.models import RequestLog
from wafer_space.core.utils import get_client_ip

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest
    from django.http import HttpResponse

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_RE = re.compile(r"[0-9a-f]{32}")

# Logged for every visitor, logged in or not: a failed or redirected fetch
# of a file is still an attempt to fetch it.
FILE_VIEW_NAMES = frozenset(
    {
        "projects:check_artifact",
        "projects:check_log",
        "projects:file_download",
    }
)

# Never logged: probes, static files, and the analytics admin itself
# (reading the log must not add to it).
_SKIPPED_PATH_PREFIXES = ("/health/", settings.STATIC_URL)
_SKIPPED_VIEW_PREFIX = "admin:analytics_requestlog_"


def _request_id(request: HttpRequest) -> str:
    """nginx's $request_id when it can be trusted, else a fresh one.

    The header is trusted on the same terms as X-Real-IP: only where nginx
    is the sole ingress (TRUST_X_REAL_IP), and only in nginx's format.
    """
    header = request.headers.get("x-request-id", "")
    if settings.TRUST_X_REAL_IP and _REQUEST_ID_RE.fullmatch(header):
        return header
    return uuid.uuid4().hex


def _without_query(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _json_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """URL kwargs as JSON values: UUIDs and other converters become strings."""
    return {
        key: value if isinstance(value, int | str) else str(value)
        for key, value in kwargs.items()
    }


def _response_bytes(response: HttpResponse) -> int | None:
    """Size of the response body, when the application knows it.

    CommonMiddleware adds Content-Length only after this middleware has
    run, so a plain response is measured directly. A streaming response
    (FileResponse) has Content-Length from the file size, or nothing.
    """
    if not response.streaming:
        return len(response.content)
    content_length = response.get("Content-Length")
    return int(content_length) if content_length else None


class RequestLogMiddleware:
    """Record who fetched what, from where, logged in or not.

    Placed after AuthenticationMiddleware so request.user is known. The row
    is written after the response, outside the view's transaction, so a view
    that rolled back is still logged. Every response carries the request id
    in X-Request-ID, logged or not.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        """Initialize middleware."""
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Serve the request, then log it if it is one we record."""
        started_at = timezone.now()
        started = time.monotonic()
        request_id = _request_id(request)

        response = self.get_response(request)
        response[REQUEST_ID_HEADER] = request_id

        if self._should_log(request):
            self._log(request, response, request_id, started_at, started)
        return response

    def _should_log(self, request: HttpRequest) -> bool:
        if request.path.startswith(_SKIPPED_PATH_PREFIXES):
            return False
        match = request.resolver_match
        view_name = match.view_name if match else ""
        if view_name.startswith(_SKIPPED_VIEW_PREFIX):
            return False
        return request.user.is_authenticated or view_name in FILE_VIEW_NAMES

    def _log(
        self,
        request: HttpRequest,
        response: HttpResponse,
        request_id: str,
        started_at: Any,
        started: float,
    ) -> None:
        user = request.user if request.user.is_authenticated else None
        match = request.resolver_match
        try:
            RequestLog.objects.create(
                created_at=started_at,
                request_id=request_id,
                user=user,
                username=user.get_username() if user else "",
                client_ip=get_client_ip(request),
                method=request.method or "",
                path=request.path[: RequestLog.PATH_LENGTH],
                view_name=match.view_name if match else "",
                route_kwargs=_json_kwargs(match.kwargs) if match else {},
                status=response.status_code,
                bytes=_response_bytes(response),
                duration_ms=int((time.monotonic() - started) * 1000),
                user_agent=request.headers.get("user-agent", "")[
                    : RequestLog.USER_AGENT_LENGTH
                ],
                referrer=_without_query(request.headers.get("referer", ""))[
                    : RequestLog.REFERRER_LENGTH
                ],
            )
        except DatabaseError:
            # Loud (ERROR reaches ADMINS through the rate-limited handler),
            # but the visitor still gets their page: a missing analytics row
            # must not turn into a 500.
            logger.exception(
                "Could not write the request log row for %s %s",
                request.method,
                request.path,
            )
