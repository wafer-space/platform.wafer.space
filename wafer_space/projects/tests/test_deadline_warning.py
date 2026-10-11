"""Warn owners near the GDS submission deadline (issue #347)."""

from __future__ import annotations

import datetime

import pytest
from django.urls import reverse
from django.utils import timezone

from wafer_space.projects.deadline_warning import URGENT
from wafer_space.projects.deadline_warning import WARNING
from wafer_space.projects.deadline_warning import deadline_warning
from wafer_space.projects.deadline_warning import deadline_warning_for
from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import Project
from wafer_space.shuttles.models import Shuttle
from wafer_space.users.tests.factories import UserFactory

from .factories import ManufacturabilityCheckFactory
from .factories import ProjectFactory
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
