"""Archive and unarchive views (issue #307)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectAccessLog
from wafer_space.users.tests.factories import UserFactory

from .constants import HTTP_FORBIDDEN
from .constants import HTTP_FOUND
from .constants import HTTP_METHOD_NOT_ALLOWED
from .factories import ProjectFactory
from .factories import ProjectFileFactory

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def archive_url(project: Project) -> str:
    return reverse("projects:archive", args=[project.pk])


def unarchive_url(project: Project) -> str:
    return reverse("projects:unarchive", args=[project.pk])


def test_owner_archives_project(client: Client) -> None:
    project = ProjectFactory()
    client.force_login(project.user)
    response = client.post(archive_url(project))
    assert response.status_code == HTTP_FOUND
    project.refresh_from_db()
    assert project.is_archived


def test_owner_unarchives_project(client: Client) -> None:
    project = ProjectFactory(archived_at=timezone.now())
    client.force_login(project.user)
    client.post(unarchive_url(project))
    project.refresh_from_db()
    assert not project.is_archived


def test_owner_refused_with_submitted_file(client: Client) -> None:
    project = ProjectFactory()
    Project.objects.filter(pk=project.pk).update(
        submitted_file=ProjectFileFactory(project=project),
    )
    client.force_login(project.user)
    response = client.post(archive_url(project), follow=True)
    project.refresh_from_db()
    assert not project.is_archived
    assert "Contact staff to archive it" in response.content.decode()


def test_staff_archives_other_users_project_and_is_logged(client: Client) -> None:
    project = ProjectFactory()
    staff = UserFactory(is_staff=True)
    client.force_login(staff)
    client.post(archive_url(project))
    project.refresh_from_db()
    assert project.is_archived
    assert ProjectAccessLog.objects.filter(
        project=project,
        admin_user=staff,
        view_name="ProjectArchiveView",
    ).exists()


def test_staff_unarchives_other_users_project_and_is_logged(client: Client) -> None:
    project = ProjectFactory(archived_at=timezone.now())
    staff = UserFactory(is_staff=True)
    client.force_login(staff)
    client.post(unarchive_url(project))
    project.refresh_from_db()
    assert not project.is_archived
    assert ProjectAccessLog.objects.filter(
        project=project,
        admin_user=staff,
        view_name="ProjectUnarchiveView",
    ).exists()


def test_stranger_cannot_archive(client: Client) -> None:
    project = ProjectFactory()
    client.force_login(UserFactory())
    assert client.post(archive_url(project)).status_code == HTTP_FORBIDDEN


def test_stranger_cannot_unarchive(client: Client) -> None:
    project = ProjectFactory(archived_at=timezone.now())
    client.force_login(UserFactory())
    assert client.post(unarchive_url(project)).status_code == HTTP_FORBIDDEN


def test_get_archive_not_allowed(client: Client) -> None:
    project = ProjectFactory()
    client.force_login(project.user)
    assert client.get(archive_url(project)).status_code == HTTP_METHOD_NOT_ALLOWED


def test_get_unarchive_not_allowed(client: Client) -> None:
    project = ProjectFactory(archived_at=timezone.now())
    client.force_login(project.user)
    response = client.get(unarchive_url(project))
    assert response.status_code == HTTP_METHOD_NOT_ALLOWED


def test_second_archive_post_changes_nothing(client: Client) -> None:
    project = ProjectFactory()
    client.force_login(project.user)
    client.post(archive_url(project))
    project.refresh_from_db()
    first = project.archived_at
    response = client.post(archive_url(project), follow=True)
    project.refresh_from_db()
    assert project.archived_at == first
    assert "already archived" in response.content.decode()


def test_unarchive_of_active_project_changes_nothing(client: Client) -> None:
    project = ProjectFactory()
    client.force_login(project.user)
    response = client.post(unarchive_url(project), follow=True)
    project.refresh_from_db()
    assert not project.is_archived
    assert "Project is not archived" in response.content.decode()
