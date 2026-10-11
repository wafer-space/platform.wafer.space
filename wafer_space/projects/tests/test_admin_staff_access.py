"""Staff (non-superuser) access to the projects admin pages (issue #305).

The project detail page shows staff an "Admin" button linking to the Django
admin change page. Staff without explicit model permissions must be able to
open it read-only, as for every other projects admin model.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from wafer_space.projects.models import PrecheckImageRevision
from wafer_space.projects.models import ProjectAccessLog
from wafer_space.users.tests.factories import UserFactory

from .constants import HTTP_FORBIDDEN
from .constants import HTTP_OK
from .factories import ProjectFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff_user():
    return UserFactory(is_staff=True, is_superuser=False)


@pytest.fixture
def staff_client(client, staff_user):
    client.force_login(staff_user)
    return client


def test_staff_can_open_project_change_page(staff_client) -> None:
    project = ProjectFactory()
    url = reverse("admin:projects_project_change", args=[project.pk])
    response = staff_client.get(url)
    assert response.status_code == HTTP_OK


def test_staff_project_change_page_is_read_only(staff_client) -> None:
    project = ProjectFactory(name="Original name")
    url = reverse("admin:projects_project_change", args=[project.pk])
    response = staff_client.post(url, {"name": "Changed by staff"})
    assert response.status_code == HTTP_FORBIDDEN
    project.refresh_from_db()
    assert project.name == "Original name"


def test_staff_can_open_project_history_page(staff_client) -> None:
    project = ProjectFactory()
    url = reverse("admin:projects_project_history", args=[project.pk])
    response = staff_client.get(url)
    assert response.status_code == HTTP_OK


def test_staff_can_open_project_changelist(staff_client) -> None:
    response = staff_client.get(reverse("admin:projects_project_changelist"))
    assert response.status_code == HTTP_OK


def test_staff_cannot_add_project_in_admin(staff_client) -> None:
    response = staff_client.get(reverse("admin:projects_project_add"))
    assert response.status_code == HTTP_FORBIDDEN


def test_staff_cannot_delete_project_in_admin(staff_client) -> None:
    project = ProjectFactory()
    url = reverse("admin:projects_project_delete", args=[project.pk])
    response = staff_client.get(url)
    assert response.status_code == HTTP_FORBIDDEN


def test_staff_can_open_access_log_changelist(staff_client, staff_user) -> None:
    ProjectAccessLog.objects.create(
        project=ProjectFactory(),
        admin_user=staff_user,
        action=ProjectAccessLog.Action.VIEW,
        ip_address="127.0.0.1",
        user_agent="test",
        view_name="ProjectDetailView",
    )
    url = reverse("admin:projects_projectaccesslog_changelist")
    response = staff_client.get(url)
    assert response.status_code == HTTP_OK


def test_staff_can_open_precheck_image_revision_changelist(staff_client) -> None:
    PrecheckImageRevision.objects.create(digest="sha256:" + "a" * 64)
    url = reverse("admin:projects_precheckimagerevision_changelist")
    response = staff_client.get(url)
    assert response.status_code == HTTP_OK


def test_staff_cannot_change_precheck_image_revision(staff_client) -> None:
    revision = PrecheckImageRevision.objects.create(digest="sha256:" + "b" * 64)
    url = reverse("admin:projects_precheckimagerevision_change", args=[revision.pk])
    response = staff_client.post(url, {"precheck_version": "changed"})
    assert response.status_code == HTTP_FORBIDDEN


def test_non_staff_cannot_open_project_change_page(client) -> None:
    client.force_login(UserFactory(is_staff=False))
    project = ProjectFactory()
    url = reverse("admin:projects_project_change", args=[project.pk])
    response = client.get(url)
    assert response.status_code != HTTP_OK
