from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    """Configuration for notifications app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "wafer_space.notifications"
    verbose_name = "Notifications"
