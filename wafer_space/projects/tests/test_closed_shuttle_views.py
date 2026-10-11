"""Owners cannot upload or submit on a closed shuttle (#320)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.urls import URLPattern
from django.urls import reverse

from wafer_space.projects import urls as project_urls
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.shuttles.models import Shuttle
from wafer_space.users.tests.factories import UserFactory

from .constants import HTTP_FORBIDDEN
from .constants import HTTP_FOUND
from .constants import HTTP_OK
from .factories import ProjectFactory
from .factories import ProjectFileFactory

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db

# Every projects URL that names a project (by ``pk``) or one of its checks
# (by ``check_id``) is either allowed on a closed shuttle or refused to its
# owner. A new such URL must be added to one of these sets, so a new view
# that changes the design cannot silently skip the rule (the archive rule
# in test_archive_read_only.py does the same).
ALLOWED_ON_CLOSED = {
    "detail",
    "progress",
    "check_status",
    "cancel_check",
    "update",  # other fields stay editable; the form locks chip-on-board
    "delete",
    "archive",
    "unarchive",
    "compliance_certify",
    "check_drc_update_requeue",  # re-checks a revision; submission stays frozen
}
REFUSED_ON_CLOSED = {"submit", "submit_url"}
PROJECT_KWARGS = ("<uuid:pk>", "<int:check_id>")
REASON = "Shuttle G889 is closed (In Production)"


def project_url_names() -> set[str]:
    return {
        p.name
        for p in project_urls.urlpatterns
        if isinstance(p, URLPattern)
        and p.name
        and any(kwarg in str(p.pattern) for kwarg in PROJECT_KWARGS)
    }


def test_every_project_url_is_classified() -> None:
    assert project_url_names() == ALLOWED_ON_CLOSED | REFUSED_ON_CLOSED


@pytest.fixture
def closed_project() -> Project:
    shuttle = Shuttle.objects.create(
        name="G889", description="Closed run", status=Shuttle.Status.IN_PRODUCTION
    )
    return ProjectFactory(shuttle=shuttle)


@pytest.mark.parametrize("name", sorted(REFUSED_ON_CLOSED))
@pytest.mark.parametrize("method", ["get", "post"])
def test_owner_is_refused(
    client: Client, closed_project: Project, name: str, method: str
) -> None:
    client.force_login(closed_project.user)
    url = reverse(f"projects:{name}", args=[closed_project.pk])

    response = getattr(client, method)(
        url, {"url": "https://example.com/design.gds"}, follow=True
    )

    detail_url = reverse("projects:detail", args=[closed_project.pk])
    closed_project.refresh_from_db()
    assert (
        response.redirect_chain,
        REASON in response.content.decode(),
        ProjectFile.objects.filter(project=closed_project).exists(),
        closed_project.submitted_file,
    ) == ([(detail_url, HTTP_FOUND)], True, False, None)


def test_staff_is_not_refused(client: Client, closed_project: Project) -> None:
    client.force_login(UserFactory(is_staff=True))

    response = client.get(reverse("projects:submit_url", args=[closed_project.pk]))

    assert response.status_code == HTTP_OK


def test_project_without_shuttle_is_not_refused(client: Client) -> None:
    project = ProjectFactory(shuttle=None)
    client.force_login(project.user)

    response = client.get(reverse("projects:submit_url", args=[project.pk]))

    assert response.status_code == HTTP_OK


def test_open_shuttle_is_not_refused(client: Client) -> None:
    shuttle = Shuttle.objects.create(
        name="G894", description="Open run", status=Shuttle.Status.OPEN
    )
    project = ProjectFactory(shuttle=shuttle)
    client.force_login(project.user)

    response = client.get(reverse("projects:submit_url", args=[project.pk]))

    assert response.status_code == HTTP_OK


def test_stranger_still_gets_403(client: Client, closed_project: Project) -> None:
    client.force_login(UserFactory())

    response = client.get(reverse("projects:submit_url", args=[closed_project.pk]))

    assert response.status_code == HTTP_FORBIDDEN


def test_detail_explains_closed_shuttle_to_owner(
    client: Client, closed_project: Project
) -> None:
    client.force_login(closed_project.user)

    content = client.get(
        reverse("projects:detail", args=[closed_project.pk])
    ).content.decode()

    upload_url = reverse("projects:submit_url", args=[closed_project.pk])
    assert (REASON in content, upload_url in content) == (True, False)


def test_detail_keeps_upload_link_for_staff(
    client: Client, closed_project: Project
) -> None:
    client.force_login(UserFactory(is_staff=True))

    content = client.get(
        reverse("projects:detail", args=[closed_project.pk])
    ).content.decode()

    assert reverse("projects:submit_url", args=[closed_project.pk]) in content


def test_detail_keeps_upload_link_on_open_shuttle(client: Client) -> None:
    shuttle = Shuttle.objects.create(
        name="G895", description="Open run", status=Shuttle.Status.OPEN
    )
    project = ProjectFactory(shuttle=shuttle)
    client.force_login(project.user)

    content = client.get(reverse("projects:detail", args=[project.pk])).content.decode()

    assert reverse("projects:submit_url", args=[project.pk]) in content


def test_detail_disables_submit_button_on_closed_shuttle(
    client: Client, closed_project: Project
) -> None:
    ProjectFileFactory(project=closed_project, is_active=True)
    client.force_login(closed_project.user)

    content = client.get(
        reverse("projects:detail", args=[closed_project.pk])
    ).content.decode()

    submit_url = reverse("projects:submit", args=[closed_project.pk])
    assert (f'title="{REASON}"' in content, submit_url in content) == (True, False)
