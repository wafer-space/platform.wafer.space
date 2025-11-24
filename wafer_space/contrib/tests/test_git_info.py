"""Tests for git_info context processor."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from wafer_space.contrib.git_info import GITHUB_REPO_URL
from wafer_space.contrib.git_info import get_git_commit_hash
from wafer_space.contrib.git_info import git_info

if TYPE_CHECKING:
    from django.test import Client

# Git SHA hash lengths
GIT_HASH_FULL_LENGTH = 40
GIT_HASH_SHORT_LENGTH = 7


class TestGetGitCommitHash:
    """Tests for get_git_commit_hash function."""

    def setup_method(self) -> None:
        """Clear the LRU cache before each test."""
        get_git_commit_hash.cache_clear()

    def test_returns_commit_hash(self) -> None:
        """Test that get_git_commit_hash returns a valid 40-char hash."""
        result = get_git_commit_hash()

        # Should return a string (in a git repo)
        assert result is not None
        assert isinstance(result, str)
        # Git hash is 40 hex characters
        assert len(result) == GIT_HASH_FULL_LENGTH
        assert all(c in "0123456789abcdef" for c in result)

    def test_result_is_cached(self) -> None:
        """Test that the result is cached between calls."""
        result1 = get_git_commit_hash()
        result2 = get_git_commit_hash()

        assert result1 == result2
        # Check cache info to verify caching
        cache_info = get_git_commit_hash.cache_info()
        assert cache_info.hits >= 1


class TestGitInfoContextProcessor:
    """Tests for git_info context processor."""

    def setup_method(self) -> None:
        """Clear the LRU cache before each test."""
        get_git_commit_hash.cache_clear()

    def test_provides_git_info_in_context(self) -> None:
        """Test that context processor provides git commit information."""
        request = MagicMock()

        result = git_info(request)

        assert "GIT_COMMIT_HASH" in result
        assert "GIT_COMMIT_SHORT" in result
        assert "GIT_COMMIT_URL" in result

        # Verify values are set (we're in a git repo)
        commit_hash = result["GIT_COMMIT_HASH"]
        short_hash = result["GIT_COMMIT_SHORT"]
        commit_url = result["GIT_COMMIT_URL"]

        assert commit_hash is not None
        assert short_hash is not None
        assert commit_url is not None
        assert len(short_hash) == GIT_HASH_SHORT_LENGTH
        assert commit_url.startswith(GITHUB_REPO_URL)

    def test_short_hash_is_prefix_of_full_hash(self) -> None:
        """Test that short hash is the first 7 chars of full hash."""
        request = MagicMock()

        result = git_info(request)

        full_hash = result["GIT_COMMIT_HASH"]
        short_hash = result["GIT_COMMIT_SHORT"]

        assert full_hash is not None
        assert short_hash == full_hash[:7]

    def test_commit_url_contains_full_hash(self) -> None:
        """Test that commit URL contains the full hash."""
        request = MagicMock()

        result = git_info(request)

        full_hash = result["GIT_COMMIT_HASH"]
        commit_url = result["GIT_COMMIT_URL"]

        assert full_hash is not None
        assert commit_url is not None
        assert full_hash in commit_url
        assert commit_url == f"{GITHUB_REPO_URL}/commit/{full_hash}"

    @patch("wafer_space.contrib.git_info.get_git_commit_hash")
    def test_returns_none_values_when_hash_unavailable(
        self,
        mock_get_hash: MagicMock,
    ) -> None:
        """Test that context processor returns None values when hash unavailable."""
        mock_get_hash.return_value = None
        request = MagicMock()

        result = git_info(request)

        assert result["GIT_COMMIT_HASH"] is None
        assert result["GIT_COMMIT_SHORT"] is None
        assert result["GIT_COMMIT_URL"] is None


@pytest.mark.django_db
class TestGitInfoIntegration:
    """Integration tests for git info in templates."""

    def setup_method(self) -> None:
        """Clear the LRU cache before each test."""
        get_git_commit_hash.cache_clear()

    def test_git_info_available_in_template_context(
        self,
        client: Client,
    ) -> None:
        """Test that git info is available in template rendering."""
        response = client.get("/")

        # Check meta tags are present in the response
        content = response.content.decode()
        assert 'name="version"' in content
        assert 'name="revision"' in content

        # Check footer link is present
        assert GITHUB_REPO_URL in content
