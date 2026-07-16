"""Tests for revision discovery and metadata fetching Celery tasks."""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import requests
from django.utils import timezone

from wafer_space.projects import tasks_revisions
from wafer_space.projects.models import PrecheckImageRevision
from wafer_space.projects.tasks_revisions import _fetch_pdk_version
from wafer_space.projects.tasks_revisions import _is_semver_tag
from wafer_space.projects.tasks_revisions import _resolve_version_from_tags
from wafer_space.projects.tasks_revisions import do_revision_fetch
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

    def test_ignores_digest_with_exhausted_fetch_attempts(self):
        """Task stops requeueing digests that hit the fetch-attempt cap."""
        digest = "sha256:gaveupdigest1234567890123456789012345678901234567890123"
        PrecheckImageRevision.objects.create(
            digest=digest,
            metadata_fetch_attempts=tasks_revisions.MAX_METADATA_FETCH_ATTEMPTS,
        )
        ManufacturabilityCheckFactory(docker_image_digest=digest)

        with patch(
            "wafer_space.projects.tasks_revisions.do_revision_fetch.delay"
        ) as mock_fetch:
            result = revisions_needs_fetching()

        assert result["new_revisions_queued"] == 0
        mock_fetch.assert_not_called()


def _metadata(**overrides) -> dict:
    """Metadata dict shaped like _fetch_ghcr_metadata's return value."""
    metadata = {
        "image_created_at": timezone.now(),
        "git_commit_sha": "59207bbebaf2f5e5bb5f3e9441199a71948b1fdc",
        "precheck_version": "1.7.2",
        "pdk_version": "1.0.604",
        "tool_versions": {"nix-eda": "6.24.0 @ ebee72ea7826"},
        "commit_message": "Merge pull request #46",
        "commit_date": timezone.now(),
    }
    metadata.update(overrides)
    return metadata


@pytest.mark.django_db
class TestDoRevisionFetch:
    """Tests for do_revision_fetch failure handling and partial saves."""

    DIGEST = "sha256:" + "a" * 64

    def test_saves_partial_metadata_when_pdk_version_missing(self):
        """Missing pdk_version saves everything else and marks fetched."""
        revision = PrecheckImageRevision.objects.create(digest=self.DIGEST)

        with patch(
            "wafer_space.projects.tasks_revisions._fetch_ghcr_metadata",
            return_value=_metadata(pdk_version=""),
        ):
            result = do_revision_fetch(self.DIGEST)

        revision.refresh_from_db()
        assert revision.metadata_fetched_at is not None
        assert revision.precheck_version == "1.7.2"
        assert revision.pdk_version == ""
        assert result["status"] == "partial"

    def test_success_saves_metadata_and_clears_last_error(self):
        """Full metadata saves normally and clears any recorded error."""
        revision = PrecheckImageRevision.objects.create(
            digest=self.DIGEST,
            metadata_fetch_last_error="old transient error",
        )

        with patch(
            "wafer_space.projects.tasks_revisions._fetch_ghcr_metadata",
            return_value=_metadata(),
        ):
            result = do_revision_fetch(self.DIGEST)

        revision.refresh_from_db()
        assert result["status"] == "success"
        assert revision.pdk_version == "1.0.604"
        assert revision.metadata_fetch_last_error == ""

    def test_request_exception_records_attempt_and_error(self):
        """Network failure records the attempt and error before retrying."""
        revision = PrecheckImageRevision.objects.create(digest=self.DIGEST)

        with (
            patch(
                "wafer_space.projects.tasks_revisions._fetch_ghcr_metadata",
                side_effect=requests.RequestException("ghcr unreachable"),
            ),
            pytest.raises(requests.RequestException),
        ):
            do_revision_fetch(self.DIGEST)

        revision.refresh_from_db()
        assert revision.metadata_fetch_attempts == 1
        assert "ghcr unreachable" in revision.metadata_fetch_last_error
        assert revision.metadata_fetched_at is None

    def test_gives_up_at_attempt_cap_without_retrying(self):
        """At the attempt cap the task returns an error instead of retrying."""
        revision = PrecheckImageRevision.objects.create(
            digest=self.DIGEST,
            metadata_fetch_attempts=(tasks_revisions.MAX_METADATA_FETCH_ATTEMPTS - 1),
        )

        with patch(
            "wafer_space.projects.tasks_revisions._fetch_ghcr_metadata",
            side_effect=requests.RequestException("still unreachable"),
        ):
            result = do_revision_fetch(self.DIGEST)

        revision.refresh_from_db()
        assert result["gave_up"] is True
        assert (
            revision.metadata_fetch_attempts
            == tasks_revisions.MAX_METADATA_FETCH_ATTEMPTS
        )
        assert revision.metadata_fetched_at is None


