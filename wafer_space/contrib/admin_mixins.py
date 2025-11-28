"""Admin mixins for common functionality."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.http import HttpRequest


class StaffReadOnlyAdminMixin:
    """Mixin that grants all staff users read-only access to admin models.

    Staff users (is_staff=True) can view all records but cannot add, change,
    or delete unless they also have explicit permissions or are superusers.
    """

    def has_view_permission(
        self,
        request: HttpRequest,
        obj: object | None = None,
    ) -> bool:
        """Grant view permission to all staff users."""
        if request.user.is_staff:
            return True
        return super().has_view_permission(request, obj)  # type: ignore[misc]

    def has_module_permission(self, request: HttpRequest) -> bool:
        """Grant module access to all staff users (shows app in admin index)."""
        if request.user.is_staff:
            return True
        return super().has_module_permission(request)  # type: ignore[misc]
