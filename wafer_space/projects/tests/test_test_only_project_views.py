"""Projects on a test-only shuttle (#221): submit works, counts leave them out."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import Project
from wafer_space.projects.tests.factories import ManufacturabilityCheckFactory
from wafer_space.projects.tests.factories import ProjectFactory
from wafer_space.projects.tests.factories import make_downloaded_file
from wafer_space.shuttles.models import Shuttle
from wafer_space.users.tests.factories import UserFactory

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db

SUBMITTED_TEST_ONLY = "Submitted on G897 (test only): checked, not manufactured"


def _test_shuttle(name: str = "G897") -> Shuttle:
    return Shuttle.objects.create(
        name=name,
        description="Test shuttle",
        status=Shuttle.Status.OPEN,
        is_test_only=True,
    )


def _manufacturable_project(shuttle: Shuttle) -> Project:
    project = ProjectFactory(shuttle=shuttle, status=Project.Status.MANUFACTURABLE)
    project_file = make_downloaded_file(project)
    project_file.hash_verified = True
    project_file.save()
    ManufacturabilityCheckFactory(
        project=project,
        project_file=project_file,
        status=ManufacturabilityCheck.Status.FINISHED,
        is_manufacturable=True,
    )
    return project


def test_owner_submits_on_test_only_shuttle(client: Client) -> None:
    project = _manufacturable_project(_test_shuttle())
    client.force_login(project.user)

    response = client.post(reverse("projects:submit", args=[project.pk]), follow=True)

    project.refresh_from_db()
    assert (
        project.submitted_file is not None,
        SUBMITTED_TEST_ONLY in response.content.decode(),
    ) == (True, True)


def test_real_shuttle_submit_message_unchanged(client: Client) -> None:
    shuttle = Shuttle.objects.create(
        name="G898", description="Real run", status=Shuttle.Status.OPEN
    )
    project = _manufacturable_project(shuttle)
    client.force_login(project.user)

    response = client.post(reverse("projects:submit", args=[project.pk]), follow=True)

    assert "submitted successfully for manufacturing" in response.content.decode()


@pytest.fixture
def summary_response(client: Client):
    Project.objects.all().delete()
    real = Shuttle.objects.create(
        name="G893", description="Real run", status=Shuttle.Status.OPEN
    )
    ProjectFactory(shuttle=real, name="Real design", project_id="AA01")
    ProjectFactory(shuttle=_test_shuttle("G894"), name="Test design", project_id="BB01")
    client.force_login(UserFactory(is_staff=True))
    return client.get(reverse("projects:admin_summary"))


def test_summary_counts_leave_out_test_only_projects(summary_response) -> None:
    context = summary_response.context

    assert (context["summary"]["total"], context["test_only_count"]) == (1, 1)


def test_summary_lists_and_labels_test_only_projects(summary_response) -> None:
    # Whitespace runs collapsed: the headline spans template lines.
    content = " ".join(summary_response.content.decode().split())

    assert (
        "Real design" in content,
        "Test design" in content,
        "1 project (plus 1 test only)" in content,
    ) == (True, True, True)
