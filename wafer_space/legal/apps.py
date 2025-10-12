"""App configuration for legal app."""

from django.apps import AppConfig


class LegalConfig(AppConfig):
    """Configuration for the legal app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "wafer_space.legal"
    verbose_name = "Legal"
