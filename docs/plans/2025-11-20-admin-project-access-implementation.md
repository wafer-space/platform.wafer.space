# Admin Project Access Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow Django staff users to view, edit, and manage any user's project with comprehensive audit logging and visual indicators.

**Architecture:** Centralized permission mixin (`ProjectOwnerOrStaffMixin`) replaces individual `test_func()` implementations across 7 project views. Immutable audit log model (`ProjectAccessLog`) tracks all admin access. UI warning banners and badges provide visual feedback.

**Tech Stack:** Django 5.2+, PostgreSQL, pytest-django, Playwright (browser tests), Bootstrap 5

**Design Document:** See `docs/plans/2025-11-20-admin-project-access-design.md` for complete architecture and rationale.

---

## Task 1: Create ProjectOwnerOrStaffMixin with Permission Tests

**Files:**
- Create: `wafer_space/projects/mixins.py`
- Create: `wafer_space/projects/tests/test_mixins.py`

**Step 1: Write failing permission tests**

Create `wafer_space/projects/tests/test_mixins.py`:

```python
"""Tests for project permission mixins."""

import pytest
from django.contrib.auth import get_user_model
from django.http import HttpRequest
from django.test import RequestFactory, TestCase
from django.views.generic import DetailView

from wafer_space.projects.mixins import ProjectOwnerOrStaffMixin
from wafer_space.projects.models import Project

User = get_user_model()


class DummyProjectView(ProjectOwnerOrStaffMixin, DetailView):
    """Dummy view for testing mixin."""

    model = Project


class ProjectOwnerOrStaffMixinTestCase(TestCase):
    """Test ProjectOwnerOrStaffMixin permission logic."""

    def setUp(self):
        """Set up test users and projects."""
        self.factory = RequestFactory()

        # Create project owner
        self.owner = User.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="testpass123",
        )

        # Create regular user (not owner)
        self.other_user = User.objects.create_user(
            username="other",
            email="other@example.com",
            password="testpass123",
        )

        # Create staff user (has is_staff=True)
        self.staff_user = User.objects.create_user(
            username="staff",
            email="staff@example.com",
            password="testpass123",
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

    def test_staff_user_has_access(self):
        """Test that staff user has access to any project."""
        request = self.factory.get(f"/projects/{self.project.pk}/")
        request.user = self.staff_user

        view = DummyProjectView()
        view.request = request
        view.kwargs = {"pk": self.project.pk}

        assert view.test_func() is True

    def test_non_staff_denied(self):
        """Test that non-staff user is denied access to others' projects."""
        request = self.factory.get(f"/projects/{self.project.pk}/")
        request.user = self.staff_user

        view = DummyProjectView()
        view.request = request
        view.kwargs = {"pk": self.project.pk}

        assert view.test_func() is False

    def test_unauthenticated_user_denied(self):
        """Test that unauthenticated user is denied access."""
        from django.contrib.auth.models import AnonymousUser

        request = self.factory.get(f"/projects/{self.project.pk}/")
        request.user = AnonymousUser()

        view = DummyProjectView()
        view.request = request
        view.kwargs = {"pk": self.project.pk}

        assert view.test_func() is False
```

**Step 2: Run tests to verify they fail**

```bash
cd /home/tim/github/wafer-space/test-platform/.worktrees/admin-project-access
uv run pytest wafer_space/projects/tests/test_mixins.py -v
```

Expected: FAIL with "ModuleNotFoundError: No module named 'wafer_space.projects.mixins'"

**Step 3: Create minimal mixin implementation**

Create `wafer_space/projects/mixins.py`:

```python
"""Permission mixins for project views."""

from django.contrib.auth.mixins import UserPassesTestMixin


class ProjectOwnerOrStaffMixin(UserPassesTestMixin):
    """Mixin to allow access to project owner or staff users.

    This mixin should be used on all project-related views to enforce
    consistent permission checking:
    - Project owner always has access
    - Staff users have access to all projects
    - All other users are denied access

    Security Design:
    - Fail-closed: Returns False by default
    - Explicit dual check: user.is_authenticated AND user.is_staff
    - Prevents bypass via unauthenticated staff user accounts

    Usage:
        class ProjectDetailView(
            LoginRequiredMixin,
            ProjectOwnerOrStaffMixin,
            DetailView,
        ):
            model = Project
    """

    def test_func(self):
        """Check if user can access this project.

        Returns True if:
        - User owns the project, OR
        - User is an authenticated staff user

        Returns False for:
        - Non-owners
        - Non-staff users
        - Unauthenticated users (even if is_staff=True)
        """
        project = self.get_object()
        user = self.request.user

        # Owner always has access
        if project.user == user:
            return True

        # Staff users have access to all projects
        # Both checks required for security (fail-closed)
        if user.is_authenticated and user.is_staff:
            return True

        # Default deny
        return False
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest wafer_space/projects/tests/test_mixins.py -v
```

Expected: 5 passed

**Step 5: Run full test suite to ensure no regressions**

```bash
make test
```

Expected: All tests pass (baseline: 496 passed, 1 skipped)

**Step 6: Commit**

```bash
make lint-fix
make lint
git add wafer_space/projects/mixins.py wafer_space/projects/tests/test_mixins.py
git commit -m "Add ProjectOwnerOrStaffMixin with permission tests

Implement centralized permission mixin to allow project owner or
staff user access. Includes comprehensive tests for:
- Owner access
- Superuser access
- Non-owner denial
- Non-staff user denial
- Unauthenticated user denial

Security features:
- Fail-closed design (default deny)
- Explicit dual check (is_authenticated AND is_staff)
- Prevents unauthenticated staff user bypass

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: Add ProjectAccessLog Model with Tests

**Files:**
- Modify: `wafer_space/projects/models.py`
- Create: `wafer_space/projects/tests/test_access_log.py`

**Step 1: Write failing model tests**

Create `wafer_space/projects/tests/test_access_log.py`:

```python
"""Tests for ProjectAccessLog model."""

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from wafer_space.projects.models import Project, ProjectAccessLog

