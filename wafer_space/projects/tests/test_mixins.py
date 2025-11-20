"""Tests for project permission mixins."""

import contextlib

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory
from django.test import TestCase
from django.views.generic import DetailView

from wafer_space.projects.mixins import ProjectOwnerOrSuperuserMixin
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectAccessLog

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

    def test_superuser_access_creates_audit_log(self):
        """Test that superuser access creates audit log entry."""
        request = self.factory.get(f"/projects/{self.project.pk}/")
        request.user = self.superuser
        request.META = {
            "REMOTE_ADDR": "127.0.0.1",
            "HTTP_USER_AGENT": "Mozilla/5.0",
        }

        view = DummyProjectView()
        view.request = request
        view.kwargs = {"pk": self.project.pk}

        # Verify access granted
        assert view.test_func() is True

        # Call dispatch to trigger audit logging
        view.dispatch(request, pk=self.project.pk)

        # Verify audit log created
        logs = ProjectAccessLog.objects.filter(
            project=self.project,
            admin_user=self.superuser,
        )
        assert logs.count() == 1

        log = logs.first()
        assert log is not None
        assert log.action == ProjectAccessLog.Action.VIEW
        assert log.ip_address == "127.0.0.1"
        assert log.user_agent == "Mozilla/5.0"
        assert log.view_name == "DummyProjectView"

    def test_owner_access_no_audit_log(self):
        """Test that owner access does NOT create audit log."""
        request = self.factory.get(f"/projects/{self.project.pk}/")
        request.user = self.owner
        request.META = {
            "REMOTE_ADDR": "127.0.0.1",
            "HTTP_USER_AGENT": "Mozilla/5.0",
        }

        view = DummyProjectView()
        view.request = request
        view.kwargs = {"pk": self.project.pk}

        # Verify access granted
        assert view.test_func() is True

        # Call dispatch
        view.dispatch(request, pk=self.project.pk)

        # Verify NO audit log created (owner access not logged)
        logs = ProjectAccessLog.objects.filter(project=self.project)
        assert logs.count() == 0

    def test_denied_access_no_audit_log(self):
        """Test that denied access does NOT create audit log."""
        request = self.factory.get(f"/projects/{self.project.pk}/")
        request.user = self.other_user
        request.META = {
            "REMOTE_ADDR": "127.0.0.1",
            "HTTP_USER_AGENT": "Mozilla/5.0",
        }

        view = DummyProjectView()
        view.request = request
        view.kwargs = {"pk": self.project.pk}

        # Verify access denied
        assert view.test_func() is False

        # Attempt dispatch (will fail permission check)
        with contextlib.suppress(PermissionDenied):
            view.dispatch(request, pk=self.project.pk)

        # Verify NO audit log created
        logs = ProjectAccessLog.objects.filter(project=self.project)
        assert logs.count() == 0
