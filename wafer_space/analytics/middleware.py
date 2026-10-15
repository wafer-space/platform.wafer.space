"""Write one RequestLog row per logged request (#379)."""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING
from typing import Any
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

from django.conf import settings
from django.db import DatabaseError
from django.db import connection
from django.db import transaction
from django.urls import Resolver404
from django.urls import resolve
from django.utils import timezone

from wafer_space.analytics.constants import FILE_VIEW_NAMES
from wafer_space.analytics.constants import REQUEST_ID_RE
from wafer_space.analytics.models import RequestLog
from wafer_space.core.utils import get_client_ip

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest
    from django.http import HttpResponse
    from django.urls import ResolverMatch

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
REDACTED = "<redacted>"
_METHOD_LENGTH = 10

# URLs whose path carries a one-time secret (allauth's email-confirmation
# and password-reset keys). For these the stored path is the URL pattern,
# and the secret kwargs are stored as REDACTED.
_SECRET_KWARGS: dict[str, tuple[str, ...]] = {
    "account_confirm_email": ("key",),
    "account_reset_password_from_key": ("uidb36", "key"),
}

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
    if settings.TRUST_X_REAL_IP and REQUEST_ID_RE.fullmatch(header):
        return header
    return uuid.uuid4().hex


def _text(value: str, length: int) -> str:
    """Storable text: no NUL (PostgreSQL rejects it), at most length chars."""
    return value.replace("\x00", "")[:length]


def _resolve(path: str) -> ResolverMatch | None:
    try:
        return resolve(path)
    except Resolver404:
        return None


def _match(request: HttpRequest) -> ResolverMatch | None:
    """The request's URL match, resolving it here if no view was reached.

    Middleware that answers early (the ToS redirect, for one) returns
    before URL resolution, but the row must still say what was asked for.
    """
    return request.resolver_match or _resolve(request.path_info)


def _stored_path(path: str, match: ResolverMatch | None) -> str:
    if match and match.view_name in _SECRET_KWARGS:
        return "/" + match.route
    return path


def _stored_kwargs(match: ResolverMatch | None) -> dict[str, Any]:
    """URL kwargs as JSON values, with secrets redacted.

    UUIDs and other converted values become strings.
    """
    if match is None:
        return {}
    secret = _SECRET_KWARGS.get(match.view_name, ())
    stored: dict[str, Any] = {}
    for key, value in match.kwargs.items():
        if key in secret:
            stored[key] = REDACTED
        elif isinstance(value, int):
            stored[key] = value
        else:
            stored[key] = _text(str(value), RequestLog.PATH_LENGTH)
    return stored


def _stored_referrer(referrer: str) -> str:
    """The Referer without query, fragment, credentials or secret path.

    A header that is not a parsable URL is stored as "".
    """
    try:
        parts = urlsplit(referrer)
        host = parts.hostname or ""
        port = parts.port
    except ValueError:
        return ""
    if ":" in host:
        host = f"[{host}]"
    netloc = f"{host}:{port}" if port else host
    path = _stored_path(parts.path, _resolve(parts.path) if parts.path else None)
    return urlunsplit((parts.scheme, netloc, path, "", ""))


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


def _row_fields(
    request: HttpRequest,
    response: HttpResponse,
    match: ResolverMatch | None,
) -> dict[str, Any]:
    """The RequestLog fields that come from the request and response."""
    user = request.user if request.user.is_authenticated else None
    return {
        "user": user,
        "username": user.get_username() if user else "",
        "client_ip": get_client_ip(request),
        "method": _text(request.method or "", _METHOD_LENGTH),
        "path": _text(_stored_path(request.path, match), RequestLog.PATH_LENGTH),
        "view_name": match.view_name if match else "",
        "route_kwargs": _stored_kwargs(match),
        "status": response.status_code,
        "bytes": _response_bytes(response),
        "user_agent": _text(
            request.headers.get("user-agent", ""), RequestLog.USER_AGENT_LENGTH
        ),
        "referrer": _text(
            _stored_referrer(request.headers.get("referer", "")),
            RequestLog.REFERRER_LENGTH,
        ),
    }


def _skip_wal_flush() -> None:
    """Let this transaction commit without waiting for the WAL flush.

    On PostgreSQL 17 a one-row autocommit INSERT took ~9 ms, almost all
    of it the flush; with synchronous_commit off, ~1.5 ms. The trade-off
    is that a database server crash can lose the last fraction of a
    second of request log rows - never corrupt them. Only this
    transaction is affected (SET LOCAL), so it is called only when the
    row's transaction is the outermost one.
    """
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL synchronous_commit TO OFF")


def _write_row(fields: dict[str, Any]) -> None:
    """Insert one row; a DatabaseError is logged loudly, never raised."""
    outermost = not connection.in_atomic_block
    try:
        with transaction.atomic():
            if outermost:
                _skip_wal_flush()
            RequestLog.objects.create(**fields)
    except DatabaseError:
        # Loud (ERROR reaches ADMINS through the rate-limited handler), but
        # the visitor still gets their page: a missing analytics row must
        # not turn into a 500.
        logger.exception(
            "Could not write the request log row for %s %s",
            fields["method"],
            fields["path"],
        )


class RequestLogMiddleware:
    """Record who fetched what, from where, logged in or not.

    Placed after AuthenticationMiddleware so request.user is known. The row
    is written after the response, outside the view's transaction, so a view
    that rolled back is still logged. Every response that reaches this
    middleware carries the request id in X-Request-ID, logged or not;
    responses from middleware earlier in the stack (WhiteNoise, an
    APPEND_SLASH redirect) do not.
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

        if request.path.startswith(_SKIPPED_PATH_PREFIXES):
            return response
        match = _match(request)
        view_name = match.view_name if match else ""
        if view_name.startswith(_SKIPPED_VIEW_PREFIX):
            return response
        if request.user.is_authenticated or view_name in FILE_VIEW_NAMES:
            fields = _row_fields(request, response, match)
            fields["created_at"] = started_at
            fields["request_id"] = request_id
            fields["duration_ms"] = int((time.monotonic() - started) * 1000)
            _write_row(fields)
        return response
