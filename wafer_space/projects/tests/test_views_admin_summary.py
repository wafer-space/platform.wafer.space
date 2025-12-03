"""Tests for ProjectAdminSummaryView."""

import pytest
from django.urls import reverse

from wafer_space.users.tests.factories import UserFactory

from .constants import HTTP_FORBIDDEN
from .constants import HTTP_FOUND
from .constants import HTTP_OK
from .factories import ProjectFactory


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
