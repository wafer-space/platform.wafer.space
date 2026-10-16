from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Configuration for the core app (shared utilities and their tables)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "wafer_space.core"
    verbose_name = "Core"
