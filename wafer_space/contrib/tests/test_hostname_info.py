"""Tests for hostname_info context processor."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from wafer_space.contrib.hostname_info import get_hostname
from wafer_space.contrib.hostname_info import hostname_info

if TYPE_CHECKING:
    from django.test import Client

# HTTP status codes
HTTP_OK = 200


def _get_hostname_from_command() -> str | None:
    """Get hostname using hostname -A command for test comparison."""
    try:
        result = subprocess.run(
            ["hostname", "-A"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None
    else:
        output = result.stdout.strip()
        return output if output else None


class TestGetHostname:
    """Tests for get_hostname function."""

    def setup_method(self) -> None:
        """Clear the LRU cache before each test."""
        get_hostname.cache_clear()

    def test_returns_hostname_string(self) -> None:
        """Test that get_hostname returns a string (may be None on some systems)."""
        result = get_hostname()

        # On systems where hostname -A works, we should get a string
        if result is not None:
            assert isinstance(result, str)
            assert len(result) > 0

    def test_returns_fqdn_from_hostname_command(self) -> None:
        """Test that get_hostname returns the FQDN from hostname -A."""
        result = get_hostname()
        expected = _get_hostname_from_command()

        # Both should match (either both None or both the same value)
        assert result == expected

    def test_result_is_cached(self) -> None:
        """Test that the result is cached between calls."""
        result1 = get_hostname()
        result2 = get_hostname()

        assert result1 == result2
        # Check cache info to verify caching
        cache_info = get_hostname.cache_info()
        assert cache_info.hits >= 1

    @patch("wafer_space.contrib.hostname_info.subprocess.run")
    def test_returns_none_on_command_failure(self, mock_run: MagicMock) -> None:
        """Test that get_hostname returns None when command fails."""
        get_hostname.cache_clear()
        mock_run.side_effect = subprocess.SubprocessError("Command failed")

        result = get_hostname()

        assert result is None

    @patch("wafer_space.contrib.hostname_info.subprocess.run")
    def test_returns_raw_output(self, mock_run: MagicMock) -> None:
        """Test that get_hostname returns raw output from hostname -A."""
        get_hostname.cache_clear()
        mock_result = MagicMock()
        mock_result.stdout = "server1.example.com server2.example.com "
        mock_run.return_value = mock_result

        result = get_hostname()

        # Should return the raw string, just stripped of leading/trailing whitespace
        assert result == "server1.example.com server2.example.com"


class TestHostnameInfoContextProcessor:
    """Tests for hostname_info context processor."""

    def setup_method(self) -> None:
        """Clear the LRU cache before each test."""
        get_hostname.cache_clear()

    def test_provides_hostname_in_context(self) -> None:
        """Test that context processor provides hostname information."""
        request = MagicMock()

        result = hostname_info(request)

        assert "SERVER_HOSTNAME" in result
        # Value may be None on systems where hostname -A doesn't work
        hostname = result["SERVER_HOSTNAME"]
        if hostname is not None:
            assert isinstance(hostname, str)
            assert len(hostname) > 0

    def test_hostname_matches_command_output(self) -> None:
        """Test that returned hostname matches hostname -A output."""
        request = MagicMock()

        result = hostname_info(request)
        expected = _get_hostname_from_command()

        assert result["SERVER_HOSTNAME"] == expected

    @patch("wafer_space.contrib.hostname_info.get_hostname")
    def test_uses_get_hostname_function(self, mock_get_hostname: MagicMock) -> None:
        """Test that context processor uses get_hostname function."""
        mock_get_hostname.return_value = "test-server-01.example.com"
        request = MagicMock()

        result = hostname_info(request)

        mock_get_hostname.assert_called_once()
        assert result["SERVER_HOSTNAME"] == "test-server-01.example.com"

    @patch("wafer_space.contrib.hostname_info.get_hostname")
    def test_returns_none_when_hostname_unavailable(
        self, mock_get_hostname: MagicMock
    ) -> None:
        """Test that context processor returns None when hostname unavailable."""
        mock_get_hostname.return_value = None
        request = MagicMock()

        result = hostname_info(request)

        assert result["SERVER_HOSTNAME"] is None


@pytest.mark.django_db
class TestHostnameInfoIntegration:
    """Integration tests for hostname info in templates."""

    def setup_method(self) -> None:
        """Clear the LRU cache before each test."""
        get_hostname.cache_clear()

    def test_hostname_available_in_template_context(
        self,
        client: Client,
    ) -> None:
        """Test that hostname is available in template rendering."""
        response = client.get("/")
        content = response.content.decode()

        # Get expected hostname from command
        hostname = _get_hostname_from_command()

        if hostname:
            # Check hostname is present in the response
            assert hostname in content
        else:
            # If hostname -A doesn't work, just verify page loads
            assert response.status_code == HTTP_OK
