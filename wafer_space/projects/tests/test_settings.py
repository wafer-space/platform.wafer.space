"""Tests for Docker server settings."""

from __future__ import annotations

from django.conf import settings


class TestDockerServersSettings:
    """Test DOCKER_SERVERS configuration."""

    def test_docker_servers_exists(self) -> None:
        """DOCKER_SERVERS setting exists."""
        assert hasattr(settings, "DOCKER_SERVERS")
        assert isinstance(settings.DOCKER_SERVERS, list)

    def test_docker_servers_has_required_keys(self) -> None:
        """Each server has id, url, max_concurrent, priority."""
        for server in settings.DOCKER_SERVERS:
            assert "id" in server
            assert "url" in server
            assert "max_concurrent" in server
            assert "priority" in server

    def test_docker_servers_sorted_by_priority(self) -> None:
        """Servers should be sorted by priority (lowest first)."""
        priorities = [s["priority"] for s in settings.DOCKER_SERVERS]
        assert priorities == sorted(priorities)