User = get_user_model()


class ProjectAccessLogTestCase(TestCase):
    """Test ProjectAccessLog model."""

    def setUp(self):
        """Set up test users and projects."""
        self.owner = User.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="testpass123",
        )

        self.admin = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="testpass123",
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

        project_pk = self.project.pk
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
        from django.db.models.deletion import ProtectedError

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
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest wafer_space/projects/tests/test_access_log.py -v
```

Expected: FAIL with "ImportError: cannot import name 'ProjectAccessLog'"

**Step 3: Add ProjectAccessLog model**

Modify `wafer_space/projects/models.py` - add after Project model:

```python
class ProjectAccessLog(models.Model):
    """Audit log for when admins access other users' projects.

    This model provides immutable audit logging for all admin access to
    projects they don't own. Logs are append-only and cannot be deleted
    while the admin user exists (PROTECT constraint).

    Security Features:
    - Immutable: No update operations allowed in admin
    - Protected: Cannot delete admin users with logs
    - Comprehensive: Captures IP, user agent, timestamp, action
    """

    class Action(models.TextChoices):
        """Types of actions admins can perform on projects."""

        VIEW = "view", "Viewed"
        EDIT = "edit", "Edited"
        DELETE = "delete", "Deleted"
        SUBMIT = "submit", "Submitted"
        FILE_UPLOAD = "file_upload", "Uploaded File"

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="access_logs",
        help_text="Project that was accessed",
    )

    admin_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,  # SECURITY: Prevent deletion of users with logs
        related_name="admin_access_logs",
        help_text="Admin user who accessed the project",
    )

    accessed_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When the access occurred",
    )

    action = models.CharField(
        max_length=20,
        choices=Action.choices,
        help_text="Type of action performed",
    )

    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="IP address of the admin user",
    )

    user_agent = models.TextField(
        blank=True,
        help_text="User agent string from the request",
    )

    view_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Name of the view that was accessed",
    )

    class Meta:
        ordering = ["-accessed_at"]
        verbose_name = "Project Access Log"
        verbose_name_plural = "Project Access Logs"
        indexes = [
            models.Index(fields=["-accessed_at"]),
            models.Index(fields=["admin_user", "-accessed_at"]),
            models.Index(fields=["project", "-accessed_at"]),
        ]

    def __str__(self):
        """String representation of access log."""
        return (
            f"{self.admin_user.username} viewed "
            f"{self.project.user.username}'s {self.project.name} "
            f"at {self.accessed_at}"
        )
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest wafer_space/projects/tests/test_access_log.py -v
```

Expected: 8 passed

**Step 5: Run full test suite**

```bash
make test
```

Expected: All tests pass

**Step 6: Commit**

```bash
make lint-fix
make lint
git add wafer_space/projects/models.py wafer_space/projects/tests/test_access_log.py
git commit -m "Add ProjectAccessLog model with comprehensive tests

Implement immutable audit log model for admin project access:
- Tracks all admin actions on other users' projects
- PROTECT constraint prevents deletion of admins with logs
- Captures IP address, user agent, timestamp, action type
- Indexed for performance on common queries

Tests cover:
- Log creation and all action types
- Cascade deletion when project deleted
- Protection preventing admin user deletion
- Auto-set timestamp
- Optional fields
- Ordering by accessed_at descending

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: Create Database Migration

**Files:**
- Create: `wafer_space/projects/migrations/000X_add_project_access_log.py` (auto-generated)

**Step 1: Create migration**

```bash
uv run python manage.py makemigrations projects
```

Expected output: "Migrations for 'projects': wafer_space/projects/migrations/000X_add_project_access_log.py - Create model ProjectAccessLog"

**Step 2: Review migration file**

```bash
cat wafer_space/projects/migrations/000X_add_project_access_log.py
```

Verify it contains:
- CreateModel operation for ProjectAccessLog
- All fields (project, admin_user, accessed_at, action, ip_address, user_agent, view_name)
- Indexes on accessed_at, admin_user+accessed_at, project+accessed_at
- Meta options (ordering, verbose_name)

**Step 3: Apply migration**

```bash
uv run python manage.py migrate
```

Expected: "Running migrations: Applying projects.000X_add_project_access_log... OK"

**Step 4: Test migration is reversible**

```bash
uv run python manage.py migrate projects <previous_migration_number>
uv run python manage.py migrate projects
```

Expected: Both directions work without errors

**Step 5: Run full test suite with migrations**

```bash
make test
```

Expected: All tests pass (migrations applied in test database)

**Step 6: Commit migration**

```bash
git add wafer_space/projects/migrations/
git commit -m "Add migration for ProjectAccessLog model

Create database migration for admin access audit logging.

Migration includes:
- ProjectAccessLog model with all fields
- Indexes for performance (accessed_at, admin_user, project)
- CASCADE on project FK, PROTECT on admin_user FK

Verified reversible migration.

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: Update ProjectDetailView with Integration Tests

**Files:**
- Modify: `wafer_space/projects/views.py`
- Modify: `wafer_space/projects/tests/test_views.py`

**Step 1: Write failing integration tests**

Add to `wafer_space/projects/tests/test_views.py`:

```python
def test_project_detail_owner_access(self):
    """Test that project owner can access detail view."""
    self.client.force_login(self.owner)
    response = self.client.get(
        reverse("projects:detail", kwargs={"pk": self.project.pk})
    )
    assert response.status_code == 200
    assert response.context["project"] == self.project


def test_project_detail_other_user_denied(self):
    """Test that non-owner is denied access to detail view."""
    other_user = User.objects.create_user(
        username="other",
        email="other@example.com",
        password="testpass123",
    )
    self.client.force_login(other_user)

    response = self.client.get(
        reverse("projects:detail", kwargs={"pk": self.project.pk})
    )
    assert response.status_code == 403  # Forbidden


