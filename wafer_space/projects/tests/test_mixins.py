"""Tests for project permission mixins."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from django.test import TestCase
from django.views.generic import DetailView

from wafer_space.projects.mixins import ProjectOwnerOrSuperuserMixin
from wafer_space.projects.models import Project

User = get_user_model()

TEST_PASSWORD = "testpass123"  # noqa: S105


class DummyProjectView(ProjectOwnerOrSuperuserMixin, DetailView):
    """Dummy view for testing mixin."""

    model = Project


class ProjectOwnerOrSuperuserMixinTestCase(TestCase):
    """Test ProjectOwnerOrSuperuserMixin permission logic."""

    def setUp(self):
        """Set up test users and projects."""
        self.factory = RequestFactory()

        # Create project owner
        self.owner = User.objects.create_user(
            username="owner",
            email="owner@example.com",
            password=TEST_PASSWORD,
        )

        # Create regular user (not owner)
        self.other_user = User.objects.create_user(
            username="other",
            email="other@example.com",
            password=TEST_PASSWORD,
        )

        # Create superuser
        self.superuser = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password=TEST_PASSWORD,
        )

        # Create staff user (not superuser)
        self.staff_user = User.objects.create_user(
            username="staff",
            email="staff@example.com",
            password=TEST_PASSWORD,
            is_staff=True,
        )

        # Create test project
        self.project = Project.objects.create(
            user=self.owner,
            name="Test Project",
            description="Test description",
        )

    def test_owner_has_access(self):
        """Test that project owner has access."""
        request = self.factory.get(f"/projects/{self.project.pk}/")
        request.user = self.owner

        view = DummyProjectView()
        view.request = request
        view.kwargs = {"pk": self.project.pk}

        assert view.test_func() is True

    def test_other_user_denied_access(self):
        """Test that non-owner regular user is denied access."""
        request = self.factory.get(f"/projects/{self.project.pk}/")
        request.user = self.other_user

        view = DummyProjectView()
        view.request = request
        view.kwargs = {"pk": self.project.pk}

        assert view.test_func() is False

    def test_superuser_has_access(self):
        """Test that superuser has access to any project."""
        request = self.factory.get(f"/projects/{self.project.pk}/")
        request.user = self.superuser

        view = DummyProjectView()
        view.request = request
        view.kwargs = {"pk": self.project.pk}

        assert view.test_func() is True

    def test_staff_without_superuser_denied(self):
        """Test that staff user without superuser flag is denied access."""
        request = self.factory.get(f"/projects/{self.project.pk}/")
        request.user = self.staff_user

        view = DummyProjectView()
        view.request = request
        view.kwargs = {"pk": self.project.pk}

        assert view.test_func() is False

    def test_unauthenticated_user_denied(self):
        """Test that unauthenticated user is denied access."""
        request = self.factory.get(f"/projects/{self.project.pk}/")
        request.user = AnonymousUser()

        view = DummyProjectView()
        view.request = request
        view.kwargs = {"pk": self.project.pk}

        assert view.test_func() is False