class TestFetchPdkVersion:
    """Tests for _fetch_pdk_version Makefile resolution."""

    MAKEFILE_WITH_TAG = "PDK ?= gf180mcuD\nPDK_TAG ?= 1.6.6\n"
    MAKEFILE_WITH_COMMIT = (
        "PDK ?= gf180mcuD\nPDK_COMMIT ?= d658698bd8bcf4e05fc7b5991a701247ba0d744c\n"
    )
    MAKEFILE_WITHOUT_PDK = "PDK ?= gf180mcuD\nall: build\n"

    def _response(self, text: str, status_code: int = 200) -> MagicMock:
        resp = MagicMock()
        resp.status_code = status_code
        resp.text = text
        return resp

    @patch("wafer_space.projects.tasks_revisions.requests.get")
    def test_resolves_pdk_tag_from_makefile(self, mock_get):
        """PDK_TAG in the Makefile is returned directly."""
        mock_get.return_value = self._response(self.MAKEFILE_WITH_TAG)

        assert _fetch_pdk_version("abc123") == "1.6.6"

    @patch("wafer_space.projects.tasks_revisions.requests.get")
    def test_resolves_pdk_commit_via_open_pdks_version(self, mock_get):
        """PDK_COMMIT is resolved to open_pdks' VERSION at that commit."""

        def get_side_effect(url, **kwargs):
            if url.endswith("/Makefile"):
                return self._response(self.MAKEFILE_WITH_COMMIT)
            if "open_pdks" in url and url.endswith("/VERSION"):
                return self._response("1.0.604\n")
            return self._response("", status_code=404)

        mock_get.side_effect = get_side_effect

        assert _fetch_pdk_version("abc123") == "1.0.604"

    @patch("wafer_space.projects.tasks_revisions.requests.get")
    def test_returns_empty_when_makefile_has_no_pdk_pinning(self, mock_get):
        """Makefile with neither PDK_TAG nor PDK_COMMIT yields empty string."""
        mock_get.return_value = self._response(self.MAKEFILE_WITHOUT_PDK)

        assert _fetch_pdk_version("abc123") == ""

    @patch("wafer_space.projects.tasks_revisions.requests.get")
    def test_rejects_open_pdks_content_that_is_not_a_version(self, mock_get):
        """Garbage VERSION content (e.g. an error page) is not a version."""

        def get_side_effect(url, **kwargs):
            if url.endswith("/Makefile"):
                return self._response(self.MAKEFILE_WITH_COMMIT)
            return self._response("404: Not Found")

        mock_get.side_effect = get_side_effect

        assert _fetch_pdk_version("abc123") == ""


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
        tags_resp.headers = {}
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

    @patch("wafer_space.projects.tasks_revisions.requests.head")
    @patch("wafer_space.projects.tasks_revisions.requests.get")
    def test_follows_tags_list_pagination(self, mock_get, mock_head):
        """Finds a matching tag beyond the first /tags/list page (#295).

        GHCR returns tags oldest-first in pages linked via the Link header,
        so newly pushed tags are only reachable by following pagination.
        """
        target_digest = "sha256:abc123"

        token_resp = MagicMock()
        token_resp.json.return_value = {"token": "fake-token"}

        page1 = MagicMock()
        page1.json.return_value = {"tags": ["main", "latest"]}
        page1.headers = {
            "Link": (
                "</v2/wafer-space/gf180mcu-precheck/tags/list"
                '?last=latest&n=100>; rel="next"'
            ),
        }

        page2 = MagicMock()
        page2.json.return_value = {"tags": ["1.7.0-4-g71a7b0f"]}
        page2.headers = {}

        mock_get.side_effect = [token_resp, page1, page2]

        def head_side_effect(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {"Docker-Content-Digest": target_digest}
            return resp

        mock_head.side_effect = head_side_effect

        result = _resolve_version_from_tags(target_digest)

        assert result == "1.7.0-4-g71a7b0f"