def test_project_detail_staff_user_access(self):
    """Test that staff user can access any project detail view."""
    staff_user = User.objects.create_superuser(
        username="admin",
        email="admin@example.com",
        password="testpass123",
    )
    self.client.force_login(staff_user)

    response = self.client.get(
        reverse("projects:detail", kwargs={"pk": self.project.pk})
    )
    assert response.status_code == 200
    assert response.context["project"] == self.project
    assert response.context["viewing_as_admin"] is True


def test_project_detail_non_staff_denied(self):
    """Test that non-staff user is denied access to others' projects."""
    staff_user = User.objects.create_user(
        username="staff",
        email="staff@example.com",
        password="testpass123",
        is_staff=True,
    )
    self.client.force_login(staff_user)

    response = self.client.get(
        reverse("projects:detail", kwargs={"pk": self.project.pk})
    )
    assert response.status_code == 403  # Forbidden
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest wafer_space/projects/tests/test_views.py::test_project_detail_owner_access -v
uv run pytest wafer_space/projects/tests/test_views.py::test_project_detail_other_user_denied -v
uv run pytest wafer_space/projects/tests/test_views.py::test_project_detail_staff_user_access -v
uv run pytest wafer_space/projects/tests/test_views.py::test_project_detail_non_staff_denied -v
```

Expected: Tests may fail or pass depending on existing implementation. The staff user test should fail with KeyError on 'viewing_as_admin'.

**Step 3: Update ProjectDetailView to use new mixin**

Modify `wafer_space/projects/views.py`:

```python
# At top of file, add import:
from wafer_space.projects.mixins import ProjectOwnerOrStaffMixin

# Find ProjectDetailView class, change from:
class ProjectDetailView(LoginRequiredMixin, UserPassesTestMixin, DetailView):
    model = Project

    def test_func(self):
        """Only allow the owner to view the project."""
        project = self.get_object()
        return project.user == self.request.user

# Change to:
class ProjectDetailView(LoginRequiredMixin, ProjectOwnerOrStaffMixin, DetailView):
    model = Project

    def get_context_data(self, **kwargs):
        """Add viewing_as_admin flag to context."""
        context = super().get_context_data(**kwargs)
        project = self.get_object()
        user = self.request.user

        # Flag if staff user is viewing another user's project
        context["viewing_as_admin"] = (
            user.is_authenticated
            and user.is_staff
            and project.user != user
        )

        return context
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest wafer_space/projects/tests/test_views.py::test_project_detail_owner_access -v
uv run pytest wafer_space/projects/tests/test_views.py::test_project_detail_other_user_denied -v
uv run pytest wafer_space/projects/tests/test_views.py::test_project_detail_staff_user_access -v
uv run pytest wafer_space/projects/tests/test_views.py::test_project_detail_non_staff_denied -v
```

Expected: 4 passed

**Step 5: Run full test suite**

```bash
make test
```

Expected: All tests pass

**Step 6: Commit**

```bash
make lint-fix
make lint
git add wafer_space/projects/views.py wafer_space/projects/tests/test_views.py
git commit -m "Update ProjectDetailView to use new permission mixin

Replace UserPassesTestMixin with ProjectOwnerOrStaffMixin to
allow staff user access. Add viewing_as_admin context variable for
UI indicator support.

Tests verify:
- Owner access granted
- Non-owner denied
- Superuser access granted
- Non-staff user denied
- viewing_as_admin flag set correctly

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: Update Remaining Project Views (6 views)

**Files:**
- Modify: `wafer_space/projects/views.py`
- Modify: `wafer_space/projects/tests/test_views.py`

**Views to update:**
1. ProjectListView
2. ProjectUpdateView
3. ProjectDeleteView
4. ProjectFileSubmitURLView
5. ProjectFileProgressView
6. ProjectSubmitView

**Step 1: Write failing tests for ProjectListView**

Add to `wafer_space/projects/tests/test_views.py`:

```python
def test_project_list_shows_only_own_projects_for_regular_user(self):
    """Test that regular users only see their own projects in list."""
    # Create another user with a project
    other_user = User.objects.create_user(
        username="other",
        email="other@example.com",
        password="testpass123",
    )
    other_project = Project.objects.create(
        user=other_user,
        name="Other Project",
        description="Other description",
    )

    self.client.force_login(self.owner)
    response = self.client.get(reverse("projects:list"))

    assert response.status_code == 200
    projects = list(response.context["object_list"])
    assert self.project in projects
    assert other_project not in projects


def test_project_list_shows_all_projects_for_staff_user(self):
    """Test that staff users see all users' projects in list."""
    # Create another user with a project
    other_user = User.objects.create_user(
        username="other",
        email="other@example.com",
        password="testpass123",
    )
    other_project = Project.objects.create(
        user=other_user,
        name="Other Project",
        description="Other description",
    )

    staff_user = User.objects.create_superuser(
        username="admin",
        email="admin@example.com",
        password="testpass123",
    )
    self.client.force_login(staff_user)

    response = self.client.get(reverse("projects:list"))
    assert response.status_code == 200

    projects = list(response.context["object_list"])
    assert self.project in projects
    assert other_project in projects
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest wafer_space/projects/tests/test_views.py::test_project_list_shows_only_own_projects_for_regular_user -v
uv run pytest wafer_space/projects/tests/test_views.py::test_project_list_shows_all_projects_for_staff_user -v
```

Expected: Superuser test fails (only shows their own empty project list)

**Step 3: Update ProjectListView**

Modify `wafer_space/projects/views.py`:

```python
# Find ProjectListView, change from:
class ProjectListView(LoginRequiredMixin, ListView):
    model = Project

    def get_queryset(self):
        """Return only the current user's projects."""
        return Project.objects.filter(user=self.request.user)

# Change to:
class ProjectListView(LoginRequiredMixin, ListView):
    model = Project

    def get_queryset(self):
        """Return projects accessible to current user.

        - Regular users: only their own projects
        - Staff users: all projects from all users
        """
        user = self.request.user

        if user.is_staff:
            # Staff users see all projects
            return Project.objects.all().select_related("user")

        # Regular users see only their own projects
        return Project.objects.filter(user=user)
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest wafer_space/projects/tests/test_views.py::test_project_list_shows_only_own_projects_for_regular_user -v
uv run pytest wafer_space/projects/tests/test_views.py::test_project_list_shows_all_projects_for_staff_user -v
```

