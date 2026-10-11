"""Warn owners near the GDS submission deadline (issue #347)."""

from __future__ import annotations

import datetime

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from wafer_space.projects.deadline_warning import URGENT
from wafer_space.projects.deadline_warning import WARNING
from wafer_space.projects.deadline_warning import deadline_warning
from wafer_space.projects.deadline_warning import deadline_warning_for
from wafer_space.projects.deadline_warning import next_step
from wafer_space.projects.models import DownloadAttempt
from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.shuttles.models import Shuttle
from wafer_space.users.tests.factories import UserFactory

from .factories import ManufacturabilityCheckFactory
from .factories import ProjectFactory
from .factories import ProjectFileFactory
from .factories import make_downloaded_file

pytestmark = pytest.mark.django_db


def project_due_in(
    delta: datetime.timedelta | None,
    *,
    status: str = Shuttle.Status.OPEN,
    name: str = "G893",
) -> Project:
    shuttle = Shuttle.objects.create(
        name=name,
        description="Run",
        status=status,
        submission_deadline=None if delta is None else timezone.now() + delta,
    )
    return ProjectFactory(shuttle=shuttle)


def submit_with_verdict(project: Project, *, manufacturable: bool) -> None:
    revision = make_downloaded_file(project)
    ManufacturabilityCheckFactory(
        project=project,
        project_file=revision,
        status=ManufacturabilityCheck.Status.FINISHED,
        is_manufacturable=manufacturable,
    )
    Project.objects.filter(pk=project.pk).update(submitted_file=revision)


def reload(project: Project) -> Project:
    return Project.objects.select_related("shuttle").get(pk=project.pk)


def test_warning_within_fourteen_days() -> None:
    project = project_due_in(datetime.timedelta(days=13, hours=23))
    assert deadline_warning(project) == WARNING


def test_urgent_within_three_days() -> None:
    project = project_due_in(datetime.timedelta(days=2))
    assert deadline_warning(project) == URGENT


def test_no_warning_more_than_fourteen_days_away() -> None:
    project = project_due_in(datetime.timedelta(days=14, hours=1))
    assert deadline_warning(project) is None


def test_no_warning_after_deadline() -> None:
    project = project_due_in(-datetime.timedelta(hours=1))
    assert deadline_warning(project) is None


def test_no_warning_without_deadline() -> None:
    assert deadline_warning(project_due_in(None)) is None


def test_no_warning_on_closed_shuttle() -> None:
    project = project_due_in(
        datetime.timedelta(days=2),
        status=Shuttle.Status.IN_PRODUCTION,
    )
    assert deadline_warning(project) is None


def test_no_warning_without_shuttle() -> None:
    assert deadline_warning(ProjectFactory(shuttle=None)) is None


def test_no_warning_when_archived() -> None:
    project = project_due_in(datetime.timedelta(days=2))
    Project.objects.filter(pk=project.pk).update(archived_at=timezone.now())
    assert deadline_warning(reload(project)) is None


def test_no_warning_when_submitted_and_passing() -> None:
    project = project_due_in(datetime.timedelta(days=2))
    submit_with_verdict(project, manufacturable=True)
    assert deadline_warning(reload(project)) is None


def test_warned_again_when_submitted_revision_now_fails() -> None:
    """Coordinator: "Submitted, now failing" (#321) needs the owner to act."""
    project = project_due_in(datetime.timedelta(days=2))
    submit_with_verdict(project, manufacturable=False)
    assert deadline_warning(reload(project)) == URGENT


def test_list_annotation_gives_same_answer_without_queries(
    django_assert_num_queries,
) -> None:
    """On the list the submitted verdict comes from #321's annotation."""
    project = project_due_in(datetime.timedelta(days=2))
    submit_with_verdict(project, manufacturable=False)
    loaded = reload(project)
    with django_assert_num_queries(0):
        assert deadline_warning_for(loaded, submitted_verdict=False) == URGENT


def detail(client, user, project: Project) -> str:
    client.force_login(user)
    return client.get(reverse("projects:detail", args=[project.pk])).content.decode()


def test_project_page_shows_urgent_banner_with_next_step(client) -> None:
    project = project_due_in(datetime.timedelta(days=2))
    html = detail(client, project.user, project)
    assert 'data-deadline-warning="urgent"' in html
    assert "no file submitted for manufacturing yet" in html
    assert "Submit a file URL" in html
    assert "data-countdown=" in html


def test_staff_see_the_banner_too(client) -> None:
    project = project_due_in(datetime.timedelta(days=10))
    html = detail(client, UserFactory(is_staff=True), project)
    assert 'data-deadline-warning="warning"' in html


