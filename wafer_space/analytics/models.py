"""Per-request analytics: who fetched what, from where, logged in or not (#379).

See docs/request_analytics.md for what is stored, why, and who can read it.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class RequestLog(models.Model):
    """One row per logged request, written by RequestLogMiddleware.

    Logged: every request by a logged-in user, and every request to a
    file-serving view whoever makes it. Never logged: request bodies, and
    any header other than User-Agent and Referer.
    """

    PATH_LENGTH = 2048
    USER_AGENT_LENGTH = 512
    REFERRER_LENGTH = 512

    created_at = models.DateTimeField(
        default=timezone.now,
        help_text="When the request reached the application",
    )
    request_id = models.CharField(
        max_length=32,
        help_text="nginx $request_id (or one generated here); joins the nginx log",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="request_logs",
        help_text="Logged-in user, or empty for an anonymous request",
    )
    username = models.CharField(
        max_length=150,
        blank=True,
        help_text="Username at the time of the request (never the email)",
    )
    client_ip = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="Client address from the trusted X-Real-IP header",
    )
    method = models.CharField(max_length=10)
    path = models.CharField(
        max_length=PATH_LENGTH,
        help_text="Request path, without the query string",
    )
    view_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="URL name, e.g. projects:file_download; empty if no route matched",
    )
    route_kwargs = models.JSONField(
        default=dict,
        blank=True,
        help_text="URL arguments, e.g. the project pk and file pk",
    )
    status = models.PositiveSmallIntegerField()
    bytes = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        help_text="Content-Length of the response, when known. Behind nginx "
        "a file response has no body here; nginx logs the bytes sent.",
    )
    duration_ms = models.PositiveIntegerField(
        help_text="Time spent in the application",
    )
    user_agent = models.CharField(max_length=USER_AGENT_LENGTH, blank=True)
    referrer = models.CharField(
        max_length=REFERRER_LENGTH,
        blank=True,
        help_text="Referer header, without its query string",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["request_id"]),
            models.Index(fields=["view_name", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["client_ip", "-created_at"]),
        ]

    def __str__(self) -> str:
        who = self.username or "anonymous"
        return f"{self.created_at:%Y-%m-%d %H:%M:%S} {who} {self.method} {self.path}"