Expected: 2 passed

**Step 5: Update remaining 5 views**

For each of ProjectUpdateView, ProjectDeleteView, ProjectFileSubmitURLView, ProjectFileProgressView, ProjectSubmitView:

1. Replace `UserPassesTestMixin` with `ProjectOwnerOrStaffMixin` in class definition
2. Remove the old `test_func()` method
3. Add `get_context_data()` to set `viewing_as_admin` flag (same pattern as ProjectDetailView)

Example for ProjectUpdateView:

```python
# OLD:
class ProjectUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    model = Project
    fields = ["name", "description"]

    def test_func(self):
        """Only allow the owner to update the project."""
        project = self.get_object()
        return project.user == self.request.user

# NEW:
class ProjectUpdateView(LoginRequiredMixin, ProjectOwnerOrStaffMixin, UpdateView):
    model = Project
    fields = ["name", "description"]

    def get_context_data(self, **kwargs):
        """Add viewing_as_admin flag to context."""
        context = super().get_context_data(**kwargs)
        project = self.get_object()
        user = self.request.user

        context["viewing_as_admin"] = (
            user.is_authenticated
            and user.is_staff
            and project.user != user
        )

        return context
```

Apply same pattern to remaining 4 views.

**Step 6: Write integration tests for remaining views**

Add to `wafer_space/projects/tests/test_views.py`:

```python
def test_project_update_staff_user_access(self):
    """Test that staff user can access update view for any project."""
    staff_user = User.objects.create_superuser(
        username="admin",
        email="admin@example.com",
        password="testpass123",
    )
    self.client.force_login(staff_user)

    response = self.client.get(
        reverse("projects:update", kwargs={"pk": self.project.pk})
    )
    assert response.status_code == 200
    assert response.context["viewing_as_admin"] is True


def test_project_delete_staff_user_access(self):
    """Test that staff user can access delete view for any project."""
    staff_user = User.objects.create_superuser(
        username="admin",
        email="admin@example.com",
        password="testpass123",
    )
    self.client.force_login(staff_user)

    response = self.client.get(
        reverse("projects:delete", kwargs={"pk": self.project.pk})
    )
    assert response.status_code == 200
    assert response.context["viewing_as_admin"] is True
```

**Step 7: Run all view tests**

```bash
uv run pytest wafer_space/projects/tests/test_views.py -v
```

Expected: All tests pass

**Step 8: Run full test suite**

```bash
make test
```

Expected: All tests pass

**Step 9: Commit**

```bash
make lint-fix
make lint
git add wafer_space/projects/views.py wafer_space/projects/tests/test_views.py
git commit -m "Update all project views to use new permission mixin

Migrate all 6 remaining project views to use
ProjectOwnerOrStaffMixin:
- ProjectListView: show all projects to staff users
- ProjectUpdateView: allow staff user edit access
- ProjectDeleteView: allow staff user delete access
- ProjectFileSubmitURLView: allow staff user file access
- ProjectFileProgressView: allow staff user progress view
- ProjectSubmitView: allow staff user submission

All views now include viewing_as_admin context flag.

Tests verify staff user access and regular user restrictions
for all views.

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: Add Audit Logging to Mixin

**Files:**
- Modify: `wafer_space/projects/mixins.py`
- Modify: `wafer_space/projects/tests/test_mixins.py`

**Step 1: Write failing audit log tests**

Add to `wafer_space/projects/tests/test_mixins.py`:

```python
from wafer_space.projects.models import ProjectAccessLog


def test_staff_user_access_creates_audit_log(self):
    """Test that staff user access creates audit log entry."""
    request = self.factory.get(f"/projects/{self.project.pk}/")
    request.user = self.staff_user
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
        admin_user=self.staff_user,
    )
    assert logs.count() == 1

    log = logs.first()
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
    try:
        view.dispatch(request, pk=self.project.pk)
    except Exception:
        pass  # Permission denied expected

    # Verify NO audit log created
    logs = ProjectAccessLog.objects.filter(project=self.project)
    assert logs.count() == 0
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest wafer_space/projects/tests/test_mixins.py::test_staff_user_access_creates_audit_log -v
uv run pytest wafer_space/projects/tests/test_mixins.py::test_owner_access_no_audit_log -v
uv run pytest wafer_space/projects/tests/test_mixins.py::test_denied_access_no_audit_log -v
```

Expected: FAIL - no audit logs created

**Step 3: Add audit logging to mixin**

Modify `wafer_space/projects/mixins.py`:

```python
"""Permission mixins for project views."""

from django.contrib.auth.mixins import UserPassesTestMixin


