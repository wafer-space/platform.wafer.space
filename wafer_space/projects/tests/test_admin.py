"""Tests for Django admin interface."""

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django.test import TestCase

from wafer_space.projects.admin import ProjectAccessLogAdmin
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectAccessLog

User = get_user_model()

TEST_PASSWORD = "testpass123"  # noqa: S105


class ProjectAccessLogAdminTestCase(TestCase):
    """Test ProjectAccessLog admin interface."""

    def setUp(self):
        """Set up test data."""
        self.factory = RequestFactory()
        self.site = AdminSite()

        self.owner = User.objects.create_user(
            username="owner",
            email="owner@example.com",
            password=TEST_PASSWORD,
        )

        self.admin_user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password=TEST_PASSWORD,
        )

        self.project = Project.objects.create(
            user=self.owner,
            name="Test Project",
            description="Test description",
        )

        self.log = ProjectAccessLog.objects.create(
            project=self.project,
            admin_user=self.admin_user,
            action=ProjectAccessLog.Action.VIEW,
            ip_address="127.0.0.1",
            user_agent="Mozilla/5.0",
            view_name="ProjectDetailView",
        )

    def test_list_display_fields(self):
        """Test that correct fields shown in list view."""
        admin = ProjectAccessLogAdmin(ProjectAccessLog, self.site)

        expected_fields = [
            "accessed_at",
            "admin_user",
            "project",
            "action",
            "ip_address",
            "view_name",
        ]

        assert list(admin.list_display) == expected_fields

    def test_list_filter_fields(self):
        """Test that correct filters available."""
        admin = ProjectAccessLogAdmin(ProjectAccessLog, self.site)

        expected_filters = ["action", "accessed_at", "admin_user"]
        assert list(admin.list_filter) == expected_filters

    def test_search_fields(self):
        """Test that correct fields are searchable."""
        admin = ProjectAccessLogAdmin(ProjectAccessLog, self.site)

        expected_search = [
            "admin_user__username",
            "project__name",
            "ip_address",
        ]
        assert list(admin.search_fields) == expected_search

    def test_readonly_fields(self):
        """Test that all fields are read-only."""
        admin = ProjectAccessLogAdmin(ProjectAccessLog, self.site)

        # All fields should be read-only (immutable audit log)
        expected_readonly = [
            "project",
            "admin_user",
            "accessed_at",
            "action",
            "ip_address",
            "user_agent",
            "view_name",
        ]
        assert list(admin.readonly_fields) == expected_readonly

    def test_has_add_permission_false(self):
        """Test that add permission is disabled."""
        admin = ProjectAccessLogAdmin(ProjectAccessLog, self.site)
        request = self.factory.get("/admin/projects/projectaccesslog/")
        request.user = self.admin_user

        assert admin.has_add_permission(request) is False

    def test_has_change_permission_false(self):
        """Test that change permission is disabled."""
        admin = ProjectAccessLogAdmin(ProjectAccessLog, self.site)
        request = self.factory.get("/admin/projects/projectaccesslog/")
        request.user = self.admin_user

        assert admin.has_change_permission(request, obj=self.log) is False

    def test_has_delete_permission_false(self):
        """Test that delete permission is disabled."""
        admin = ProjectAccessLogAdmin(ProjectAccessLog, self.site)
        request = self.factory.get("/admin/projects/projectaccesslog/")
        request.user = self.admin_user

        assert admin.has_delete_permission(request, obj=self.log) is False
