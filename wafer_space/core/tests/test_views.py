"""Tests for the /health/ liveness endpoint (issue #336).

The endpoint is referenced by the nginx config and deployment tooling but was
never implemented, so every probe 404s (and, before the nginx fix, produced
``DisallowedHost`` noise). It must be anonymously accessible, database-free
(so it stays up while the database is down) and uncacheable (so Cloudflare
never serves a stale "ok").
"""

from __future__ import annotations

from http import HTTPStatus

import pytest
from django.test import Client


@pytest.fixture
def client() -> Client:
    """Anonymous test client (no session, no database access)."""
    return Client()


def test_health_returns_200_ok(client: Client) -> None:
    """GET /health/ responds 200 with a plain-text "ok" body."""
    response = client.get("/health/")

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"ok"
    assert response["Content-Type"] == "text/plain"


def test_health_allows_head(client: Client) -> None:
    """HEAD /health/ responds 200 so uptime monitors can use HEAD probes."""
    response = client.head("/health/")

    assert response.status_code == HTTPStatus.OK


def test_health_rejects_post(client: Client) -> None:
    """POST /health/ responds 405; the endpoint is read-only."""
    response = client.post("/health/")

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED


def test_health_is_not_cacheable(client: Client) -> None:
    """The response forbids caching so probes always reach the app."""
    response = client.get("/health/")

    assert "no-cache" in response["Cache-Control"]