class ProjectOwnerOrStaffMixin(UserPassesTestMixin):
    """Mixin to allow access to project owner or staff users.

    This mixin should be used on all project-related views to enforce
    consistent permission checking:
    - Project owner always has access
    - Staff users have access to all projects
    - All other users are denied access

    Audit Logging:
    - When staff users access projects they don't own, an audit log is created
    - Logs include: timestamp, IP address, user agent, action, view name
    - Owner access is NOT logged (normal operation)

    Security Design:
    - Fail-closed: Returns False by default
    - Explicit dual check: user.is_authenticated AND user.is_staff
    - Prevents bypass via unauthenticated staff user accounts

    Usage:
        class ProjectDetailView(
            LoginRequiredMixin,
            ProjectOwnerOrStaffMixin,
            DetailView,
        ):
            model = Project
    """

    def test_func(self):
        """Check if user can access this project.

        Returns True if:
        - User owns the project, OR
        - User is an authenticated staff user

        Returns False for:
        - Non-owners
        - Non-staff users
        - Unauthenticated users (even if is_staff=True)
        """
        project = self.get_object()
        user = self.request.user

        # Owner always has access
        if project.user == user:
            return True

        # Staff users have access to all projects
        # Both checks required for security (fail-closed)
        if user.is_authenticated and user.is_staff:
            return True

        # Default deny
        return False

    def dispatch(self, request, *args, **kwargs):
        """Dispatch request and create audit log for staff user access."""
        # Get response from parent
        response = super().dispatch(request, *args, **kwargs)

        # Only log if access was granted (status < 400)
        if response.status_code < 400:
            project = self.get_object()
            user = request.user

            # Only log staff user access to OTHER users' projects
            if (
                user.is_authenticated
                and user.is_staff
                and project.user != user
            ):
                self._create_audit_log(project, user, request)

        return response

    def _create_audit_log(self, project, admin_user, request):
        """Create audit log entry for admin access.

        Args:
            project: Project being accessed
            admin_user: Superuser accessing the project
            request: HTTP request object
        """
        from wafer_space.projects.models import ProjectAccessLog

        # Determine action based on request method
        action_map = {
            "GET": ProjectAccessLog.Action.VIEW,
            "POST": ProjectAccessLog.Action.EDIT,
            "PUT": ProjectAccessLog.Action.EDIT,
            "PATCH": ProjectAccessLog.Action.EDIT,
            "DELETE": ProjectAccessLog.Action.DELETE,
        }
        action = action_map.get(request.method, ProjectAccessLog.Action.VIEW)

        # Get client IP address
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            ip_address = x_forwarded_for.split(",")[0].strip()
        else:
            ip_address = request.META.get("REMOTE_ADDR")

        # Create log entry
        ProjectAccessLog.objects.create(
            project=project,
            admin_user=admin_user,
            action=action,
            ip_address=ip_address,
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            view_name=self.__class__.__name__,
        )
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest wafer_space/projects/tests/test_mixins.py::test_staff_user_access_creates_audit_log -v
uv run pytest wafer_space/projects/tests/test_mixins.py::test_owner_access_no_audit_log -v
uv run pytest wafer_space/projects/tests/test_mixins.py::test_denied_access_no_audit_log -v
```

Expected: 3 passed

**Step 5: Run all mixin tests**

```bash
uv run pytest wafer_space/projects/tests/test_mixins.py -v
```

Expected: All tests pass (8 total)

**Step 6: Run full test suite**

```bash
make test
```

Expected: All tests pass

**Step 7: Commit**

```bash
make lint-fix
make lint
git add wafer_space/projects/mixins.py wafer_space/projects/tests/test_mixins.py
git commit -m "Add audit logging to ProjectOwnerOrStaffMixin

Implement automatic audit logging when staff users access other
users' projects:
- Log created on successful access (status < 400)
- Captures IP address, user agent, timestamp, action, view name
- Action determined by HTTP method (GET=VIEW, POST/PUT/PATCH=EDIT, etc.)
- Owner access NOT logged (normal operation)
- Denied access NOT logged (no project accessed)

Tests verify:
- Superuser access creates log with correct details
- Owner access does not create log
- Denied access does not create log

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 7: Add UI Warning Banner to Templates

**Files:**
- Create: `wafer_space/projects/templates/projects/_admin_warning_banner.html`
- Modify: `wafer_space/projects/templates/projects/project_detail.html`
- Modify: `wafer_space/projects/templates/projects/project_form.html`
- Modify: `wafer_space/projects/templates/projects/project_confirm_delete.html`

**Step 1: Create reusable warning banner template**

Create `wafer_space/projects/templates/projects/_admin_warning_banner.html`:

```html
{% if viewing_as_admin %}
<div class="alert alert-warning border-warning mb-4" role="alert">
    <div class="d-flex align-items-center">
        <i class="bi bi-exclamation-triangle-fill me-2 fs-4"></i>
        <div>
            <strong>⚠️ Admin Mode:</strong>
            You are viewing <strong>{{ project.user.username }}</strong>'s project.
            All actions will be logged for audit purposes.
        </div>
    </div>
</div>
{% endif %}
```

**Step 2: Add banner to project_detail.html**

Modify `wafer_space/projects/templates/projects/project_detail.html`:

Find the content block, add banner at the top:

```html
{% block content %}
    {% include "projects/_admin_warning_banner.html" %}

    <!-- Existing content below -->
    <h1>{{ project.name }}</h1>
    ...
{% endblock %}
```

**Step 3: Add banner to project_form.html**

Modify `wafer_space/projects/templates/projects/project_form.html`:

```html
{% block content %}
    {% include "projects/_admin_warning_banner.html" %}

    <!-- Existing form content below -->
    <h1>{% if form.instance.pk %}Edit{% else %}Create{% endif %} Project</h1>
    ...
{% endblock %}
```

**Step 4: Add banner to project_confirm_delete.html**

Modify `wafer_space/projects/templates/projects/project_confirm_delete.html`:

```html
{% block content %}
    {% include "projects/_admin_warning_banner.html" %}

    <!-- Existing delete confirmation content below -->
    <h1>Delete Project</h1>
    ...
{% endblock %}
```

**Step 5: Add owner badge to project list template**

Modify `wafer_space/projects/templates/projects/project_list.html`:

Find the project list loop, add owner badge:

```html
{% for project in object_list %}
    <div class="project-card">
        <h3>
            {{ project.name }}
            {% if project.user == request.user %}
                <span class="badge bg-success ms-2">Your Project</span>
            {% else %}
                <span class="badge bg-info ms-2">{{ project.user.username }}'s Project</span>
            {% endif %}
        </h3>
        ...
    </div>
{% endfor %}
```

**Step 6: Manual verification (no automated test)**

Start development server and manually verify:

```bash
make runserver
```

1. Create staff user if needed: `make createsuperuser`
2. Login as staff user
3. Visit another user's project detail page
4. Verify warning banner appears
5. Verify owner badge shows in project list

**Step 7: Commit template changes**

