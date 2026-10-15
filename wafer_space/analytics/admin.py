"""Read-only admin for the request log (#379)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import admin

from wafer_space.analytics.models import RequestLog
from wafer_space.contrib.admin_mixins import StaffReadOnlyAdminMixin

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import HttpRequest


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
    list_filter = [LoggedInFilter, "view_name", "status", "method"]
    search_fields = ["path", "username", "client_ip", "request_id"]
    date_hierarchy = "created_at"
    list_select_related = False
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
