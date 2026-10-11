"""Staff read-only access to the projects admin pages (issue #305).

The project detail page shows staff an "Admin" button linking to the Django
admin change page. Two halves are proven here:

- ``TestStaffReadOnlyAdminAccess``: a user with ``is_staff`` only (no
  superuser, no model permissions) can open the list and change pages of
  ProjectAdmin, ProjectAccessLogAdmin and PrecheckImageRevisionAdmin, and
  every write path (save, add, delete, bulk delete, history revert,
  duplicate) is refused.
- ``TestNoAdminAccessForNonStaff``: a logged-in non-staff user and an
  anonymous user get no admin access to the same pages.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

import pytest
from django.urls import reverse

from wafer_space.projects.models import PrecheckImageRevision
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectAccessLog
from wafer_space.users.tests.factories import UserFactory

from .constants import HTTP_FORBIDDEN
from .constants import HTTP_FOUND
from .constants import HTTP_OK
from .factories import ProjectFactory

if TYPE_CHECKING:
    from django.test import Client

    from wafer_space.users.models import User

pytestmark = pytest.mark.django_db

ADMIN_MODELS = ["project", "projectaccesslog", "precheckimagerevision"]


@pytest.fixture
def staff_user() -> User:
    return UserFactory(is_staff=True, is_superuser=False)


@pytest.fixture
def staff_client(client: Client, staff_user: User) -> Client:
    client.force_login(staff_user)
    return client


def make_object(model: str, staff_user: User) -> Any:
    """Create one instance of the admin model named ``model``."""
    if model == "project":
        return ProjectFactory()
    if model == "projectaccesslog":
        return ProjectAccessLog.objects.create(
            project=ProjectFactory(),
            admin_user=staff_user,
            action=ProjectAccessLog.Action.VIEW,
            ip_address="127.0.0.1",
            user_agent="test",
            view_name="ProjectDetailView",
        )
    return PrecheckImageRevision.objects.create(digest="sha256:" + "a" * 64)


class TestStaffReadOnlyAdminAccess:
    """A user with is_staff only sees the projects admin pages read-only."""

    @pytest.mark.parametrize("model", ADMIN_MODELS)
    def test_staff_can_open_changelist(self, staff_client: Client, model: str) -> None:
        response = staff_client.get(reverse(f"admin:projects_{model}_changelist"))
        assert response.status_code == HTTP_OK

    @pytest.mark.parametrize("model", ADMIN_MODELS)
    def test_staff_changelist_has_no_add_link(
        self,
        staff_client: Client,
        model: str,
    ) -> None:
        response = staff_client.get(reverse(f"admin:projects_{model}_changelist"))
        assert reverse(f"admin:projects_{model}_add") not in response.content.decode()

    @pytest.mark.parametrize("model", ADMIN_MODELS)
    def test_staff_can_open_change_page(
        self,
        staff_client: Client,
        staff_user: User,
        model: str,
    ) -> None:
        obj = make_object(model, staff_user)
        url = reverse(f"admin:projects_{model}_change", args=[obj.pk])
        response = staff_client.get(url)
        assert response.status_code == HTTP_OK

    @pytest.mark.parametrize("model", ADMIN_MODELS)
    def test_staff_change_page_is_view_only(
        self,
        staff_client: Client,
        staff_user: User,
        model: str,
    ) -> None:
        """The page renders as "View", with no editable field, save or delete."""
        obj = make_object(model, staff_user)
        url = reverse(f"admin:projects_{model}_change", args=[obj.pk])
        response = staff_client.get(url)
        context = response.context
        assert context["title"].startswith("View ")
        assert list(context["adminform"].form.fields) == []
        assert context["has_change_permission"] is False
        assert context["has_delete_permission"] is False
        content = response.content.decode()
        assert 'name="_save"' not in content
        assert reverse(f"admin:projects_{model}_delete", args=[obj.pk]) not in content

    @pytest.mark.parametrize("model", ADMIN_MODELS)
    def test_staff_cannot_save_change_page(
        self,
        staff_client: Client,
        staff_user: User,
        model: str,
    ) -> None:
        obj = make_object(model, staff_user)
        url = reverse(f"admin:projects_{model}_change", args=[obj.pk])
        response = staff_client.post(url, {"_save": "Save"})
        assert response.status_code == HTTP_FORBIDDEN

    @pytest.mark.parametrize("model", ADMIN_MODELS)
    def test_staff_cannot_open_add_page(self, staff_client: Client, model: str) -> None:
        response = staff_client.get(reverse(f"admin:projects_{model}_add"))
        assert response.status_code == HTTP_FORBIDDEN

    @pytest.mark.parametrize("model", ADMIN_MODELS)
    def test_staff_cannot_open_delete_page(
        self,
        staff_client: Client,
        staff_user: User,
        model: str,
    ) -> None:
        obj = make_object(model, staff_user)
        url = reverse(f"admin:projects_{model}_delete", args=[obj.pk])
        response = staff_client.get(url)
        assert response.status_code == HTTP_FORBIDDEN

    def test_staff_project_save_leaves_project_unchanged(
        self,
        staff_client: Client,
    ) -> None:
        project = ProjectFactory(name="Original name")
        url = reverse("admin:projects_project_change", args=[project.pk])
        staff_client.post(url, {"name": "Changed by staff"})
        project.refresh_from_db()
        assert project.name == "Original name"

    def test_staff_cannot_bulk_delete_projects(self, staff_client: Client) -> None:
        project = ProjectFactory()
        staff_client.post(
            reverse("admin:projects_project_changelist"),
            {
                "action": "delete_selected",
                "_selected_action": [str(project.pk)],
                "post": "yes",
            },
        )
        assert Project.objects.filter(pk=project.pk).exists()

    def test_staff_can_open_project_history(self, staff_client: Client) -> None:
        project = ProjectFactory()
        url = reverse("admin:projects_project_history", args=[project.pk])
        response = staff_client.get(url)
        assert response.status_code == HTTP_OK

    def test_staff_can_open_project_history_version(
        self,
        staff_client: Client,
    ) -> None:
        project = ProjectFactory()
        version = project.history.get()
        url = reverse(
            "admin:projects_project_simple_history",
            args=[project.pk, version.history_id],
        )
        response = staff_client.get(url)
        assert response.status_code == HTTP_OK

    def test_staff_cannot_revert_project_via_history(
        self,
        staff_client: Client,
    ) -> None:
        created = ProjectFactory(name="Original name")
        # Reload so the immutability check in Project.clean() can run.
        project = Project.objects.get(pk=created.pk)
        project.name = "Second name"
        project.save()
        original_version = project.history.order_by("history_id").first()
        assert original_version is not None
        url = reverse(
            "admin:projects_project_simple_history",
            args=[project.pk, original_version.history_id],
        )
        response = staff_client.post(url, {})
        assert response.status_code == HTTP_FORBIDDEN
        project.refresh_from_db()
        assert project.name == "Second name"

    def test_staff_cannot_duplicate_project(self, staff_client: Client) -> None:
        project = ProjectFactory()
        url = reverse("admin:projects_project_duplicate", args=[project.pk])
        response = staff_client.get(url)
        assert response.status_code == HTTP_FORBIDDEN


class TestNoAdminAccessForNonStaff:
    """Logged-in non-staff users and anonymous users get no admin access."""

    @pytest.fixture
    def non_staff_client(self, client: Client) -> Client:
        client.force_login(UserFactory(is_staff=False, is_superuser=False))
        return client

    @staticmethod
    def assert_redirected_to_admin_login(response: Any) -> None:
        assert response.status_code == HTTP_FOUND
        assert response["Location"].startswith(reverse("admin:login"))

    @pytest.mark.parametrize("model", ADMIN_MODELS)
    def test_non_staff_changelist_redirects_to_login(
        self,
        non_staff_client: Client,
        model: str,
    ) -> None:
        url = reverse(f"admin:projects_{model}_changelist")
        self.assert_redirected_to_admin_login(non_staff_client.get(url))

    @pytest.mark.parametrize("model", ADMIN_MODELS)
    def test_non_staff_change_page_redirects_to_login(
        self,
        non_staff_client: Client,
        staff_user: User,
        model: str,
    ) -> None:
        obj = make_object(model, staff_user)
        url = reverse(f"admin:projects_{model}_change", args=[obj.pk])
        self.assert_redirected_to_admin_login(non_staff_client.get(url))

    @pytest.mark.parametrize("model", ADMIN_MODELS)
    def test_anonymous_changelist_redirects_to_login(
        self,
        client: Client,
        model: str,
    ) -> None:
        url = reverse(f"admin:projects_{model}_changelist")
        self.assert_redirected_to_admin_login(client.get(url))

    @pytest.mark.parametrize("model", ADMIN_MODELS)
    def test_anonymous_change_page_redirects_to_login(
        self,
        client: Client,
        staff_user: User,
        model: str,
    ) -> None:
        obj = make_object(model, staff_user)
        url = reverse(f"admin:projects_{model}_change", args=[obj.pk])
        self.assert_redirected_to_admin_login(client.get(url))

    def test_non_staff_project_history_redirects_to_login(
        self,
        non_staff_client: Client,
    ) -> None:
        project = ProjectFactory()
        url = reverse("admin:projects_project_history", args=[project.pk])
        self.assert_redirected_to_admin_login(non_staff_client.get(url))