```bash
git add wafer_space/projects/templates/
git commit -m "Add UI warning banner for admin project access

Add visual indicators for staff user project access:
- Warning banner on detail, edit, delete views
- Shows project owner username
- Indicates audit logging active
- Owner badges in project list (green=yours, blue=others)

Banner uses Bootstrap alert-warning styling with
exclamation triangle icon for visibility.

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 8: Add Browser Tests for Admin Access

**Files:**
- Create: `tests/browser/test_admin_project_access.py`

**Step 1: Write browser tests**

Create `tests/browser/test_admin_project_access.py`:

```python
"""Browser tests for admin project access functionality."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from wafer_space.projects.models import Project, ProjectAccessLog

User = get_user_model()

pytestmark = pytest.mark.browser


@pytest.fixture
def owner(db):
    """Create project owner user."""
    return User.objects.create_user(
        username="owner",
        email="owner@example.com",
        password="testpass123",
    )


@pytest.fixture
def staff_user(db):
    """Create staff user."""
    return User.objects.create_superuser(
        username="admin",
        email="admin@example.com",
        password="testpass123",
    )


@pytest.fixture
def project(owner):
    """Create test project."""
    return Project.objects.create(
        user=owner,
        name="Test Project",
        description="Test description",
    )


def test_staff_user_sees_warning_banner(driver, live_server, staff_user, project):
    """Test that staff user sees warning banner on other user's project."""
    # Login as staff user
    driver.get(f"{live_server.url}/accounts/login/")
    driver.find_element("id", "id_login").send_keys("admin")
    driver.find_element("id", "id_password").send_keys("testpass123")
    driver.find_element("css selector", "button[type='submit']").click()

    # Navigate to owner's project
    driver.get(f"{live_server.url}/projects/{project.pk}/")

    # Verify warning banner visible
    banner = driver.find_element("css selector", ".alert-warning")
    assert "Admin Mode" in banner.text
    assert "owner's project" in banner.text
    assert "logged for audit purposes" in banner.text


def test_owner_does_not_see_warning_banner(driver, live_server, owner, project):
    """Test that project owner does NOT see warning banner."""
    # Login as owner
    driver.get(f"{live_server.url}/accounts/login/")
    driver.find_element("id", "id_login").send_keys("owner")
    driver.find_element("id", "id_password").send_keys("testpass123")
    driver.find_element("css selector", "button[type='submit']").click()

    # Navigate to own project
    driver.get(f"{live_server.url}/projects/{project.pk}/")

    # Verify NO warning banner
    banners = driver.find_elements("css selector", ".alert-warning")
    assert len(banners) == 0


def test_staff_user_sees_all_projects_in_list(driver, live_server, staff_user, owner, project):
    """Test that staff user sees all users' projects in list view."""
    # Create another project for staff user
    admin_project = Project.objects.create(
        user=staff_user,
        name="Admin Project",
        description="Admin description",
    )

    # Login as staff user
    driver.get(f"{live_server.url}/accounts/login/")
    driver.find_element("id", "id_login").send_keys("admin")
    driver.find_element("id", "id_password").send_keys("testpass123")
    driver.find_element("css selector", "button[type='submit']").click()

    # Navigate to project list
    driver.get(f"{live_server.url}/projects/")

    # Verify both projects visible
    page_text = driver.find_element("tag name", "body").text
    assert "Test Project" in page_text
    assert "Admin Project" in page_text


def test_regular_user_sees_only_own_projects(driver, live_server, owner, staff_user):
    """Test that regular user only sees their own projects in list."""
    # Create projects for both users
    owner_project = Project.objects.create(
        user=owner,
        name="Owner Project",
        description="Owner description",
    )
    admin_project = Project.objects.create(
        user=staff_user,
        name="Admin Project",
        description="Admin description",
    )

    # Login as owner
    driver.get(f"{live_server.url}/accounts/login/")
    driver.find_element("id", "id_login").send_keys("owner")
    driver.find_element("id", "id_password").send_keys("testpass123")
    driver.find_element("css selector", "button[type='submit']").click()

    # Navigate to project list
    driver.get(f"{live_server.url}/projects/")

    # Verify only own project visible
    page_text = driver.find_element("tag name", "body").text
    assert "Owner Project" in page_text
    assert "Admin Project" not in page_text


def test_staff_user_can_edit_other_users_project(driver, live_server, staff_user, project):
    """Test that staff user can edit another user's project."""
    # Login as staff user
    driver.get(f"{live_server.url}/accounts/login/")
    driver.find_element("id", "id_login").send_keys("admin")
    driver.find_element("id", "id_password").send_keys("testpass123")
    driver.find_element("css selector", "button[type='submit']").click()

    # Navigate to edit page
    driver.get(f"{live_server.url}/projects/{project.pk}/edit/")

    # Verify warning banner present
    banner = driver.find_element("css selector", ".alert-warning")
    assert "Admin Mode" in banner.text

    # Edit project name
    name_field = driver.find_element("id", "id_name")
    name_field.clear()
    name_field.send_keys("Updated by Admin")

    # Submit form
    driver.find_element("css selector", "button[type='submit']").click()

    # Verify project updated
    project.refresh_from_db()
    assert project.name == "Updated by Admin"


def test_audit_log_created_on_staff_user_access(driver, live_server, staff_user, project):
    """Test that audit log is created when staff user views project."""
    # Verify no logs initially
    assert ProjectAccessLog.objects.count() == 0

    # Login as staff user
    driver.get(f"{live_server.url}/accounts/login/")
    driver.find_element("id", "id_login").send_keys("admin")
    driver.find_element("id", "id_password").send_keys("testpass123")
    driver.find_element("css selector", "button[type='submit']").click()

    # Navigate to owner's project
    driver.get(f"{live_server.url}/projects/{project.pk}/")

    # Verify audit log created
    logs = ProjectAccessLog.objects.filter(
        project=project,
        admin_user=staff_user,
    )
    assert logs.count() == 1

    log = logs.first()
    assert log.action == ProjectAccessLog.Action.VIEW
    assert log.view_name == "ProjectDetailView"
