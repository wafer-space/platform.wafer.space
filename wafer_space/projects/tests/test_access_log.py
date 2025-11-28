"""Tests for ProjectAccessLog model."""

import pytest
from django.contrib.auth import get_user_model
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.utils import timezone

from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectAccessLog

User = get_user_model()

TEST_PASSWORD = "testpass123"  # noqa: S105


class ProjectAccessLogTestCase(TestCase):
    """Test ProjectAccessLog model."""

    def setUp(self):
        """Set up test users and projects."""
        self.owner = User.objects.create_user(
            username="owner",
            email="owner@example.com",
            password=TEST_PASSWORD,
        )

        self.admin = User.objects.create_user(
            username="admin",
            email="admin@example.com",
            password=TEST_PASSWORD,
            is_staff=True,
        )

        self.project = Project.objects.create(
            user=self.owner,
            name="Test Project",
            description="Test description",
        )

    def test_create_access_log(self):
        """Test creating an access log entry."""
        log = ProjectAccessLog.objects.create(
            project=self.project,
            admin_user=self.admin,
            action=ProjectAccessLog.Action.VIEW,
            ip_address="127.0.0.1",
            user_agent="Mozilla/5.0",
            view_name="ProjectDetailView",
        )

        assert log.project == self.project
        assert log.admin_user == self.admin
        assert log.action == ProjectAccessLog.Action.VIEW
        assert log.ip_address == "127.0.0.1"
        assert log.user_agent == "Mozilla/5.0"
        assert log.view_name == "ProjectDetailView"
        assert log.accessed_at is not None

    def test_access_log_str(self):
        """Test string representation of access log."""
        log = ProjectAccessLog.objects.create(
            project=self.project,
            admin_user=self.admin,
            action=ProjectAccessLog.Action.EDIT,
        )

        expected = f"admin viewed owner's Test Project at {log.accessed_at}"
        assert str(log) == expected

    def test_project_deletion_cascades_logs(self):
        """Test that deleting project deletes associated logs."""
        log = ProjectAccessLog.objects.create(
            project=self.project,
            admin_user=self.admin,
            action=ProjectAccessLog.Action.VIEW,
        )

        self.project.delete()

        # Log should be deleted
        assert not ProjectAccessLog.objects.filter(pk=log.pk).exists()

    def test_admin_user_deletion_protected(self):
        """Test that deleting admin user with logs is prevented."""
        ProjectAccessLog.objects.create(
            project=self.project,
            admin_user=self.admin,
            action=ProjectAccessLog.Action.VIEW,
        )

        # Attempting to delete admin should raise ProtectedError
        with pytest.raises(ProtectedError):
            self.admin.delete()

    def test_all_action_types(self):
        """Test all action type choices are valid."""
        actions = [
            ProjectAccessLog.Action.VIEW,
            ProjectAccessLog.Action.EDIT,
            ProjectAccessLog.Action.DELETE,
            ProjectAccessLog.Action.SUBMIT,
            ProjectAccessLog.Action.FILE_UPLOAD,
        ]

        for action in actions:
            log = ProjectAccessLog.objects.create(
                project=self.project,
                admin_user=self.admin,
                action=action,
            )
            assert log.action == action

    def test_accessed_at_auto_set(self):
        """Test that accessed_at is automatically set to current time."""
        before = timezone.now()
        log = ProjectAccessLog.objects.create(
            project=self.project,
            admin_user=self.admin,
            action=ProjectAccessLog.Action.VIEW,
        )
        after = timezone.now()

        assert before <= log.accessed_at <= after

    def test_optional_fields_can_be_blank(self):
        """Test that IP address, user agent, and view name are optional."""
        log = ProjectAccessLog.objects.create(
            project=self.project,
            admin_user=self.admin,
            action=ProjectAccessLog.Action.VIEW,
        )

        assert log.ip_address is None
        assert log.user_agent == ""
        assert log.view_name == ""

    def test_ordering_by_accessed_at_desc(self):
        """Test that logs are ordered by accessed_at descending."""
        log1 = ProjectAccessLog.objects.create(
            project=self.project,
            admin_user=self.admin,
            action=ProjectAccessLog.Action.VIEW,
        )

        log2 = ProjectAccessLog.objects.create(
            project=self.project,
            admin_user=self.admin,
            action=ProjectAccessLog.Action.EDIT,
        )

        logs = list(ProjectAccessLog.objects.all())
        assert logs[0] == log2  # Most recent first
        assert logs[1] == log1
