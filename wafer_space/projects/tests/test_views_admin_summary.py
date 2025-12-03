"""Tests for ProjectAdminSummaryView."""

import pytest
from django.urls import reverse

from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.users.tests.factories import UserFactory

from .constants import HTTP_FORBIDDEN
from .constants import HTTP_FOUND
from .constants import HTTP_OK
from .factories import ProjectFactory
from .factories import ProjectFileFactory


@pytest.mark.django_db
class TestProjectAdminSummaryView:
    """Tests for the admin summary view."""

    def test_staff_can_access(self, client):
        """Staff users can access the summary page."""
        staff_user = UserFactory(is_staff=True)
        client.force_login(staff_user)

        response = client.get(reverse("projects:admin_summary"))

        assert response.status_code == HTTP_OK

    def test_non_staff_cannot_access(self, client):
        """Non-staff users are forbidden."""
        regular_user = UserFactory(is_staff=False)
        client.force_login(regular_user)

        response = client.get(reverse("projects:admin_summary"))

        assert response.status_code == HTTP_FORBIDDEN

    def test_anonymous_redirected_to_login(self, client):
        """Anonymous users are redirected to login."""
        response = client.get(reverse("projects:admin_summary"))

        assert response.status_code == HTTP_FOUND
        assert "/accounts/login/" in response.url

    def test_displays_project_data(self, client):
        """Summary page displays project data in table."""
        staff_user = UserFactory(is_staff=True)
        # Create a project with known data
        owner = UserFactory(username="testowner", email="owner@example.com")
        ProjectFactory(
            name="Test Project",
            user=owner,
            slot_size="1x1",
        )
        client.force_login(staff_user)

        response = client.get(reverse("projects:admin_summary"))

        assert response.status_code == HTTP_OK
        content = response.content.decode()
        assert "Test Project" in content
        assert "testowner" in content
        assert "owner@example.com" in content
        assert "1x1" in content

    def test_displays_all_projects(self, client):
        """Summary page shows all projects, not just user's own."""
        staff_user = UserFactory(is_staff=True)
        other_user = UserFactory()
        ProjectFactory(name="Staff Project", user=staff_user)
        ProjectFactory(name="Other Project", user=other_user)
        client.force_login(staff_user)

        response = client.get(reverse("projects:admin_summary"))

        content = response.content.decode()
        assert "Staff Project" in content
        assert "Other Project" in content

    def test_displays_precheck_status(self, client):
        """Summary page displays manufacturability check status."""
        staff_user = UserFactory(is_staff=True)
        project = ProjectFactory(name="Checked Project")
        # Create active file with manufacturability check
        project_file = ProjectFileFactory(project=project, is_active=True)
        ManufacturabilityCheck.objects.create(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )
        client.force_login(staff_user)

        response = client.get(reverse("projects:admin_summary"))

        content = response.content.decode()
        assert "Finished" in content

    def test_default_sort_by_name(self, client):
        """Default sort is by name ascending."""
        staff_user = UserFactory(is_staff=True)
        ProjectFactory(name="Zebra Project")
        ProjectFactory(name="Alpha Project")
        client.force_login(staff_user)

        response = client.get(reverse("projects:admin_summary"))

        content = response.content.decode()
        alpha_pos = content.find("Alpha Project")
        zebra_pos = content.find("Zebra Project")
        assert alpha_pos < zebra_pos, "Alpha should appear before Zebra"

    def test_sort_by_name_descending(self, client):
        """Sort by name descending with -name parameter."""
        staff_user = UserFactory(is_staff=True)
        ProjectFactory(name="Zebra Project")
        ProjectFactory(name="Alpha Project")
        client.force_login(staff_user)

        response = client.get(reverse("projects:admin_summary") + "?sort=-name")

        content = response.content.decode()
        alpha_pos = content.find("Alpha Project")
        zebra_pos = content.find("Zebra Project")
        assert zebra_pos < alpha_pos, "Zebra should appear before Alpha"

    def test_sort_by_owner(self, client):
        """Sort by owner username."""
        staff_user = UserFactory(is_staff=True)
        user_a = UserFactory(username="alice")
        user_z = UserFactory(username="zack")
        ProjectFactory(name="Zack Project", user=user_z)
        ProjectFactory(name="Alice Project", user=user_a)
        client.force_login(staff_user)

        response = client.get(reverse("projects:admin_summary") + "?sort=owner")

        content = response.content.decode()
        alice_pos = content.find("Alice Project")
        zack_pos = content.find("Zack Project")
        assert alice_pos < zack_pos, "Alice's project should appear first"

    def test_sort_indicator_in_header(self, client):
        """Current sort column shows indicator."""
        staff_user = UserFactory(is_staff=True)
        client.force_login(staff_user)

        response = client.get(reverse("projects:admin_summary") + "?sort=name")

        content = response.content.decode()
        # Should have ascending indicator on name column
        assert "▲" in content or "sort=-name" in content
