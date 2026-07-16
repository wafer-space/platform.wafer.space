"""Regression tests for the one_active_file_per_project submission race.

Production incident (2026-07-15 17:24 UTC, issue #310): two overlapping
POSTs to /projects/<pk>/submit-url/ both read the project's active-file
state before either transaction committed, so both tried to INSERT a
ProjectFile with is_active=True and the loser crashed with:

    IntegrityError: duplicate key value violates unique constraint
    "one_active_file_per_project"

These tests deterministically replay the losing request's database
interleaving by injecting the winning request's committed insert between
the loser's read of the active-file state (_handle_file_replacement) and
its insert (_create_project_file). The service must absorb the conflict
by re-reading and retrying (last writer wins), and the view must degrade
gracefully if a conflict still escapes.
"""

from __future__ import annotations

from unittest.mock import Mock
from unittest.mock import patch

from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from wafer_space.projects.models import ProjectFile
from wafer_space.projects.services import ProjectFileService
from wafer_space.projects.tests.factories import ProjectFactory
from wafer_space.projects.tests.factories import ProjectFileFactory
from wafer_space.users.tests.factories import UserFactory

ONE_MB = 1024 * 1024

# Rows left behind by the simulated race: the injected competitor row plus
# the winning submission (plus the original file in the replacement case).
ROWS_AFTER_FIRST_SUBMISSION_RACE = 2
ROWS_AFTER_REPLACEMENT_RACE = 3

REPLACEMENT_HOOK = (
    "wafer_space.projects.services.file_service"
    ".ProjectFileService._handle_file_replacement"
)

VALIDATION_RESULT = {
    "file_size": ONE_MB,
    "content_type": "application/octet-stream",
    "etag": '"abc123"',
    "supports_range": True,
}


def make_racing_replacement_hook():
    """Build a replacement-step stand-in that simulates a concurrent winner.

    Mirrors _handle_file_replacement's database effect (deactivate the
    active file), then commits a competing active file exactly once —
    replaying a concurrent request whose transaction commits after this
    request read the active-file state but before it inserts.
    """
    state = {"injected": False}

    def replacement(project):
        ProjectFile.objects.filter(project=project, is_active=True).update(
            is_active=False,
        )
        if not state["injected"]:
            state["injected"] = True
            ProjectFileFactory(project=project, is_active=True)

    return replacement


class ConcurrentSubmissionRaceTest(TestCase):
    """The service must survive the interleaving that caused the 500."""

    def setUp(self):
        self.project = ProjectFactory()

    @patch("wafer_space.projects.tasks.download_project_file.delay")
    @patch("wafer_space.projects.services.URLValidator.validate_url")
    def test_race_on_first_submission(self, mock_validate, mock_task):
        """Two first-ever submissions: the later one retries and wins."""
        mock_validate.return_value = VALIDATION_RESULT
        mock_task.return_value = Mock(id="task-123")

        with patch(
            REPLACEMENT_HOOK,
            side_effect=make_racing_replacement_hook(),
        ):
            project_file, _metadata = ProjectFileService.submit_file_from_url(
                project=self.project,
                url="https://example.com/design.gds",
            )

        active = ProjectFile.objects.filter(project=self.project, is_active=True)
        assert list(active) == [project_file]
        assert (
            ProjectFile.objects.filter(project=self.project).count()
            == ROWS_AFTER_FIRST_SUBMISSION_RACE
        )
        mock_task.assert_called_once()

    @patch("wafer_space.projects.tasks.download_project_file.delay")
    @patch("wafer_space.projects.services.URLValidator.validate_url")
    def test_race_on_replacement_submission(self, mock_validate, mock_task):
        """Same race while replacing an existing active file."""
        mock_validate.return_value = VALIDATION_RESULT
        mock_task.return_value = Mock(id="task-123")
        old_file = ProjectFileFactory(project=self.project, is_active=True)

        with patch(
            REPLACEMENT_HOOK,
            side_effect=make_racing_replacement_hook(),
        ):
            project_file, _metadata = ProjectFileService.submit_file_from_url(
                project=self.project,
                url="https://example.com/design.gds",
            )

        old_file.refresh_from_db()
        assert old_file.is_active is False
        active = ProjectFile.objects.filter(project=self.project, is_active=True)
        assert list(active) == [project_file]
        assert (
            ProjectFile.objects.filter(project=self.project).count()
            == ROWS_AFTER_REPLACEMENT_RACE
        )
        mock_task.assert_called_once()


class SubmitURLViewConflictFallbackTest(TestCase):
    """If a conflict still escapes the service, the view must not 500."""

    def setUp(self):
        self.user = UserFactory()
        self.project = ProjectFactory(user=self.user)
        self.client.force_login(self.user)

    def test_integrity_error_shows_friendly_message(self):
        url = reverse("projects:submit_url", kwargs={"pk": self.project.pk})
        error = IntegrityError(
            "duplicate key value violates unique constraint "
            '"one_active_file_per_project"',
        )
        with patch.object(
            ProjectFileService,
            "submit_file_from_url",
            side_effect=error,
        ):
            response = self.client.post(
                url,
                {
                    "url": "https://example.com/design.gds",
                    "expected_hash_md5": "",
                    "expected_hash_sha1": "",
                    "expected_hash_sha256": "a" * 64,
                },
            )

        detail_url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        self.assertRedirects(response, detail_url, fetch_redirect_response=False)
        messages = [str(m) for m in self.client.get(detail_url).context["messages"]]
        assert any("another submission" in m.lower() for m in messages)
