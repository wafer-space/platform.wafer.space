"""Views for notifications."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING
from typing import cast

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.utils import timezone
from django.views.generic import ListView

from .models import Notification

if TYPE_CHECKING:
    from wafer_space.users.models import User


class NotificationListView(LoginRequiredMixin, ListView):
    """List all notifications for the current user."""

    model = Notification
    template_name = "notifications/notification_list.html"
    context_object_name = "notifications"
    paginate_by = 20

    def get_queryset(self):
        """Get notifications for current user."""
        # Cast user since LoginRequiredMixin ensures authentication
        user = cast("User", self.request.user)
        queryset = Notification.objects.filter(user=user)

        # Filter by read status if requested
        status_filter = self.request.GET.get("status")
        if status_filter == "unread":
            queryset = queryset.filter(is_read=False)
        elif status_filter == "read":
            queryset = queryset.filter(is_read=True)

        return queryset.select_related("content_type")

    def get_context_data(self, **kwargs):
        """Add unread count to context."""
        context = super().get_context_data(**kwargs)
        # Cast user since LoginRequiredMixin ensures authentication
        user = cast("User", self.request.user)
        context["unread_count"] = Notification.objects.filter(
            user=user,
            is_read=False,
        ).count()
        context["status_filter"] = self.request.GET.get("status", "all")
        return context


@login_required
def mark_notification_read(request, notification_id):
    """Mark a notification as read and redirect to related object or list."""
    notification = get_object_or_404(
        Notification,
        id=notification_id,
        user=request.user,
    )

    # Mark as read
    notification.mark_as_read()

    # Try to redirect to related object if it exists
    if notification.content_object:
        # Try to get URL for the related object
        with contextlib.suppress(Exception):
            # For ProjectFile, redirect to the project detail page
            if hasattr(notification.content_object, "project"):
                return redirect(
                    "projects:detail",
                    pk=notification.content_object.project.pk,
                )

    # Default: redirect back to notifications list
    return redirect("notifications:list")


@login_required
def mark_all_notifications_read(request):
    """Mark all notifications as read for current user."""
    if request.method == "POST":
        Notification.objects.filter(user=request.user, is_read=False).update(
            is_read=True,
            read_at=timezone.now(),
        )

    return redirect("notifications:list")


@login_required
def get_unread_count(request):
    """Get unread notification count as JSON (for AJAX updates)."""
    count = Notification.objects.filter(user=request.user, is_read=False).count()
    return JsonResponse({"unread_count": count})
