"""A design with a broken cell hierarchy fails its download cleanly (#78).

Before #78, a circular cell reference made download_project_file raise
RecursionError: the attempt stayed "downloading", the user got no
message, ADMINS got a traceback, and the 60 s watchdog re-queued the
download to fail the same way. These tests pin down what happens now:
one failed attempt, a message that tells the user what to fix, no
ADMINS email and no retry.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from django.core import mail
from django.core.cache import cache

from wafer_space.core.log import RateLimitedAdminEmailHandler
from wafer_space.notifications.models import Notification
from wafer_space.projects.models import DownloadAttempt
from wafer_space.projects.models import ProjectFile
from wafer_space.projects.tasks_download import download_project_file
from wafer_space.projects.tasks_download import ensure_download_tasks_queued
from wafer_space.projects.tests.factories import ProjectFactory
from wafer_space.projects.tests.layout_helpers import DEEP_LEVELS
from wafer_space.projects.tests.layout_helpers import chain
from wafer_space.projects.tests.layout_helpers import write_layout

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from django.core.mail import EmailMessage

pytestmark = pytest.mark.django_db

TASKS = "wafer_space.projects.tasks_download"

CYCLE_MESSAGE = (
    "The design has a circular cell reference (A → B → A). "
    "Fix the circular reference in your layout and upload it again."
)


@pytest.fixture
def admin_mail() -> Iterator[list[EmailMessage]]:
    """Route wafer_space.* ERRORs to ADMINS email, as prod and stage LOGGING do."""
    cache.clear()
    handler = RateLimitedAdminEmailHandler()
    handler.setLevel(logging.ERROR)  # "level": "ERROR" in prod LOGGING
    app_logger = logging.getLogger("wafer_space")
    app_logger.addHandler(handler)
    yield mail.outbox
    app_logger.removeHandler(handler)
    cache.clear()


def download(tmp_path: Path, hierarchy: dict[str, list[str]]) -> ProjectFile:
    """Run download_project_file on a GDS with this hierarchy.

    Only the network transfer and the type sniffing are mocked; the file
    is a real GDS and the real top-cell extractor reads it.
    """
    layout = write_layout(tmp_path / "layout.gds", hierarchy)
    project = ProjectFactory()
    project_file = ProjectFile.objects.create(
        project=project,
        source_url="https://example.com/design.gds",
        original_filename="design.gds",
        is_active=True,
        download_task_id="download-task-id",
    )

    def write_gds(
        task: object,
        pf: ProjectFile,
        attempt: DownloadAttempt,
        temp_path: Path,
    ) -> tuple[str, str, str]:
        temp_path.write_bytes(layout.read_bytes())
        return ("md5", "sha1", "sha256")

    with (
        patch(f"{TASKS}._download_with_progress", side_effect=write_gds),
        patch(
            f"{TASKS}.detect_file_type_from_data",
            return_value=("application/octet-stream", ".gds"),
        ),
    ):
        download_project_file(str(project.id))

    project_file.refresh_from_db()
    return project_file


CYCLE = {"TOP": ["A"], "A": ["B"], "B": ["A"], "OTHER": []}


@pytest.fixture
def media_root(settings, tmp_path: Path) -> Path:
    """Keep the downloaded file and its staging dir under tmp_path."""
    settings.MEDIA_ROOT = str(tmp_path / "media")
    return tmp_path


def test_cycle_fails_the_one_attempt_with_the_message(media_root: Path) -> None:
    """One attempt, failed, carrying the message; no retry attempt."""
    project_file = download(media_root, CYCLE)

    attempts = list(
        project_file.download_attempts.values_list("status", "download_error"),
    )
    assert attempts == [(DownloadAttempt.Status.FAILED, CYCLE_MESSAGE)]


def test_cycle_message_is_the_files_download_error(media_root: Path) -> None:
    """The file shows as failed, with the message as its error."""
    project_file = download(media_root, CYCLE)

    assert (project_file.download_status, project_file.download_error) == (
        DownloadAttempt.Status.FAILED,
        CYCLE_MESSAGE,
    )


def test_cycle_tells_the_user_in_a_notification(media_root: Path) -> None:
    """The download-failed notification is the only one, and quotes it."""
    project_file = download(media_root, CYCLE)

    notifications = list(
        Notification.objects.filter(user=project_file.project.user).values_list(
            "notification_type",
            "title",
            "message",
        ),
    )
    assert notifications == [
        (
            Notification.Type.DOWNLOAD_FAILED,
            "Download Failed: design.gds",
            f"Failed to download 'design.gds'. Error: {CYCLE_MESSAGE}",
        ),
    ]


def test_cycle_leaves_no_top_cell(media_root: Path) -> None:
    """No top cell, so no manufacturability check can start on it."""
    project_file = download(media_root, CYCLE)

    assert project_file.top_cell == ""


def test_cycle_sends_admins_no_email(
    media_root: Path,
    admin_mail: list[EmailMessage],
) -> None:
    """A user's broken design is not a platform fault."""
    download(media_root, CYCLE)

    assert admin_mail == []


def test_watchdog_does_not_requeue_a_cycle_failure(media_root: Path) -> None:
    """The 60 s fallback leaves the failed attempt alone.

    The task is gone from Celery, as it would be after it finished; the
    watchdog would re-queue an attempt still marked "downloading".
    """
    project_file = download(media_root, CYCLE)

    with (
        patch(f"{TASKS}.is_download_task_actively_running", return_value=False),
        patch(f"{TASKS}.is_download_task_queued", return_value=False),
        patch(f"{TASKS}.download_project_file.delay") as delay,
    ):
        result = ensure_download_tasks_queued()

    statuses = list(project_file.download_attempts.values_list("status", flat=True))
    assert (delay.call_count, result["requeued"], statuses) == (
        0,
        0,
        [DownloadAttempt.Status.FAILED],
    )


@pytest.mark.parametrize(
    "hierarchy",
    [
        pytest.param({"TOP": ["A"], "A": ["A"]}, id="self-reference"),
        pytest.param({"A": ["B"], "B": ["A"]}, id="no-top-cell"),
    ],
)
def test_other_cycles_fail_the_download_too(
    media_root: Path,
    hierarchy: dict[str, list[str]],
) -> None:
    """A self-reference, and a cycle with no top cell, fail the same way."""
    project_file = download(media_root, hierarchy)

    assert project_file.download_error.startswith(
        "The design has a circular cell reference (",
    )


def test_2000_deep_design_downloads(media_root: Path) -> None:
    """Deep but acyclic, with a second top cell: it completes as before."""
    hierarchy = chain(DEEP_LEVELS + 1)
    hierarchy["OTHER"] = []

    project_file = download(media_root, hierarchy)

    assert (project_file.download_status, project_file.top_cell) == (
        DownloadAttempt.Status.COMPLETED,
        "C0",
    )
