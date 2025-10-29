"""Context processors for notifications."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .models import Notification

if TYPE_CHECKING:
    from django.http import HttpRequest


def unread_notifications_count(request: HttpRequest) -> dict[str, int]:
    """Add unread notification count to template context.

    Args:
        request: The HTTP request object

    Returns:
        Dictionary with unread_count key
    """
    if not request.user.is_authenticated:
        return {"unread_count": 0}

    count = Notification.objects.filter(user=request.user, is_read=False).count()
    return {"unread_count": count}
