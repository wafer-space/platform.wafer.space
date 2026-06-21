"""Tests for the env-driven ALLOWED_HOSTS contract (issue #267).

prod and stage must read ``ALLOWED_HOSTS`` from the ``DJANGO_ALLOWED_HOSTS``
environment variable and fail fast when it is missing *or* empty, rather than
silently booting with an unusable allowlist that rejects every request at
runtime. The shared logic lives in ``config.settings.base.required_host_list``.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured

from config.settings.base import required_host_list

VAR = "DJANGO_ALLOWED_HOSTS"


def test_parses_comma_separated_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    """A comma-separated value is parsed into a list of hostnames."""
    monkeypatch.setenv(VAR, "example.com,foo.example.com")

    assert required_host_list(VAR) == ["example.com", "foo.example.com"]


def test_strips_surrounding_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whitespace around entries is trimmed."""
    monkeypatch.setenv(VAR, "example.com, foo.example.com")

    assert required_host_list(VAR) == ["example.com", "foo.example.com"]


def test_missing_variable_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unset variable fails fast at import time."""
    monkeypatch.delenv(VAR, raising=False)

    with pytest.raises(ImproperlyConfigured):
        required_host_list(VAR)


@pytest.mark.parametrize("value", ["", "   ", ",", " , "])
def test_blank_value_raises(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """An empty / whitespace-only / comma-only value fails fast too."""
    monkeypatch.setenv(VAR, value)

    with pytest.raises(ImproperlyConfigured):
        required_host_list(VAR)
