"""Tests for ProjectAdminSummaryView."""

import pytest
from django.urls import reverse

from wafer_space.users.tests.factories import UserFactory

from .constants import HTTP_FORBIDDEN
from .constants import HTTP_FOUND
from .constants import HTTP_OK


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
