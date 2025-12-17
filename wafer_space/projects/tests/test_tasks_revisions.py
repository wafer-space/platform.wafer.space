"""Tests for revision discovery and metadata fetching Celery tasks."""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import requests
from django.utils import timezone

from wafer_space.projects.models import PrecheckImageRevision
from wafer_space.projects.tasks_revisions import _is_semver_tag
from wafer_space.projects.tasks_revisions import _resolve_version_from_tags
from wafer_space.projects.tasks_revisions import revisions_needs_fetching
from wafer_space.projects.tests.factories import ManufacturabilityCheckFactory


@pytest.mark.django_db
class TestRevisionsNeedsFetching:
    """Tests for revisions_needs_fetching task."""

    def test_discovers_new_digest(self):
        """Task discovers digest not in PrecheckImageRevision."""
        ManufacturabilityCheckFactory(
            docker_image_digest="sha256:newdigest123456789012345678901234567890123456789012345678"
        )

        with patch(
            "wafer_space.projects.tasks_revisions.do_revision_fetch.delay"
        ) as mock_fetch:
            result = revisions_needs_fetching()

        assert result["new_revisions_queued"] == 1
        assert PrecheckImageRevision.objects.filter(
            digest="sha256:newdigest123456789012345678901234567890123456789012345678"
        ).exists()
        mock_fetch.assert_called_once()

    def test_ignores_fetched_digest(self):
        """Task ignores digest with metadata already fetched."""
        digest = "sha256:knowndigest12345678901234567890123456789012345678901234567"
        PrecheckImageRevision.objects.create(
            digest=digest,
            metadata_fetched_at=timezone.now(),
        )
        ManufacturabilityCheckFactory(docker_image_digest=digest)

        with patch(
            "wafer_space.projects.tasks_revisions.do_revision_fetch.delay"
        ) as mock_fetch:
            result = revisions_needs_fetching()

        assert result["new_revisions_queued"] == 0
        mock_fetch.assert_not_called()

    def test_queues_unfetched_digest(self):
        """Task queues fetch for digest with stub record but no metadata."""
        digest = "sha256:unfetcheddig12345678901234567890123456789012345678901234"
        PrecheckImageRevision.objects.create(digest=digest)  # No metadata_fetched_at
        ManufacturabilityCheckFactory(docker_image_digest=digest)

        with patch(
            "wafer_space.projects.tasks_revisions.do_revision_fetch.delay"
        ) as mock_fetch:
            result = revisions_needs_fetching()

        assert result["new_revisions_queued"] == 1
        mock_fetch.assert_called_once()

    def test_ignores_empty_digest(self):
        """Task ignores checks with empty digest."""
        ManufacturabilityCheckFactory(docker_image_digest="")

        with patch(
            "wafer_space.projects.tasks_revisions.do_revision_fetch.delay"
        ) as mock_fetch:
            result = revisions_needs_fetching()

        assert result["new_revisions_queued"] == 0
        mock_fetch.assert_not_called()


class TestIsSemverTag:
    """Tests for _is_semver_tag helper function."""

    def test_matches_simple_semver(self):
        """Matches basic semver like 1.5.2."""
        assert _is_semver_tag("1.5.2") is True
        assert _is_semver_tag("0.0.1") is True
        assert _is_semver_tag("10.20.30") is True

    def test_matches_semver_with_suffix(self):
        """Matches semver with git-describe suffix like 1.5.2-2-gf5c1b34."""
        assert _is_semver_tag("1.5.2-2-gf5c1b34") is True
        assert _is_semver_tag("1.0.0-alpha") is True
        assert _is_semver_tag("2.0.0-rc.1") is True

    def test_matches_v_prefix(self):
        """Matches semver with v prefix like v1.0.0."""
        assert _is_semver_tag("v1.0.0") is True
        assert _is_semver_tag("v0.1.0-beta") is True

    def test_rejects_branch_names(self):
        """Rejects branch-style names."""
        assert _is_semver_tag("main") is False
        assert _is_semver_tag("main-f5c1b34") is False
        assert _is_semver_tag("latest") is False
        assert _is_semver_tag("master") is False
        assert _is_semver_tag("develop") is False

    def test_rejects_commit_hashes(self):
        """Rejects bare commit hashes."""
        assert _is_semver_tag("f5c1b34") is False
        assert _is_semver_tag("abc123def") is False


