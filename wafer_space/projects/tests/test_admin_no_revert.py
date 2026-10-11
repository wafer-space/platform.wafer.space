"""Project history versions cannot be reverted in the admin (issue #345)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from wafer_space.projects.models import Project
from wafer_space.users.tests.factories import UserFactory

from .constants import HTTP_FORBIDDEN
from .constants import HTTP_OK
from .factories import ProjectFactory

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def superuser_client(client: Client) -> Client:
    client.force_login(UserFactory(is_staff=True, is_superuser=True))
    return client


@pytest.fixture
def renamed_project() -> Project:
    """A project with two history versions: "Original name", "Second name"."""
    created = ProjectFactory(name="Original name")
    project = Project.objects.get(pk=created.pk)
    project.name = "Second name"
    project.save()
    return project


def original_version_url(project: Project) -> str:
    version = project.history.order_by("history_id").first()
    assert version is not None
    return reverse(
        "admin:projects_project_simple_history",
        args=[project.pk, version.history_id],
    )


def test_superuser_history_version_page_opens(
    superuser_client: Client,
    renamed_project: Project,
) -> None:
    response = superuser_client.get(original_version_url(renamed_project))
    assert response.status_code == HTTP_OK


def test_superuser_history_version_has_no_revert_button(
    superuser_client: Client,
    renamed_project: Project,
) -> None:
    response = superuser_client.get(original_version_url(renamed_project))
    content = response.content.decode()
    assert 'value="Revert"' not in content
    assert response.context["revert_disabled"] is True


def test_superuser_revert_post_is_refused(
    superuser_client: Client,
    renamed_project: Project,
) -> None:
    response = superuser_client.post(original_version_url(renamed_project), {})
    assert response.status_code == HTTP_FORBIDDEN
    renamed_project.refresh_from_db()
    assert renamed_project.name == "Second name"


def test_superuser_history_list_still_opens(
    superuser_client: Client,
    renamed_project: Project,
) -> None:
    url = reverse("admin:projects_project_history", args=[renamed_project.pk])
    assert superuser_client.get(url).status_code == HTTP_OK