def test_banner_names_failing_submission(client) -> None:
    project = project_due_in(datetime.timedelta(days=2))
    submit_with_verdict(project, manufacturable=False)
    html = detail(client, project.user, project)
    assert "submitted revision no longer passes" in html


def test_no_banner_far_from_deadline(client) -> None:
    project = project_due_in(datetime.timedelta(days=30))
    assert "data-deadline-warning" not in detail(client, project.user, project)


def test_projects_list_alert_lists_own_warned_projects(client) -> None:
    warned = project_due_in(datetime.timedelta(days=2))
    other_user_warned = project_due_in(datetime.timedelta(days=2), name="G894")
    client.force_login(warned.user)
    html = client.get(reverse("projects:list")).content.decode()
    assert "data-deadline-alert" in html
    assert f'data-warned-project="{warned.pk}"' in html
    assert f'data-warned-project="{other_user_warned.pk}"' not in html


def test_staff_list_alert_excludes_other_users_projects(client) -> None:
    project_due_in(datetime.timedelta(days=2))
    client.force_login(UserFactory(is_staff=True))
    html = client.get(reverse("projects:list")).content.decode()
    assert "data-deadline-alert" not in html


def test_no_list_alert_when_nothing_is_warned(client) -> None:
    project = project_due_in(datetime.timedelta(days=30))
    client.force_login(project.user)
    html = client.get(reverse("projects:list")).content.decode()
    assert "data-deadline-alert" not in html


def with_revision(
    project: Project,
    *,
    download: str | None = DownloadAttempt.Status.COMPLETED,
    check_status: str | None = None,
    manufacturable: bool | None = None,
) -> ProjectFile:
    """Give the project an active revision in a chosen state."""
    revision = ProjectFileFactory(
        project=project,
        is_active=True,
        download_task_id="task",
        hash_verified=True,
    )
    if download is not None:
        DownloadAttempt.objects.create(
            project_file=revision,
            attempt_number=1,
            status=download,
        )
    if check_status is not None:
        ManufacturabilityCheckFactory(
            project=project,
            project_file=revision,
            status=check_status,
            is_manufacturable=manufacturable,
        )
    return revision


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ({"download": DownloadAttempt.Status.FAILED}, "download failed"),
        ({"download": DownloadAttempt.Status.DOWNLOADING}, "Wait for the file"),
        (
            {"check_status": ManufacturabilityCheck.Status.RUNNING},
            "Wait for the manufacturability check",
        ),
        (
            {"check_status": ManufacturabilityCheck.Status.ERROR},
            "ended with an error",
        ),
        (
            {
                "check_status": ManufacturabilityCheck.Status.FINISHED,
                "manufacturable": False,
            },
            "failed its manufacturability check",
        ),
        (
            {
                "check_status": ManufacturabilityCheck.Status.FINISHED,
                "manufacturable": True,
            },
            "Submit for Manufacturing",
        ),
    ],
)
def test_next_step_for_each_state(state, expected) -> None:
    project = project_due_in(datetime.timedelta(days=2))
    with_revision(project, **state)
    assert expected in next_step(reload(project))


def test_next_step_failing_submission_with_newer_passing_revision() -> None:
    project = project_due_in(datetime.timedelta(days=2))
    submit_with_verdict(project, manufacturable=False)
    ProjectFile.objects.filter(project=project).update(is_active=False)
    with_revision(
        project,
        check_status=ManufacturabilityCheck.Status.FINISHED,
        manufacturable=True,
    )
    assert "newer revision passed" in next_step(reload(project))


def test_list_alert_includes_submitted_now_failing(client) -> None:
    project = project_due_in(datetime.timedelta(days=2))
    submit_with_verdict(project, manufacturable=False)
    client.force_login(project.user)
    html = client.get(reverse("projects:list")).content.decode()
    assert f'data-warned-project="{project.pk}"' in html


def test_list_alert_query_count_does_not_grow_with_projects(client) -> None:
    owner = UserFactory()
    client.force_login(owner)

    def warned_projects(count: int, offset: int) -> None:
        for i in range(count):
            shuttle = Shuttle.objects.create(
                name=f"G8{50 + offset + i}",
                description="Run",
                status=Shuttle.Status.OPEN,
                submission_deadline=timezone.now() + datetime.timedelta(days=2),
            )
            ProjectFactory(user=owner, shuttle=shuttle)

    warned_projects(1, offset=0)
    with CaptureQueriesContext(connection) as one:
        client.get(reverse("projects:list"))
    warned_projects(4, offset=1)
    with CaptureQueriesContext(connection) as five:
        client.get(reverse("projects:list"))
    assert len(five) == len(one)
