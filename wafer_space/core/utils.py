"""Core utility functions used across wafer_space applications."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from django.conf import settings

if TYPE_CHECKING:
    from django.http import HttpRequest


def is_production_environment() -> bool:
    """Check if the application is running in a production-like environment.

    Returns True if ANY of the following conditions indicate production:
    - DEBUG is False
    - Database engine is PostgreSQL (not SQLite)
    - Settings module contains prod/stage/production/staging

    This is a safety check to prevent dangerous operations (like creating
    test users with weak passwords) from running on production systems.

    Returns:
        True if running in production, False if running in development/test.
    """
    # Check DEBUG setting
    if not settings.DEBUG:
        return True

    # Check database engine - production uses PostgreSQL
    db_engine = settings.DATABASES.get("default", {}).get("ENGINE", "")
    if "postgresql" in db_engine or "postgres" in db_engine:
        return True

    # Check settings module name
    settings_module = os.environ.get("DJANGO_SETTINGS_MODULE", "").lower()
    production_settings = ("prod", "stage", "production", "staging")
    return any(name in settings_module for name in production_settings)


def get_client_ip(request: HttpRequest) -> str | None:
    """Return the client IP, as resolved by RealClientIPMiddleware.

    Single source of truth for every consumer. Falsy values (gunicorn on a
    unix socket leaves REMOTE_ADDR as ``""``) are normalised to ``None`` so the
    result can be stored in a ``GenericIPAddressField`` (Postgres ``inet``
    rejects the empty string). Never reads X-Forwarded-For -- its first entry
    is client-controlled.
    """
    return request.META.get("REMOTE_ADDR") or None
