"""A URL that serves a web page fails its download once, quietly (#463).

Before #463, a URL that returned an HTML page instead of a layout file
raised a plain ValueError: the download was retried three times against
the same page, and each failure was logged at ERROR, which emails
ADMINS. These tests pin down what happens now: one failed attempt, a
message that tells the user what to fix, one notification, a WARNING in
the log and no retry.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import Mock
from unittest.mock import patch

import pytest

from wafer_space.notifications.models import Notification
from wafer_space.projects.content_pipeline import download_dir_path
from wafer_space.projects.models import DownloadAttempt
from wafer_space.projects.models import FileProcessingError
from wafer_space.projects.models import ProjectFile
from wafer_space.projects.tasks_download import download_project_file
from wafer_space.projects.tests.factories import ProjectFactory

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.django_db

TASKS = "wafer_space.projects.tasks_download"

HTML_PAGE = b"<!DOCTYPE html><html><body>Sign in to continue</body></html>"

HTML_MESSAGE = (
    "Unsupported file type: text/html. The URL returned a web page, not a "
    "layout file. This usually means the link is a share or preview page "
    "rather than a direct download, it needs you to sign in, or it has "
    "expired. Please provide a direct download link to the GDS or OASIS file."
)


@pytest.fixture(autouse=True)
def media_root(settings, tmp_path: Path) -> Path:
    """Keep the download staging dir under tmp_path."""
    settings.MEDIA_ROOT = str(tmp_path / "media")
    return tmp_path


@pytest.fixture(params=["early-check", "post-download-check"])
def sniffing(request: pytest.FixtureRequest) -> Iterator[str]:
    """Run each test through both places the file type is checked.

    The early check reads the first bytes as they arrive. It is skipped
    for resumed downloads and base64-encoded sources, which leaves the
    check after the download ("Step 6") to reject the content.
    """
    if request.param == "early-check":
        yield request.param
        return
    with patch(f"{TASKS}._should_sniff_content", return_value=False):
        yield request.param


@pytest.fixture
def html_response() -> Iterator[Mock]:
    """Make every request for the file answer 200 with an HTML page."""

    def respond(*args: object, **kwargs: object) -> Mock:
        response = Mock()
        response.status_code = 200
        response.headers = {}
        response.iter_content.return_value = iter([HTML_PAGE])
        return response

    with patch(f"{TASKS}.requests.get", side_effect=respond) as get:
        yield get


def download() -> tuple[ProjectFile, dict[str, str]]:
    """Run download_project_file as Celery would, retries included."""
    project_file = ProjectFile.objects.create(
        project=ProjectFactory(),
        source_url="https://example.com/share/design",
        original_filename="design.gds",
        is_active=True,
    )

    result = download_project_file.apply(args=[str(project_file.project.id)]).result

    project_file.refresh_from_db()
    return project_file, result


@pytest.mark.usefixtures("sniffing")
def test_html_page_is_fetched_once(html_response: Mock) -> None:
    """No retry: the same page would come back each time."""
    download()

    assert html_response.call_count == 1


@pytest.mark.usefixtures("sniffing", "html_response")
def test_html_page_does_not_call_task_retry() -> None:
    """The task never asks Celery for a retry."""
    with patch.object(download_project_file, "retry") as retry:
        download()

    assert retry.call_count == 0


@pytest.mark.usefixtures("sniffing", "html_response")
def test_html_page_fails_the_one_attempt_with_the_message() -> None:
    """One attempt, failed, carrying the message; no PENDING retry attempt."""
    project_file, _result = download()

    attempts = list(
        project_file.download_attempts.values_list("status", "download_error"),
    )
    assert attempts == [(DownloadAttempt.Status.FAILED, HTML_MESSAGE)]


@pytest.mark.usefixtures("sniffing", "html_response")
def test_html_message_is_the_files_download_error() -> None:
    """The file shows as failed, with the message as its error."""
    project_file, result = download()

    assert (
        project_file.download_status,
        project_file.download_error,
        result,
    ) == (
        DownloadAttempt.Status.FAILED,
        HTML_MESSAGE,
        {"status": "failed", "message": HTML_MESSAGE},
    )


@pytest.mark.usefixtures("sniffing", "html_response")
def test_html_page_tells_the_user_in_one_notification() -> None:
    """The download-failed notification is the only one, and quotes it."""
    project_file, _result = download()

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
            f"Failed to download 'design.gds'. Error: {HTML_MESSAGE}",
        ),
    ]


@pytest.mark.usefixtures("sniffing", "html_response")
def test_html_page_is_recorded_as_one_processing_error() -> None:
    """The failure is recorded once, not once per place that saw it."""
    project_file, _result = download()

    errors = list(
        FileProcessingError.objects.filter(
            download_attempt__project_file=project_file,
        ).values_list("error_type", "error_message"),
    )
    assert errors == [
        (
            FileProcessingError.ErrorType.DOWNLOAD,
            f"Download failed: {HTML_MESSAGE}",
        ),
    ]


@pytest.mark.usefixtures("sniffing", "html_response")
def test_html_page_logs_nothing_at_error(caplog: pytest.LogCaptureFixture) -> None:
    """A user's bad link is not a platform fault: no ERROR, so no ADMINS email."""
    with caplog.at_level(logging.DEBUG):
        download()

    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []


@pytest.mark.usefixtures("sniffing", "html_response")
def test_html_page_logs_one_warning(caplog: pytest.LogCaptureFixture) -> None:
    """The warning names the project and carries the message."""
    with caplog.at_level(logging.DEBUG):
        project_file, _result = download()

    warnings = [
        r.getMessage()
        for r in caplog.records
        if r.levelno == logging.WARNING and r.name == TASKS
    ]
    expected = (
        "DOWNLOAD TASK FAILED - Unsupported file type for project "
        f"{project_file.project.id}: {HTML_MESSAGE}"
    )
    assert warnings == [expected]


@pytest.mark.usefixtures("sniffing", "html_response")
def test_html_page_leaves_no_staging_dir() -> None:
    """No retry is coming, so the downloaded page is removed."""
    project_file, _result = download()

    assert not download_dir_path(project_file.id).exists()


def test_post_download_check_is_what_rejects_when_sniffing_is_skipped(
    html_response: Mock,
) -> None:
    """With the early check skipped, the whole page is saved, then rejected.

    This guards the "post-download-check" runs above: were the early
    check still to run, they would pass without reaching Step 6.
    """
    with (
        patch(f"{TASKS}._should_sniff_content", return_value=False),
        patch(f"{TASKS}._validate_leading_bytes") as early_check,
    ):
        project_file, _result = download()

    assert (early_check.call_count, project_file.download_error) == (
        0,
        HTML_MESSAGE,
    )
