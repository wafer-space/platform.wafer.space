"""Read-only admin for the request log (#379).

The table grows without limit, so every filter offers a fixed set of
choices (no SELECT DISTINCT over the table), and search picks one exact,
case-sensitive lookup that an index serves. The one exception is a path
prefix, which scans the rows: narrow the date first.
"""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING

from django.contrib import admin

from wafer_space.analytics.constants import FILE_VIEW_NAMES
from wafer_space.analytics.constants import REQUEST_ID_RE
from wafer_space.analytics.models import RequestLog
from wafer_space.contrib.admin_mixins import StaffReadOnlyAdminMixin

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import HttpRequest

_STATUS_CLASSES = ("2", "3", "4", "5")
_STATUS_CLASS_WIDTH = 100
_METHODS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")


class LoggedInFilter(admin.SimpleListFilter):
    """Filter rows by whether the request came from a logged-in user."""

    title = "logged in"
    parameter_name = "logged_in"

    def lookups(
        self, request: HttpRequest, model_admin: admin.ModelAdmin[RequestLog]
    ) -> list[tuple[str, str]]:
        return [("yes", "Logged in"), ("no", "Anonymous")]

    def queryset(
        self, request: HttpRequest, queryset: QuerySet[RequestLog]
    ) -> QuerySet[RequestLog]:
        if self.value() == "yes":
            return queryset.filter(user__isnull=False)
        if self.value() == "no":
            return queryset.filter(user__isnull=True)
        return queryset


class FileViewFilter(admin.SimpleListFilter):
    """Filter rows to one file-serving view."""

    title = "file view"
    parameter_name = "file_view"

    def lookups(
        self, request: HttpRequest, model_admin: admin.ModelAdmin[RequestLog]
    ) -> list[tuple[str, str]]:
        return [(name, name) for name in sorted(FILE_VIEW_NAMES)]

    def queryset(
        self, request: HttpRequest, queryset: QuerySet[RequestLog]
    ) -> QuerySet[RequestLog]:
        if self.value() in FILE_VIEW_NAMES:
            return queryset.filter(view_name=self.value())
        return queryset


class StatusClassFilter(admin.SimpleListFilter):
    """Filter rows by status class: 2xx, 3xx, 4xx or 5xx."""

    title = "status"
    parameter_name = "status_class"

    def lookups(
        self, request: HttpRequest, model_admin: admin.ModelAdmin[RequestLog]
    ) -> list[tuple[str, str]]:
        return [(digit, f"{digit}xx") for digit in _STATUS_CLASSES]

    def queryset(
        self, request: HttpRequest, queryset: QuerySet[RequestLog]
    ) -> QuerySet[RequestLog]:
        value = self.value()
        if value not in _STATUS_CLASSES:
            return queryset
        low = int(value) * _STATUS_CLASS_WIDTH
        return queryset.filter(status__gte=low, status__lt=low + _STATUS_CLASS_WIDTH)


class MethodFilter(admin.SimpleListFilter):
    """Filter rows by request method."""

    title = "method"
    parameter_name = "method"

    def lookups(
        self, request: HttpRequest, model_admin: admin.ModelAdmin[RequestLog]
    ) -> list[tuple[str, str]]:
        return [(method, method) for method in _METHODS]

    def queryset(
        self, request: HttpRequest, queryset: QuerySet[RequestLog]
    ) -> QuerySet[RequestLog]:
        if self.value() in _METHODS:
            return queryset.filter(method=self.value())
        return queryset


@admin.register(RequestLog)
class RequestLogAdmin(StaffReadOnlyAdminMixin, admin.ModelAdmin):
    """Who fetched what, from where. Staff can read; nobody can edit."""

    list_display = [
        "created_at",
        "username",
        "client_ip",
        "method",
        "path",
        "view_name",
        "status",
        "bytes",
        "duration_ms",
    ]
    list_filter = [LoggedInFilter, FileViewFilter, StatusClassFilter, MethodFilter]
    # Shows the search box; get_search_results decides the lookup.
    search_fields = ["request_id", "client_ip", "username", "path"]
    search_help_text = (
        "A request id, an IP address or a username (exact), or a path "
        "beginning with / (prefix)."
    )
    date_hierarchy = "created_at"
    show_full_result_count = False

    def get_search_results(
        self,
        request: HttpRequest,
        queryset: QuerySet[RequestLog],
        search_term: str,
    ) -> tuple[QuerySet[RequestLog], bool]:
        """One exact lookup an index can serve, chosen by the term's shape.

        Django's default search is UPPER(...) LIKE '%term%' on every field,
        a full scan of a table that only grows.
        """
        term = search_term.strip()
        if not term:
            return queryset, False
        if REQUEST_ID_RE.fullmatch(term):
            return queryset.filter(request_id=term), False
        try:
            address = ipaddress.ip_address(term)
        except ValueError:
            pass
        else:
            # A scoped IPv6 address (fe80::1%eth0) parses here but is not
            # a valid inet value for PostgreSQL; treat it as a username.
            if not getattr(address, "scope_id", None):
                return queryset.filter(client_ip=str(address)), False
        if term.startswith("/"):
            return queryset.filter(path__startswith=term), False
        return queryset.filter(username=term), False

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(
        self, request: HttpRequest, obj: RequestLog | None = None
    ) -> bool:
        return False

    def has_delete_permission(
        self, request: HttpRequest, obj: RequestLog | None = None
    ) -> bool:
        return False
