"""Reproduction tests for the one_active_file_per_project IntegrityError.

Production incident (2026-07-15 17:24 UTC): two overlapping POSTs to
/projects/<pk>/submit-url/ raced each other. Both requests read the
project's active-file state before either committed, so both tried to
INSERT a ProjectFile with is_active=True and the loser crashed with:

    IntegrityError: duplicate key value violates unique constraint
    "one_active_file_per_project"

These tests deterministically replay the database interleaving of the
losing request (request B) by injecting the winning request's (request A)
committed insert between B's read of the active-file state (Step 5,
_handle_file_replacement) and B's insert (Step 6, _create_project_file).

They PASS while the bug exists (they assert the current broken
behaviour). When the race is fixed, flip the assertions to expect
graceful handling instead of IntegrityError.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.db import IntegrityError
from django.test import TestCase

from wafer_space.projects.models import ProjectFile
from wafer_space.projects.services import ProjectFileService
from wafer_space.projects.tests.factories import ProjectFactory
from wafer_space.projects.tests.factories import ProjectFileFactory

ONE_MB = 1024 * 1024

REPLACEMENT_HOOK = (
    "wafer_space.projects.services.file_service"
    ".ProjectFileService._handle_file_replacement"
)

# PostgreSQL names the constraint; SQLite names the indexed column.
CONSTRAINT_ERROR = r"one_active_file_per_project|project_id"

VALIDATION_RESULT = {
    "file_size": ONE_MB,
    "content_type": "application/octet-stream",
    "etag": '"abc123"',
    "supports_range": True,
}


class ConcurrentSubmissionRaceTest(TestCase):
    """Replay the exact interleaving that caused the production 500."""

    def setUp(self):
        self.project = ProjectFactory()

    @patch("wafer_space.projects.tasks.download_project_file.delay")
    @patch("wafer_space.projects.services.URLValidator.validate_url")
    def test_race_on_first_submission(self, mock_validate, mock_task):
        """Two first-ever submissions: both see no active file, both insert.

        Request B reads the active-file state (none — so its replacement
        step is a no-op), then request A's transaction commits an active
        file, then B inserts its own "active" row -> IntegrityError.
        """
        mock_validate.return_value = VALIDATION_RESULT

        def competitor_commits_active_file(project):
            # B saw no active file, so B's replacement step did nothing.
            # A's request now commits its new active file.
            ProjectFileFactory(project=project, is_active=True)

        with (
            patch(REPLACEMENT_HOOK, side_effect=competitor_commits_active_file),
            pytest.raises(IntegrityError, match=CONSTRAINT_ERROR),
        ):
            ProjectFileService.submit_file_from_url(
                project=self.project,
                url="https://example.com/design.gds",
            )

        # The download task never started for the failed insert.
        mock_task.assert_not_called()
        assert (
            ProjectFile.objects.filter(project=self.project, is_active=True).count()
            == 1
        )

    @patch("wafer_space.projects.tasks.download_project_file.delay")
    @patch("wafer_space.projects.services.URLValidator.validate_url")
    def test_race_on_replacement_submission(self, mock_validate, mock_task):
        """Same race when both requests replace an existing active file."""
        mock_validate.return_value = VALIDATION_RESULT
        ProjectFileFactory(project=self.project, is_active=True)

        def deactivate_then_competitor_commits(project):
            # B's replacement step: deactivate the old active file.
            ProjectFile.objects.filter(project=project, is_active=True).update(
                is_active=False,
            )
            # A's request commits its replacement before B inserts.
            ProjectFileFactory(project=project, is_active=True)

        with (
            patch(REPLACEMENT_HOOK, side_effect=deactivate_then_competitor_commits),
            pytest.raises(IntegrityError, match=CONSTRAINT_ERROR),
        ):
            ProjectFileService.submit_file_from_url(
                project=self.project,
                url="https://example.com/design.gds",
            )

        mock_task.assert_not_called()
        assert (
            ProjectFile.objects.filter(project=self.project, is_active=True).count()
            == 1
        )
