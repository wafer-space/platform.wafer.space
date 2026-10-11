"""Archived projects are read-only (issue #307)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.urls import URLPattern
from django.urls import reverse
from django.utils import timezone

from wafer_space.projects import urls as project_urls
from wafer_space.projects.models import ARCHIVED_READ_ONLY_MESSAGE
from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import Project
from wafer_space.users.tests.factories import UserFactory

from .constants import HTTP_FORBIDDEN
from .constants import HTTP_FOUND
from .constants import HTTP_METHOD_NOT_ALLOWED
from .constants import HTTP_OK
from .factories import ManufacturabilityCheckFactory
from .factories import ProjectFactory

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db

# Every projects URL that takes a project pk is either allowed on an
# archived project or refused. A new pk URL must be added to one of these
# sets, so a new write view cannot silently skip the read-only rule.
ALLOWED_ON_ARCHIVED = {
    "detail",  # read only
    "progress",  # read only (AJAX polling)
    "check_status",  # read only (AJAX polling)
    "cancel_check",  # staff stopping a running check: clean-up
    "unarchive",  # the one write allowed on an archived project
    "delete",  # unlinked delete page; its fate is decided in #344
}
REFUSED_ON_ARCHIVED = {
    "update",
    "submit",
    "submit_url",
    "archive",
    "compliance_certify",
}


def pk_url_names() -> set[str]:
    return {
        p.name
        for p in project_urls.urlpatterns
        if isinstance(p, URLPattern) and p.name and "<uuid:pk>" in str(p.pattern)
    }


def test_every_project_pk_url_is_classified() -> None:
    assert pk_url_names() == ALLOWED_ON_ARCHIVED | REFUSED_ON_ARCHIVED


@pytest.fixture
def archived_project() -> Project:
    project = ProjectFactory(name="Archived name", archived_at=timezone.now())
    return Project.objects.get(pk=project.pk)


@pytest.fixture
def owner_client(client: Client, archived_project: Project) -> Client:
    client.force_login(archived_project.user)
    return client


@pytest.mark.parametrize("name", sorted(REFUSED_ON_ARCHIVED))
@pytest.mark.parametrize("method", ["get", "post"])
def test_write_views_refuse_archived_project(
    owner_client: Client,
    archived_project: Project,
    name: str,
    method: str,
) -> None:
    """Each write view redirects to the project page with the refusal."""
    before = archived_project.updated_at
    url = reverse(f"projects:{name}", args=[archived_project.pk])
    response = getattr(owner_client, method)(url, {"name": "Changed"}, follow=True)
    if name == "archive" and method == "get":
        # The archive view is POST-only; GET is refused before any rule.
        assert response.status_code == HTTP_METHOD_NOT_ALLOWED
    else:
        detail_url = reverse("projects:detail", args=[archived_project.pk])
        assert response.redirect_chain == [(detail_url, HTTP_FOUND)]
        expected = (
            "Project is already archived"
            if name == "archive"
            else ARCHIVED_READ_ONLY_MESSAGE
        )
        assert expected in response.content.decode()
    archived_project.refresh_from_db()
    assert archived_project.updated_at == before
    assert archived_project.name == "Archived name"


def test_refusal_shows_read_only_message(
    owner_client: Client,
    archived_project: Project,
) -> None:
    url = reverse("projects:update", args=[archived_project.pk])
    response = owner_client.post(url, {"name": "Changed"}, follow=True)
    assert ARCHIVED_READ_ONLY_MESSAGE in response.content.decode()


def test_stranger_gets_403_not_archive_redirect(
    client: Client,
    archived_project: Project,
) -> None:
    client.force_login(UserFactory())
    url = reverse("projects:update", args=[archived_project.pk])
    assert client.get(url).status_code == HTTP_FORBIDDEN


def test_drc_requeue_refuses_archived_project(
    owner_client: Client,
    archived_project: Project,
) -> None:
    check = ManufacturabilityCheckFactory(
        project=archived_project,
        project_file__project=archived_project,
    )
    checks_before = ManufacturabilityCheck.objects.count()
    url = reverse("projects:check_drc_update_requeue", args=[check.pk])
    response = owner_client.post(url, follow=True)
    assert ARCHIVED_READ_ONLY_MESSAGE in response.content.decode()
    assert ManufacturabilityCheck.objects.count() == checks_before


def test_active_project_edit_page_still_opens(client: Client) -> None:
    project = ProjectFactory()
    client.force_login(project.user)
    response = client.get(reverse("projects:update", args=[project.pk]))
    assert response.status_code == HTTP_OK