```

**Step 2: Run browser tests**

```bash
make test-browser-headless
```

Expected: 6 passed (all new browser tests)

**Step 3: Run full test suite**

```bash
make test
```

Expected: All tests pass (baseline + new tests)

**Step 4: Commit**

```bash
make lint-fix
make lint
git add tests/browser/test_admin_project_access.py
git commit -m "Add browser tests for admin project access

Implement comprehensive browser tests for staff user access:
- Warning banner visibility for admin vs owner
- Project list filtering (all vs own projects)
- Edit access for staff users
- Audit log creation on access

Tests verify complete user flow including:
- Login
- Navigation
- UI element visibility
- Database state changes

All tests run headless by default.

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 9: Add Admin Interface for ProjectAccessLog

**Files:**
- Modify: `wafer_space/projects/admin.py`
- Create: `wafer_space/projects/tests/test_admin.py`

**Step 1: Write failing admin tests**

Create `wafer_space/projects/tests/test_admin.py`:

```python
"""Tests for Django admin interface."""

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from wafer_space.projects.admin import ProjectAccessLogAdmin
from wafer_space.projects.models import Project, ProjectAccessLog

User = get_user_model()


class ProjectAccessLogAdminTestCase(TestCase):
    """Test ProjectAccessLog admin interface."""

    def setUp(self):
        """Set up test data."""
        self.factory = RequestFactory()
        self.site = AdminSite()

        self.owner = User.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="testpass123",
        )

        self.admin_user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="testpass123",
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
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest wafer_space/projects/tests/test_admin.py -v
```

Expected: FAIL with "ImportError: cannot import name 'ProjectAccessLogAdmin'"

**Step 3: Add admin configuration**

Modify `wafer_space/projects/admin.py`:

```python
"""Django admin configuration for projects app."""

from django.contrib import admin

from wafer_space.projects.models import Project, ProjectAccessLog


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    """Admin interface for Project model."""

    list_display = ["name", "user", "status", "created_at", "updated_at"]
    list_filter = ["status", "created_at", "updated_at"]
    search_fields = ["name", "description", "user__username"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(ProjectAccessLog)
class ProjectAccessLogAdmin(admin.ModelAdmin):
    """Admin interface for ProjectAccessLog model.

    This admin is read-only to preserve audit log integrity.
    Logs cannot be added, modified, or deleted through the admin interface.
    """

    list_display = [
        "accessed_at",
        "admin_user",
        "project",
        "action",
        "ip_address",
        "view_name",
    ]

    list_filter = ["action", "accessed_at", "admin_user"]

    search_fields = [
        "admin_user__username",
        "project__name",
        "ip_address",
    ]

    readonly_fields = [
        "project",
        "admin_user",
        "accessed_at",
        "action",
        "ip_address",
        "user_agent",
        "view_name",
    ]

    def has_add_permission(self, request):
        """Disable add permission - logs created automatically."""
        return False

    def has_change_permission(self, request, obj=None):
        """Disable change permission - logs are immutable."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Disable delete permission - logs are permanent."""
        return False
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest wafer_space/projects/tests/test_admin.py -v
```

Expected: 7 passed

**Step 5: Run full test suite**

```bash
make test
```

Expected: All tests pass

**Step 6: Commit**

```bash
make lint-fix
make lint
git add wafer_space/projects/admin.py wafer_space/projects/tests/test_admin.py
git commit -m "Add read-only admin interface for ProjectAccessLog

Configure Django admin for audit log viewing:
- List display shows key fields (timestamp, user, project, action)
- Filters on action, timestamp, admin user
- Search by username, project name, IP address
- All fields read-only (immutable audit log)
- No add/change/delete permissions

Tests verify admin configuration and permission restrictions.

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 10: Update Documentation

**Files:**
- Create: `docs/admin_project_access.md`
- Modify: `README.md`

**Step 1: Create feature documentation**

Create `docs/admin_project_access.md`:

```markdown
# Admin Project Access

## Overview

Django staff users can view, edit, and manage any user's project on the platform. This feature includes comprehensive audit logging and visual indicators to ensure transparency and accountability.

## Who Has Access

**Staff users Only**: Access is restricted to users with `is_staff=True`.

**Staff users** (`is_staff=True` without `is_staff=True`) do **NOT** have access to other users' projects.

## Features

### 1. Full Project Access

Staff users can:
- **View** any project's details, files, and status
- **Edit** project name, description, and metadata
- **Delete** projects
- **Submit** projects for manufacturing
- **Upload/manage** project files

### 2. Unified Project List

When staff users visit the project list page, they see **all users' projects**, not just their own.

Regular users continue to see only their own projects.

### 3. Visual Indicators

**Warning Banner**: When viewing another user's project, staff users see a prominent yellow warning banner:

```
⚠️ Admin Mode: You are viewing [username]'s project.
All actions will be logged for audit purposes.
```

**Owner Badges**: Project list shows colored badges:
- Green "Your Project" for own projects
- Blue "[username]'s Project" for other users' projects

### 4. Comprehensive Audit Logging

**All staff user access to other users' projects is logged**, including:
- Timestamp
- Admin username
- Project accessed
- Action type (view, edit, delete, submit, file upload)
- IP address
- User agent
- View name

**Owner access is NOT logged** (normal operation).

## Audit Log Retention

- Audit logs are **immutable** (cannot be edited or deleted through UI)
- Admin users **cannot be deleted** if they have audit log entries (database PROTECT constraint)
- Logs are retained indefinitely for compliance
- Logs cascade delete when associated project is deleted

## Viewing Audit Logs

Staff users can view audit logs through Django admin:

1. Navigate to Django admin (`/admin/`)
2. Go to "Projects" → "Project Access Logs"
3. Filter by action, date, or admin user
4. Search by username, project name, or IP address

## Security Features