class TestResolveVersionFromTags:
    """Tests for _resolve_version_from_tags helper function."""

    def _mock_ghcr_responses(self, tags: list[str], digest_map: dict[str, str]):
        """Create mock responses for GHCR API calls.

        Args:
            tags: List of available tags
            digest_map: Map of tag -> digest for HEAD requests
        """
        mock_responses = []

        # Token response
        token_resp = MagicMock()
        token_resp.json.return_value = {"token": "fake-token"}
        token_resp.raise_for_status = MagicMock()
        mock_responses.append(token_resp)

        # Tags list response
        tags_resp = MagicMock()
        tags_resp.json.return_value = {"tags": tags}
        tags_resp.raise_for_status = MagicMock()
        mock_responses.append(tags_resp)

        return mock_responses, digest_map

    @patch("wafer_space.projects.tasks_revisions.requests.head")
    @patch("wafer_space.projects.tasks_revisions.requests.get")
    def test_returns_semver_tag_ignores_branch_names(self, mock_get, mock_head):
        """Returns semver tag, ignoring branch-style names entirely."""
        target_digest = "sha256:abc123"
        tags = ["main", "main-f5c1b34", "1.5.2-2-gf5c1b34", "latest"]
        digest_map = dict.fromkeys(tags, target_digest)

        mock_responses, _ = self._mock_ghcr_responses(tags, digest_map)
        mock_get.side_effect = mock_responses

        def head_side_effect(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            tag = url.split("/manifests/")[-1]
            resp.headers = {"Docker-Content-Digest": digest_map.get(tag, "other")}
            return resp

        mock_head.side_effect = head_side_effect

        result = _resolve_version_from_tags(target_digest)

        # Should return 1.5.2-2-gf5c1b34 (only semver tag)
        assert result == "1.5.2-2-gf5c1b34"

    @patch("wafer_space.projects.tasks_revisions.requests.head")
    @patch("wafer_space.projects.tasks_revisions.requests.get")
    def test_returns_empty_when_only_branch_tags(self, mock_get, mock_head):
        """Returns empty string when only branch-style tags match."""
        target_digest = "sha256:abc123"
        tags = ["main", "main-f5c1b34", "latest"]
        digest_map = dict.fromkeys(tags, target_digest)

        mock_responses, _ = self._mock_ghcr_responses(tags, digest_map)
        mock_get.side_effect = mock_responses

        def head_side_effect(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            tag = url.split("/manifests/")[-1]
            resp.headers = {"Docker-Content-Digest": digest_map.get(tag, "other")}
            return resp

        mock_head.side_effect = head_side_effect

        result = _resolve_version_from_tags(target_digest)

        # No semver tags match, so return empty
        assert result == ""

    @patch("wafer_space.projects.tasks_revisions.requests.head")
    @patch("wafer_space.projects.tasks_revisions.requests.get")
    def test_returns_empty_when_no_matching_digest(self, mock_get, mock_head):
        """Returns empty string when no tags match the digest."""
        target_digest = "sha256:notfound"
        tags = ["main", "1.5.2"]

        mock_responses, _ = self._mock_ghcr_responses(tags, {})
        mock_get.side_effect = mock_responses

        def head_side_effect(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {"Docker-Content-Digest": "sha256:different"}
            return resp

        mock_head.side_effect = head_side_effect

        result = _resolve_version_from_tags(target_digest)

        assert result == ""

    @patch("wafer_space.projects.tasks_revisions.requests.get")
    def test_returns_empty_on_request_exception(self, mock_get):
        """Returns empty string when GHCR request fails."""
        mock_get.side_effect = requests.RequestException("Network error")

        result = _resolve_version_from_tags("sha256:any")

        assert result == ""

    @patch("wafer_space.projects.tasks_revisions.requests.head")
    @patch("wafer_space.projects.tasks_revisions.requests.get")
    def test_returns_first_sorted_semver(self, mock_get, mock_head):
        """Returns first semver tag when sorted alphabetically."""
        target_digest = "sha256:abc123"
        tags = ["2.0.0", "1.5.2", "1.5.2-2-gf5c1b34"]
        digest_map = dict.fromkeys(tags, target_digest)

        mock_responses, _ = self._mock_ghcr_responses(tags, digest_map)
        mock_get.side_effect = mock_responses

        def head_side_effect(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            tag = url.split("/manifests/")[-1]
            resp.headers = {"Docker-Content-Digest": digest_map.get(tag, "other")}
            return resp

        mock_head.side_effect = head_side_effect

        result = _resolve_version_from_tags(target_digest)

        # Should return 1.5.2 (first alphabetically)
        assert result == "1.5.2"
