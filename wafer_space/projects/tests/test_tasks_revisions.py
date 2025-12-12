"""Tests for revision discovery and metadata fetching Celery tasks."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from wafer_space.projects.models import PrecheckImageRevision
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

    def test_ignores_known_digest(self):
        """Task ignores digest already in PrecheckImageRevision."""
        digest = "sha256:knowndigest12345678901234567890123456789012345678901234567"
        PrecheckImageRevision.objects.create(digest=digest)
        ManufacturabilityCheckFactory(docker_image_digest=digest)

        with patch(
            "wafer_space.projects.tasks_revisions.do_revision_fetch.delay"
        ) as mock_fetch:
            result = revisions_needs_fetching()

        assert result["new_revisions_queued"] == 0
        mock_fetch.assert_not_called()

    def test_ignores_empty_digest(self):
        """Task ignores checks with empty digest."""
        ManufacturabilityCheckFactory(docker_image_digest="")

        with patch(
            "wafer_space.projects.tasks_revisions.do_revision_fetch.delay"
        ) as mock_fetch:
            result = revisions_needs_fetching()

        assert result["new_revisions_queued"] == 0
        mock_fetch.assert_not_called()
