"""Tests for environment-driven settings on prod and stage.

These verify the contract from issue #267: production and staging must read
``ALLOWED_HOSTS`` from the ``DJANGO_ALLOWED_HOSTS`` environment variable and
fail fast (``ImproperlyConfigured``) when it is not set, mirroring how
``DJANGO_SECRET_KEY`` is already handled.
"""

from __future__ import annotations

import importlib
import os
import sys
from typing import TYPE_CHECKING

import pytest
from django.core.exceptions import ImproperlyConfigured

if TYPE_CHECKING:
    from types import ModuleType

# Environment variables required to import the prod/stage settings modules,
# excluding DJANGO_ALLOWED_HOSTS (the variable under test). DATABASE_URL has a
# default in base.py, and base.py is not re-executed on reload, so only the
# values read at the top level of prod.py/stage.py need to be present.
REQUIRED_ENV = {
    "DJANGO_READ_DOT_ENV_FILE": "False",
    "DJANGO_SECRET_KEY": "test-secret-key",
    "MAILGUN_API_KEY": "test-mailgun-key",
    "GITHUB_CLIENT_SECRET": "test-github-secret",
    "GITLAB_CLIENT_SECRET": "test-gitlab-secret",
    "GOOGLE_CLIENT_SECRET": "test-google-secret",
    "DISCORD_CLIENT_SECRET": "test-discord-secret",
    "LINKEDIN_CLIENT_SECRET": "test-linkedin-secret",
}

SETTINGS_MODULES = ["config.settings.prod", "config.settings.stage"]


@pytest.fixture(autouse=True)
def _isolate_settings_modules() -> object:
    """Drop reloaded prod/stage modules so each test starts from a clean slate."""
    yield
    for name in SETTINGS_MODULES:
        sys.modules.pop(name, None)


def _load(module_name: str, environ: dict[str, str]) -> ModuleType:
    """Import a settings module fresh under a fully controlled environment.

    Replaces os.environ in-place so the module-level ``env`` singleton (whose
    ENVIRON *is* os.environ) sees exactly these values, then (re)executes the
    module body.
    """
    saved = dict(os.environ)
    os.environ.clear()
    os.environ.update(environ)
    try:
        existing = sys.modules.get(module_name)
        if existing is not None:
            return importlib.reload(existing)
        return importlib.import_module(module_name)
    finally:
        os.environ.clear()
        os.environ.update(saved)


@pytest.mark.parametrize("module_name", SETTINGS_MODULES)
def test_allowed_hosts_read_from_environment(module_name: str) -> None:
    """ALLOWED_HOSTS is parsed from the comma-separated DJANGO_ALLOWED_HOSTS var."""
    environ = {**REQUIRED_ENV, "DJANGO_ALLOWED_HOSTS": "example.com,foo.example.com"}

    module = _load(module_name, environ)

    assert module.ALLOWED_HOSTS == ["example.com", "foo.example.com"]


@pytest.mark.parametrize("module_name", SETTINGS_MODULES)
def test_missing_allowed_hosts_raises(module_name: str) -> None:
    """Importing the settings fails fast when DJANGO_ALLOWED_HOSTS is unset."""
    with pytest.raises(ImproperlyConfigured):
        _load(module_name, REQUIRED_ENV)
