"""Read-only admin for the request log (#379).

The table grows without limit, so every filter offers a fixed set of
choices (no SELECT DISTINCT over the table) and search uses exact or
prefix matches that the indexes can serve.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import admin

from wafer_space.analytics.middleware import FILE_VIEW_NAMES
from wafer_space.analytics.models import RequestLog
from wafer_space.contrib.admin_mixins import StaffReadOnlyAdminMixin

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import HttpRequest

_STATUS_CLASSES = ("2", "3", "4", "5")
_STATUS_CLASS_WIDTH = 100
_METHODS = ("GET", "HEAD", "POST")


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
    """Who fetched what, from where. Staff can read; nobody can edit.

    Search matches a request id, client IP or username exactly, or a path
    by its beginning (for example /projects/<uuid>/).
    """

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
    search_fields = ["=request_id", "=client_ip", "=username", "^path"]
    date_hierarchy = "created_at"
    show_full_result_count = False

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
