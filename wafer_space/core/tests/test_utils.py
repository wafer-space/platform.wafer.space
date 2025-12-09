"""Tests for core utility functions."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from wafer_space.core.utils import is_production_environment


class TestIsProductionEnvironment:
    """Tests for is_production_environment function."""

    def test_returns_true_when_debug_is_false(self):
        """Production detected when DEBUG=False."""
        with patch("wafer_space.core.utils.settings") as mock_settings:
            mock_settings.DEBUG = False
            mock_settings.DATABASES = {"default": {"ENGINE": "sqlite3"}}

            assert is_production_environment() is True

    def test_returns_false_when_debug_true_and_sqlite(self):
        """Development detected with DEBUG=True and SQLite."""
        with (
            patch("wafer_space.core.utils.settings") as mock_settings,
            patch.dict("os.environ", {"DJANGO_SETTINGS_MODULE": "config.settings.dev"}),
        ):
            mock_settings.DEBUG = True
            mock_settings.DATABASES = {
                "default": {"ENGINE": "django.db.backends.sqlite3"}
            }

            assert is_production_environment() is False

    def test_returns_true_when_using_postgresql(self):
        """Production detected when using PostgreSQL database."""
        with (
            patch("wafer_space.core.utils.settings") as mock_settings,
            patch.dict("os.environ", {"DJANGO_SETTINGS_MODULE": "config.settings.dev"}),
        ):
            mock_settings.DEBUG = True
            mock_settings.DATABASES = {
                "default": {"ENGINE": "django.db.backends.postgresql"}
            }

            assert is_production_environment() is True

    def test_returns_true_when_using_postgres_engine(self):
        """Production detected when ENGINE contains 'postgres'."""
        with (
            patch("wafer_space.core.utils.settings") as mock_settings,
            patch.dict("os.environ", {"DJANGO_SETTINGS_MODULE": "config.settings.dev"}),
        ):
            mock_settings.DEBUG = True
            mock_settings.DATABASES = {
                "default": {"ENGINE": "django.db.backends.postgres"}
            }

            assert is_production_environment() is True

    @pytest.mark.parametrize(
        "settings_module",
        [
            "config.settings.prod",
            "config.settings.stage",
            "config.settings.production",
            "config.settings.staging",
            "myapp.settings.prod",
            "PROD_SETTINGS",
        ],
    )
    def test_returns_true_for_production_settings_modules(self, settings_module: str):
        """Production detected for various production settings module names."""
        with (
            patch("wafer_space.core.utils.settings") as mock_settings,
            patch.dict("os.environ", {"DJANGO_SETTINGS_MODULE": settings_module}),
        ):
            mock_settings.DEBUG = True
            mock_settings.DATABASES = {
                "default": {"ENGINE": "django.db.backends.sqlite3"}
            }

            assert is_production_environment() is True

    @pytest.mark.parametrize(
        "settings_module",
        [
            "config.settings.dev",
            "config.settings.pytest",
            "config.settings.local",
            "config.settings.test",
            "",
        ],
    )
    def test_returns_false_for_development_settings_modules(self, settings_module: str):
        """Development detected for non-production settings module names."""
        with (
            patch("wafer_space.core.utils.settings") as mock_settings,
            patch.dict("os.environ", {"DJANGO_SETTINGS_MODULE": settings_module}),
        ):
            mock_settings.DEBUG = True
            mock_settings.DATABASES = {
                "default": {"ENGINE": "django.db.backends.sqlite3"}
            }

            assert is_production_environment() is False

    def test_handles_missing_database_config(self):
        """Gracefully handles missing database configuration."""
        with (
            patch("wafer_space.core.utils.settings") as mock_settings,
            patch.dict("os.environ", {"DJANGO_SETTINGS_MODULE": "config.settings.dev"}),
        ):
            mock_settings.DEBUG = True
            mock_settings.DATABASES = {}

            assert is_production_environment() is False

    def test_handles_missing_engine_key(self):
        """Gracefully handles missing ENGINE key in database config."""
        with (
            patch("wafer_space.core.utils.settings") as mock_settings,
            patch.dict("os.environ", {"DJANGO_SETTINGS_MODULE": "config.settings.dev"}),
        ):
            mock_settings.DEBUG = True
            mock_settings.DATABASES = {"default": {}}

            assert is_production_environment() is False
