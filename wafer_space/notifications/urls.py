"""URLs for notifications app."""

from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.NotificationListView.as_view(), name="list"),
    path(
        "<int:notification_id>/read/",
        views.mark_notification_read,
        name="mark_read",
    ),
    path("mark-all-read/", views.mark_all_notifications_read, name="mark_all_read"),
    path("unread-count/", views.get_unread_count, name="unread_count"),
]
