"""Staff override for Submit for Manufacturing: model rules (issue #252)."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from wafer_space.projects.models import ARCHIVED_READ_ONLY_MESSAGE
from wafer_space.projects.models import SUBMIT_OVERRIDE_REASON_MIN_LENGTH
from wafer_space.projects.models import DownloadAttempt
from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.users.tests.factories import UserFactory

from .factories import ManufacturabilityCheckFactory
from .factories import ProjectFactory
from .factories import ProjectFileFactory

pytestmark = pytest.mark.django_db

REASON = "Precheck flags a false DRC error on the seal ring."


def add_checked_revision(
    project: Project,
    *,
    passed: bool = False,
    with_layout: bool = True,
    downloaded: bool = True,
    hash_verified: bool = True,
) -> ProjectFile:
    """Make a new active revision with a finished check (failing by default)."""
    ProjectFile.objects.filter(project=project, is_active=True).update(is_active=False)
    revision = ProjectFileFactory(
        project=project,
        is_active=True,
        download_task_id="task",
        hash_verified=hash_verified,
    )
    if downloaded:
        DownloadAttempt.objects.create(
            project_file=revision,
            attempt_number=1,
            status=DownloadAttempt.Status.COMPLETED,
        )
    check = ManufacturabilityCheckFactory(
        project=project,
        project_file=revision,
        status=ManufacturabilityCheck.Status.FINISHED,
        is_manufacturable=passed,
    )
    if with_layout:
        check.output_gds.save("out.oas", SimpleUploadedFile("out.oas", b"oas"))
    if passed:
        Project.objects.filter(pk=project.pk).update(
            status=Project.Status.MANUFACTURABLE
        )
    return revision


def make_failed_project(**kwargs: bool) -> Project:
    project = ProjectFactory()
    add_checked_revision(project, **kwargs)
    return Project.objects.get(pk=project.pk)


@pytest.fixture
def staff():
    return UserFactory(is_staff=True)


def test_staff_may_override_failed_project(staff) -> None:
    assert make_failed_project().can_override_submit(staff) == (True, "")


def test_owner_may_not_override() -> None:
    project = make_failed_project()
    allowed, reason = project.can_override_submit(project.user)
    assert allowed is False
    assert "Only staff" in reason


def test_archived_project_refused(staff) -> None:
    project = make_failed_project()
    Project.objects.filter(pk=project.pk).update(archived_at=timezone.now())
    project = Project.objects.get(pk=project.pk)
    assert project.can_override_submit(staff) == (False, ARCHIVED_READ_ONLY_MESSAGE)


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"downloaded": False}, "download is not completed"),
        ({"hash_verified": False}, "hash has not been verified"),
        ({"with_layout": False}, "no processed layout"),
    ],
)
def test_file_state_and_layout_still_required(staff, kwargs, expected) -> None:
    allowed, reason = make_failed_project(**kwargs).can_override_submit(staff)
    assert allowed is False
    assert expected in reason


def test_refused_without_finished_check(staff) -> None:
    project = make_failed_project()
    ManufacturabilityCheck.objects.filter(project=project).update(
        status=ManufacturabilityCheck.Status.RUNNING,
    )
    project = Project.objects.get(pk=project.pk)
    allowed, reason = project.can_override_submit(staff)
    assert allowed is False
    assert "No finished precheck" in reason


def test_refused_when_normal_submit_works(staff) -> None:
    allowed, reason = make_failed_project(passed=True).can_override_submit(staff)
    assert allowed is False
    assert "use Submit" in reason


def test_override_submit_records_submission(staff) -> None:
    project = make_failed_project()
    active = project.latest_file
    project.override_submit(staff, REASON)
    project.refresh_from_db()
    assert project.submitted_file == active
    assert project.submitted_at is not None
    assert project.status == Project.Status.SUBMITTED
    assert project.submission_override_by == staff
    assert project.submission_override_reason == REASON
    assert project.is_submission_override


@pytest.mark.parametrize(
    "reason",
    ["x" * (SUBMIT_OVERRIDE_REASON_MIN_LENGTH - 1), " " * 40, ""],
)
def test_short_or_blank_reason_rejected(staff, reason) -> None:
    project = make_failed_project()
    with pytest.raises(ValidationError):
        project.override_submit(staff, reason)
    project.refresh_from_db()
    assert project.submitted_file is None


def test_refused_override_raises_and_saves_nothing(staff) -> None:
    project = make_failed_project(with_layout=False)
    with pytest.raises(ValidationError, match="no processed layout"):
        project.override_submit(staff, REASON)
    project.refresh_from_db()
    assert project.submitted_file is None


def test_replaced_revision_detected(staff) -> None:
    project = make_failed_project()
    loaded = project.latest_file
    assert loaded is not None
    ProjectFile.objects.filter(pk=loaded.pk).update(is_active=False)
    ProjectFileFactory(project=project, is_active=True)
    with pytest.raises(ValidationError, match="replaced"):
        project.override_submit(staff, REASON)


def test_normal_submit_clears_override_and_history_keeps_it(staff) -> None:
    project = make_failed_project()
    project.override_submit(staff, REASON)
    add_checked_revision(project, passed=True)
    project = Project.objects.get(pk=project.pk)
    project.submit()
    project.refresh_from_db()
    assert project.submission_override_by is None
    assert project.submission_override_reason == ""
    reasons = set(project.history.values_list("submission_override_reason", flat=True))
    assert REASON in reasons


def test_refused_for_passing_revision_already_submitted(staff) -> None:
    """A passing, normally submitted revision is no override case."""
    project = make_failed_project(passed=True)
    project.submit()
    project = Project.objects.get(pk=project.pk)
    allowed, reason = project.can_override_submit(staff)
    assert allowed is False
    assert "passed its precheck" in reason


def test_refused_when_revision_already_submitted_by_override(staff) -> None:
    project = make_failed_project()
    project.override_submit(staff, REASON)
    project = Project.objects.get(pk=project.pk)
    allowed, reason = project.can_override_submit(staff)
    assert allowed is False
    assert "already submitted" in reason


def test_new_failing_revision_after_override_may_be_overridden(staff) -> None:
    """Rule 3: a newer revision may replace the submitted one."""
    project = make_failed_project()
    project.override_submit(staff, REASON)
    add_checked_revision(project)
    project = Project.objects.get(pk=project.pk)
    assert project.can_override_submit(staff) == (True, "")
