"""Staff override for Submit for Manufacturing: the view (issue #252)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from wafer_space.projects.models import ARCHIVED_READ_ONLY_MESSAGE
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectAccessLog
from wafer_space.shuttles.models import Shuttle
from wafer_space.users.tests.factories import UserFactory

from .constants import HTTP_FORBIDDEN
from .constants import HTTP_FOUND
from .constants import HTTP_METHOD_NOT_ALLOWED
from .test_models_submit_override import REASON
from .test_models_submit_override import make_failed_project

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def override_url(project: Project) -> str:
    return reverse("projects:submit_override", args=[project.pk])


@pytest.fixture
def staff_client(client: Client) -> Client:
    client.force_login(UserFactory(is_staff=True, username="overrider"))
    return client


def test_staff_override_submits_and_logs_reason(staff_client: Client) -> None:
    project = make_failed_project()
    response = staff_client.post(override_url(project), {"reason": REASON})
    assert response.status_code == HTTP_FOUND
    assert response["Location"] == reverse("projects:detail", args=[project.pk])
    project.refresh_from_db()
    assert project.submitted_file is not None
    assert project.submission_override_reason == REASON
    entries = ProjectAccessLog.objects.filter(
        project=project,
        action=ProjectAccessLog.Action.SUBMIT_OVERRIDE,
    )
    assert [(e.admin_user.username, e.details) for e in entries] == [
        ("overrider", REASON),
    ]


def test_owner_who_is_not_staff_gets_403(client: Client) -> None:
    project = make_failed_project()
    client.force_login(project.user)
    response = client.post(override_url(project), {"reason": REASON})
    assert response.status_code == HTTP_FORBIDDEN
    project.refresh_from_db()
    assert project.submitted_file is None


def test_stranger_gets_403(client: Client) -> None:
    project = make_failed_project()
    client.force_login(UserFactory())
    assert client.post(override_url(project), {"reason": REASON}).status_code == (
        HTTP_FORBIDDEN
    )


def test_get_not_allowed(staff_client: Client) -> None:
    project = make_failed_project()
    response = staff_client.get(override_url(project))
    assert response.status_code == HTTP_METHOD_NOT_ALLOWED


def test_short_reason_is_refused(staff_client: Client) -> None:
    project = make_failed_project()
    response = staff_client.post(
        override_url(project),
        {"reason": "too short"},
        follow=True,
    )
    assert "at least 20 characters" in response.content.decode()
    project.refresh_from_db()
    assert project.submitted_file is None
    assert not ProjectAccessLog.objects.filter(
        action=ProjectAccessLog.Action.SUBMIT_OVERRIDE,
    ).exists()


def test_refused_rule_shows_reason(staff_client: Client) -> None:
    project = make_failed_project(with_layout=False)
    response = staff_client.post(override_url(project), {"reason": REASON}, follow=True)
    assert "no processed layout" in response.content.decode()
    project.refresh_from_db()
    assert project.submitted_file is None


def test_archived_project_refused(staff_client: Client) -> None:
    project = make_failed_project()
    Project.objects.filter(pk=project.pk).update(archived_at=timezone.now())
    response = staff_client.post(override_url(project), {"reason": REASON}, follow=True)
    assert ARCHIVED_READ_ONLY_MESSAGE in response.content.decode()
    project.refresh_from_db()
    assert project.submitted_file is None


def test_admin_filter_lists_only_overridden_projects(client: Client) -> None:
    overridden = make_failed_project()
    overridden.override_submit(UserFactory(is_staff=True), REASON)
    plain = make_failed_project()
    client.force_login(UserFactory(is_staff=True, is_superuser=True))
    response = client.get(
        reverse("admin:projects_project_changelist"),
        {"submission_override": "yes"},
    )
    listed = {p.pk for p in response.context["cl"].result_list}
    assert overridden.pk in listed
    assert plain.pk not in listed


def test_admin_summary_marks_override(client: Client) -> None:
    project = make_failed_project()
    project.override_submit(UserFactory(is_staff=True), REASON)
    make_failed_project()
    client.force_login(UserFactory(is_staff=True))
    content = client.get(reverse("projects:admin_summary")).content.decode()
    assert content.count("data-submission-override-badge") == 1


def test_staff_override_on_closed_shuttle_like_staff_submit(
    staff_client: Client,
) -> None:
    """The closed-shuttle rule (#320) never refuses staff, so neither here."""
    project = make_failed_project()
    shuttle = Shuttle.objects.create(
        name="G886",
        description="Closed run",
        status=Shuttle.Status.IN_PRODUCTION,
    )
    Project.objects.filter(pk=project.pk).update(shuttle=shuttle)
    response = staff_client.post(override_url(project), {"reason": REASON})
    assert response.status_code == HTTP_FOUND
    project.refresh_from_db()
    assert project.is_submission_override
