"""Tests for the admin duplicate-to-shuttle view."""

from __future__ import annotations

import pytest
from django.contrib.admin.models import ADDITION
from django.contrib.admin.models import CHANGE
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from wafer_space.projects.models import Project
from wafer_space.shuttles.models import Shuttle

from .constants import HTTP_FORBIDDEN
from .constants import HTTP_FOUND
from .constants import HTTP_OK
from .constants import TEST_PASSWORD
from .factories import ProjectFactory
from .test_duplication_service import make_shuttle
from .test_duplication_service import make_source_project

User = get_user_model()


@pytest.mark.django_db
class TestAdminDuplicateView(TestCase):
    """The duplicate view: permissions, form, POST behaviour."""

    def setUp(self) -> None:
        self.superuser = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password=TEST_PASSWORD,
        )
        self.client.force_login(self.superuser)
        self.source_shuttle = make_shuttle("G890")
        self.target_shuttle = make_shuttle("G891")
        self.production_shuttle = make_shuttle(
            "G892",
            status=Shuttle.Status.IN_PRODUCTION,
        )
        self.project = make_source_project(shuttle=self.source_shuttle)
        self.url = reverse(
            "admin:projects_project_duplicate",
            args=[self.project.pk],
        )

    def test_button_on_change_page(self) -> None:
        change_url = reverse(
            "admin:projects_project_change",
            args=[self.project.pk],
        )
        response = self.client.get(change_url)
        assert response.status_code == HTTP_OK
        self.assertContains(response, self.url)

    def test_get_shows_eligible_shuttles_only(self) -> None:
        response = self.client.get(self.url)
        assert response.status_code == HTTP_OK
        self.assertContains(response, self.target_shuttle.name)
        self.assertNotContains(response, self.production_shuttle.name)
        # Source shuttle is not offered as a target
        form = response.context["form"]
        assert self.source_shuttle not in form.fields["target_shuttle"].queryset

    def test_post_duplicates_and_redirects(self) -> None:
        response = self.client.post(
            self.url,
            {"target_shuttle": self.target_shuttle.pk},
        )
        duplicate = Project.objects.get(shuttle=self.target_shuttle)
        self.assertRedirects(
            response,
            reverse("admin:projects_project_change", args=[duplicate.pk]),
        )
        assert duplicate.status == Project.Status.DRAFT
        assert LogEntry.objects.filter(
            action_flag=ADDITION,
            object_id=str(duplicate.pk),
        ).exists()
        assert LogEntry.objects.filter(
            action_flag=CHANGE,
            object_id=str(self.project.pk),
        ).exists()

    def test_post_collision_shows_error(self) -> None:
        ProjectFactory(
            shuttle=self.target_shuttle,
            project_id=self.project.project_id,
        )
        response = self.client.post(
            self.url,
            {"target_shuttle": self.target_shuttle.pk},
        )
        assert response.status_code == HTTP_OK
        messages = [str(m) for m in response.context["messages"]]
        assert any("already used" in m for m in messages)

    def test_staff_without_add_permission_forbidden(self) -> None:
        staff = User.objects.create_user(
            username="staffer",
            email="staffer@example.com",
            password=TEST_PASSWORD,
            is_staff=True,
        )
        self.client.force_login(staff)
        response = self.client.get(self.url)
        assert response.status_code == HTTP_FORBIDDEN

    def test_unknown_project_404(self) -> None:
        url = reverse(
            "admin:projects_project_duplicate",
            args=["00000000-0000-0000-0000-000000000000"],
        )
        response = self.client.get(url)
        # Django admin redirects unknown objects to the index with a message
        assert response.status_code == HTTP_FOUND