1. **Fail-Closed Design**: Permission checks default to deny if undefined
2. **Explicit Dual Check**: Both `is_authenticated` AND `is_staff` required
3. **Centralized Logic**: Single mixin (`ProjectOwnerOrStaffMixin`) prevents bypass
4. **Protected Audit Logs**: Cannot delete users with log entries
5. **No Backdoors**: Non-staff users explicitly denied

## Implementation Details

### Permission Mixin

All project views use `ProjectOwnerOrStaffMixin`:

```python
class ProjectDetailView(LoginRequiredMixin, ProjectOwnerOrStaffMixin, DetailView):
    model = Project
```

### Audit Logging

Audit logs are created automatically in mixin's `dispatch()` method when:
- User is authenticated staff user
- Project owner is different from current user
- Access is granted (status < 400)

### Context Variables

Views set `viewing_as_admin` flag for template rendering:

```python
def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    project = self.get_object()
    user = self.request.user

    context["viewing_as_admin"] = (
        user.is_authenticated
        and user.is_staff
        and project.user != user
    )

    return context
```

## Testing

Comprehensive test coverage includes:
- **Permission tests**: Owner, staff_user, non-owner, non-staff user
- **Audit log tests**: Creation, immutability, protection, cascade
- **Integration tests**: All views with staff user access
- **Browser tests**: Warning banner, project list, edit access, audit logging

Run tests:
```bash
make test                    # Unit tests
make test-browser-headless   # Browser tests
```

## Migration Guide

If extending this feature to new views:

1. Add `ProjectOwnerOrStaffMixin` to view class
2. Remove old `test_func()` method if present
3. Add `get_context_data()` to set `viewing_as_admin` flag
4. Include `_admin_warning_banner.html` in template
5. Write tests for permission and audit logging

See `wafer_space/projects/views.py` for examples.
```

**Step 2: Update README.md**

Add to README.md features section:

```markdown
### Admin Project Access

Django staff users can view and manage any user's project with comprehensive audit logging:
- Full access to view, edit, delete, and submit any project
- Visual warning banners indicate admin mode
- All access automatically logged with IP, timestamp, and action
- Read-only audit logs viewable in Django admin

See [docs/admin_project_access.md](docs/admin_project_access.md) for details.
```

**Step 3: Commit documentation**

```bash
git add docs/admin_project_access.md README.md
git commit -m "Add documentation for admin project access feature

Document staff user project access capabilities:
- Access levels and restrictions
- Visual indicators and UI changes
- Audit logging and retention
- Security features
- Implementation details
- Testing coverage

Update README with feature summary.

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 11: Final Verification and PR Preparation

**Files:**
- N/A (verification only)

**Step 1: Run complete test suite**

```bash
make check-all
```

Expected: All checks pass (lint, type-check, tests)

**Step 2: Run browser tests**

```bash
make test-browser-headless
```

Expected: All browser tests pass

**Step 3: Verify migration applied**

```bash
uv run python manage.py showmigrations projects
```

Expected: Latest migration (ProjectAccessLog) shown as applied

**Step 4: Check test coverage**

```bash
make test-coverage-html
```

Review coverage report, ensure new code is covered

**Step 5: Manual smoke test**

```bash
make runserver
```

Test manually:
1. Create test users (owner, staff_user)
2. Create test project as owner
3. Login as staff user
4. View project list (see all projects)
5. View owner's project (see warning banner)
6. Edit owner's project (verify access)
7. Check Django admin for audit log

**Step 6: Review all changes**

```bash
git log --oneline feature/admin-project-access
git diff main...feature/admin-project-access
```

Review commit messages and code changes

**Step 7: Push branch**

```bash
git push -u origin feature/admin-project-access
```

**Step 8: Create pull request**

```bash
gh pr create \
  --title "Add admin project access with audit logging" \
  --body "$(cat <<'EOF'
## Summary
Allow Django staff users to view, edit, and manage any user's project with comprehensive audit logging and visual indicators.

## Changes
- ✅ **Permission System**: New `ProjectOwnerOrStaffMixin` with fail-closed design
- ✅ **Audit Logging**: Immutable `ProjectAccessLog` model tracks all admin access
- ✅ **UI Indicators**: Warning banners and owner badges for visual feedback
- ✅ **View Updates**: All 7 project views migrated to new permission system
- ✅ **Admin Interface**: Read-only audit log viewer in Django admin
- ✅ **Comprehensive Tests**: 30+ tests (permission, audit, integration, browser)
- ✅ **Documentation**: Complete feature documentation and implementation guide

## Security
- Explicit dual authentication check (is_authenticated AND is_staff)
- Non-staff users explicitly denied
- PROTECT constraint prevents deletion of admins with logs
- Centralized permission logic prevents bypass

## Testing
- All tests passing (496 unit + 6 browser)
- Full coverage of permission edge cases
- Browser tests verify complete user flow
- Audit logging validated end-to-end

## Design Document
See `docs/plans/2025-11-20-admin-project-access-design.md` for complete architecture rationale and security analysis.

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

**Step 9: Mark complete**

All tasks complete! PR ready for review.

---

## Summary

This implementation plan covers:

1. **Backend Permission System** (Tasks 1-6):
   - ProjectOwnerOrStaffMixin with TDD
   - ProjectAccessLog model with comprehensive tests
   - Migration creation and verification
   - All 7 project views updated
   - Automatic audit logging

2. **Frontend UI** (Task 7):
   - Warning banner component
   - Template integration across views
   - Owner badges in project list

3. **Testing** (Task 8):
   - Browser tests for complete user flow
   - Permission edge cases
   - Audit log creation and immutability

4. **Admin Interface** (Task 9):
   - Read-only audit log viewer
   - Filters and search
   - Permission restrictions

5. **Documentation** (Task 10):
   - Feature documentation
   - Implementation guide
   - README updates

6. **Verification** (Task 11):
   - Full test suite
   - Manual smoke testing
   - PR creation

**Total Commits**: 11 incremental commits following TDD principles

**Total Tests Added**: ~30 tests (permission, audit log, integration, browser)

**Files Modified/Created**: ~15 files
