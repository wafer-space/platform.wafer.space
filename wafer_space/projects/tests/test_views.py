"""Tests for project views."""

from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.contrib.messages import get_messages
from django.test import Client
from django.test import TestCase
from django.urls import reverse

from wafer_space.projects.models import CheckExecutionContext
from wafer_space.projects.models import DownloadAttempt
from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.projects.security import SecurityValidationError
from wafer_space.shuttles.models import Shuttle
from wafer_space.users.models import User

from .constants import EXPECTED_USER_PROJECTS
from .constants import FIVE_MB
from .constants import HTTP_FORBIDDEN
from .constants import HTTP_FOUND
from .constants import HTTP_METHOD_NOT_ALLOWED
from .constants import HTTP_NOT_FOUND
from .constants import HTTP_OK
from .constants import PROGRESS_COMPLETE
from .constants import PROGRESS_HALF
from .constants import TEN_MB
from .constants import TEST_PASSWORD


@pytest.mark.django_db
class TestProjectListView(TestCase):
    """Test ProjectListView."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )
        self.other_user = User.objects.create_user(
            username="otheruser",
            email="other@example.com",
            password=TEST_PASSWORD,
        )

        # Create projects for both users
        self.project1 = Project.objects.create(
            user=self.user,
            name="Project 1",
            description="First project",
        )
        self.project2 = Project.objects.create(
            user=self.user,
            name="Project 2",
            description="Second project",
        )
        self.other_project = Project.objects.create(
            user=self.other_user,
            name="Other Project",
            description="Other user's project",
        )

    def test_requires_login(self):
        """Test that view requires login."""
        url = reverse("projects:list")
        response = self.client.get(url)

        # Should redirect to login
        assert response.status_code == HTTP_FOUND
        # Check redirect location (use Location header for type safety)
        assert "/accounts/login/" in response["Location"]

    def test_shows_only_user_projects(self):
        """Test that view shows only current user's projects."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:list")
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert "projects" in response.context
        projects = response.context["projects"]

        # Should show user's projects
        assert len(projects) == EXPECTED_USER_PROJECTS
        assert self.project1 in projects
        assert self.project2 in projects
        assert self.other_project not in projects


@pytest.mark.django_db
class TestProjectDetailView(TestCase):
    """Test ProjectDetailView."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )
        self.other_user = User.objects.create_user(
            username="otheruser",
            email="other@example.com",
            password=TEST_PASSWORD,
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test project",
        )

    def test_requires_login(self):
        """Test that view requires login."""
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        # Should redirect to login
        assert response.status_code == HTTP_FOUND
        # Check redirect location (use Location header for type safety)
        assert "/accounts/login/" in response["Location"]

    def test_owner_can_view(self):
        """Test that owner can view project."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert response.context["project"] == self.project

    def test_non_owner_cannot_view(self):
        """Test that non-owner cannot view project."""
        self.client.login(username="otheruser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        # Should return 403 Forbidden
        assert response.status_code == HTTP_FORBIDDEN

    def test_includes_active_file_in_context(self):
        """Test that active file is included in context."""
        # Create active file
        active_file = project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
        )
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.COMPLETED,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        # Active file is provided as in_progress_file in the context
        assert response.context["in_progress_file"] == active_file

    def test_project_detail_staff_access(self):
        """Test that staff user can access any project detail view."""
        staff_user = User.objects.create_user(
            username="staff",
            email="staff@example.com",
            password=TEST_PASSWORD,
            is_staff=True,
        )
        self.client.force_login(staff_user)

        response = self.client.get(
            reverse("projects:detail", kwargs={"pk": self.project.pk}),
        )
        assert response.status_code == HTTP_OK
        assert response.context["project"] == self.project
        assert response.context["viewing_as_admin"] is True


@pytest.mark.django_db
class TestProjectCreateView(TestCase):
    """Test ProjectCreateView."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )
        self.shuttle = Shuttle.objects.create(
            name="G800",
            description="Test Shuttle",
            status=Shuttle.Status.OPEN,
            max_slots=10,
            available_slots=10,
        )

    def test_requires_login(self):
        """Test that view requires login."""
        url = reverse("projects:create")
        response = self.client.get(url)

        # Should redirect to login
        assert response.status_code == HTTP_FOUND
        # Check redirect location (use Location header for type safety)
        assert "/accounts/login/" in response["Location"]

    def test_displays_form(self):
        """Test that GET displays the form."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:create")
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert "form" in response.context

    def test_creates_project(self):
        """Test that POST creates a project."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:create")

        form_data = {
            "name": "New Project",
            "description": "New project description",
            "shuttle": self.shuttle.pk,
            "project_id": "TEST",
            "slot_size": "1x1",
        }
        response = self.client.post(url, form_data)

        # Should redirect to detail page
        assert response.status_code == HTTP_FOUND

        # Verify project was created
        assert Project.objects.count() == 1
        project = Project.objects.first()
        assert project is not None
        assert project.name == "New Project"
        assert project.description == "New project description"
        assert project.user == self.user
        assert project.shuttle == self.shuttle
        assert project.project_id == "TEST"
        assert project.slot_size == "1x1"

        # Verify success message
        messages = list(get_messages(response.wsgi_request))
        assert len(messages) == 1
        assert "created successfully" in str(messages[0])


@pytest.mark.django_db
class TestProjectUpdateView(TestCase):
    """Test ProjectUpdateView."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )
        self.other_user = User.objects.create_user(
            username="otheruser",
            email="other@example.com",
            password=TEST_PASSWORD,
        )
        self.shuttle = Shuttle.objects.create(
            name="G800",
            description="Test Shuttle",
            status=Shuttle.Status.OPEN,
            max_slots=10,
            available_slots=10,
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test project",
            shuttle=self.shuttle,
            project_id="ABCD",
        )

    def test_requires_login(self):
        """Test that view requires login."""
        url = reverse("projects:update", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        # Should redirect to login
        assert response.status_code == HTTP_FOUND
        # Check redirect location (use Location header for type safety)
        assert "/accounts/login/" in response["Location"]

    def test_owner_can_update(self):
        """Test that owner can update project."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:update", kwargs={"pk": self.project.pk})

        form_data = {
            "name": "Updated Project",
            "description": "Updated description",
            "shuttle": self.shuttle.pk,
            "project_id": "ABCD",
            "slot_size": "0p5x1",
        }
        response = self.client.post(url, form_data)

        # Should redirect
        assert response.status_code == HTTP_FOUND

        # Verify project was updated
        self.project.refresh_from_db()
        assert self.project.name == "Updated Project"
        assert self.project.description == "Updated description"
        assert self.project.slot_size == "0p5x1"

    def test_non_owner_cannot_update(self):
        """Test that non-owner cannot update project."""
        self.client.login(username="otheruser", password=TEST_PASSWORD)
        url = reverse("projects:update", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        # Should return 403 Forbidden
        assert response.status_code == HTTP_FORBIDDEN


@pytest.mark.django_db
class TestProjectDeleteView(TestCase):
    """Test ProjectDeleteView."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )
        self.other_user = User.objects.create_user(
            username="otheruser",
            email="other@example.com",
            password=TEST_PASSWORD,
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test project",
        )

    def test_requires_login(self):
        """Test that view requires login."""
        url = reverse("projects:delete", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        # Should redirect to login
        assert response.status_code == HTTP_FOUND
        # Check redirect location (use Location header for type safety)
        assert "/accounts/login/" in response["Location"]

    def test_owner_can_delete(self):
        """Test that owner can delete project."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:delete", kwargs={"pk": self.project.pk})

        response = self.client.post(url)

        # Should redirect to list page
        assert response.status_code == HTTP_FOUND

        # Verify project was deleted
        assert Project.objects.count() == 0

    def test_non_owner_cannot_delete(self):
        """Test that non-owner cannot delete project."""
        self.client.login(username="otheruser", password=TEST_PASSWORD)
        url = reverse("projects:delete", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        # Should return 403 Forbidden
        assert response.status_code == HTTP_FORBIDDEN


@pytest.mark.django_db
class TestProjectFileSubmitURLView(TestCase):
    """Test ProjectFileSubmitURLView."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )
        self.other_user = User.objects.create_user(
            username="otheruser",
            email="other@example.com",
            password=TEST_PASSWORD,
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test project",
        )

    def test_requires_login(self):
        """Test that view requires login."""
        url = reverse("projects:submit_url", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        # Should redirect to login
        assert response.status_code == HTTP_FOUND
        # Check redirect location (use Location header for type safety)
        assert "/accounts/login/" in response["Location"]

    def test_owner_can_view_form(self):
        """Test that owner can view form."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:submit_url", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert "form" in response.context

    def test_non_owner_cannot_view_form(self):
        """Test that non-owner cannot view form."""
        self.client.login(username="otheruser", password=TEST_PASSWORD)
        url = reverse("projects:submit_url", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        # Should return 403 Forbidden
        assert response.status_code == HTTP_FORBIDDEN

    @patch("wafer_space.projects.views.ProjectFileService.submit_file_from_url")
    def test_submit_url_success(self, mock_submit):
        """Test successful URL submission."""
        # Mock service layer
        mock_file = Mock(spec=ProjectFile)
        mock_file.original_filename = "test.gds"
        mock_metadata = {
            "url_rewritten": True,
            "rewrite_reason": "Converted GitHub blob URL",
            "file_size": 1048576,
        }
        mock_submit.return_value = (mock_file, mock_metadata)

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:submit_url", kwargs={"pk": self.project.pk})

        form_data = {
            "url": "https://github.com/user/repo/blob/main/file.gds",
            "expected_hash_md5": "abc123def456789012345678901234ab",
            "expected_hash_sha1": "",
        }
        response = self.client.post(url, form_data)

        # Should redirect to detail page
        assert response.status_code == HTTP_FOUND

        # Verify service was called
        mock_submit.assert_called_once()

    @patch("wafer_space.projects.views.ProjectFileService.submit_file_from_url")
    def test_submit_url_security_error(self, mock_submit):
        """Test URL submission with security error."""
        # Mock security validation error
        error_msg = "Cannot download from localhost"
        mock_submit.side_effect = SecurityValidationError(error_msg)

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:submit_url", kwargs={"pk": self.project.pk})

        form_data = {
            "url": "http://localhost/file.gds",
            "expected_hash_md5": "abc123def456789012345678901234ab",
            "expected_hash_sha1": "",
        }
        response = self.client.post(url, form_data)

        # Should re-render form with error
        assert response.status_code == HTTP_OK
        messages = list(get_messages(response.wsgi_request))
        assert any("Security validation failed" in str(m) for m in messages)


@pytest.mark.django_db
class TestProjectFileProgressView(TestCase):
    """Test ProjectFileProgressView."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )
        self.other_user = User.objects.create_user(
            username="otheruser",
            email="other@example.com",
            password=TEST_PASSWORD,
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test project",
        )

    def test_requires_login(self):
        """Test that view requires login."""
        url = reverse("projects:progress", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        # Should redirect to login
        assert response.status_code == HTTP_FOUND
        # Check redirect location (use Location header for type safety)
        assert "/accounts/login/" in response["Location"]

    def test_non_owner_cannot_view_progress(self):
        """Test that non-owner cannot view progress."""
        self.client.login(username="otheruser", password=TEST_PASSWORD)
        url = reverse("projects:progress", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        # Should return 403 Forbidden
        assert response.status_code == HTTP_FORBIDDEN

    def test_no_active_file_returns_404(self):
        """Test that no active file returns 404."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:progress", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        # Should return 404
        assert response.status_code == HTTP_NOT_FOUND
        data = response.json()
        assert "error" in data

    @patch("wafer_space.projects.views.ProjectFileService.get_download_progress")
    def test_returns_progress_json(self, mock_progress):
        """Test that view returns progress as JSON."""
        # Create active file
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
        )

        # Create download attempt
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.DOWNLOADING,
        )

        # Mock progress
        mock_progress.return_value = {
            "status": "downloading",
            "progress": PROGRESS_HALF,
            "current": FIVE_MB,
            "total": TEN_MB,
            "message": "Downloaded 4,718,592 of 10,485,760 bytes",
        }

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:progress", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        data = response.json()
        assert data["status"] == "downloading"
        assert data["progress"] == PROGRESS_HALF
        assert data["current"] == FIVE_MB
        assert data["total"] == TEN_MB


@pytest.mark.django_db
class TestProjectSubmitView(TestCase):
    """Test ProjectSubmitView."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )
        self.other_user = User.objects.create_user(
            username="otheruser",
            email="other@example.com",
            password=TEST_PASSWORD,
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test project",
            status=Project.Status.DRAFT,
        )

    def test_requires_login(self):
        """Test that view requires login."""
        url = reverse("projects:submit", kwargs={"pk": self.project.pk})
        response = self.client.post(url)

        # Should redirect to login
        assert response.status_code == HTTP_FOUND
        # Check redirect location (use Location header for type safety)
        assert "/accounts/login/" in response["Location"]

    def test_requires_ownership(self):
        """Test that only owner can submit project."""
        self.client.login(username="otheruser", password=TEST_PASSWORD)
        url = reverse("projects:submit", kwargs={"pk": self.project.pk})
        response = self.client.post(url)

        # Should return 403 Forbidden
        assert response.status_code == HTTP_FORBIDDEN

    @patch("wafer_space.projects.tasks.check_process_job.delay")
    def test_successful_submission(self, mock_task):
        """Test successful project submission."""
        mock_task.return_value = Mock(id="task-123")

        # Create completed and verified file
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            hash_verified=True,
        )
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.COMPLETED,
        )

        # Mark as manufacturable (simulates completed check via mark_finished)
        self.project.is_manufacturable = True
        self.project.status = Project.Status.MANUFACTURABLE
        self.project.save()

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:submit", kwargs={"pk": self.project.pk})
        response = self.client.post(url)

        # Should redirect to project detail
        assert response.status_code == HTTP_FOUND
        detail_url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        # Check redirect location (use Location header for type safety)
        assert response["Location"] == detail_url

        # Verify project was submitted
        self.project.refresh_from_db()
        assert self.project.status == Project.Status.SUBMITTED
        assert self.project.submitted_at is not None

        # Verify success message
        messages = list(get_messages(response.wsgi_request))
        assert len(messages) == 1
        assert "submitted successfully" in str(messages[0]).lower()

    def test_submission_fails_without_active_file(self):
        """Test that submission fails without active file."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:submit", kwargs={"pk": self.project.pk})
        response = self.client.post(url)

        # Should redirect back to project detail
        assert response.status_code == HTTP_FOUND

        # Verify project was NOT submitted
        self.project.refresh_from_db()
        assert self.project.status == Project.Status.DRAFT
        assert self.project.submitted_at is None

        # Verify error message
        messages = list(get_messages(response.wsgi_request))
        assert len(messages) == 1
        assert "no active file" in str(messages[0]).lower()

    def test_submission_fails_with_pending_download(self):
        """Test that submission fails with pending download."""
        ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:submit", kwargs={"pk": self.project.pk})
        response = self.client.post(url)

        # Should redirect back to project detail
        assert response.status_code == HTTP_FOUND

        # Verify project was NOT submitted
        self.project.refresh_from_db()
        assert self.project.status == Project.Status.DRAFT

        # Verify error message mentions download not completed
        messages = list(get_messages(response.wsgi_request))
        assert len(messages) == 1
        message_text = str(messages[0]).lower()
        assert "download" in message_text
        assert "not completed" in message_text or "pending" in message_text

    def test_submission_fails_with_failed_download(self):
        """Test that submission fails with failed download."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            download_error="Download failed",
        )
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.FAILED,
            download_error="Download failed",
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:submit", kwargs={"pk": self.project.pk})
        response = self.client.post(url)

        # Should redirect back to project detail
        assert response.status_code == HTTP_FOUND

        # Verify project was NOT submitted
        self.project.refresh_from_db()
        assert self.project.status == Project.Status.DRAFT

        # Verify error message
        messages = list(get_messages(response.wsgi_request))
        assert len(messages) == 1
        assert "download" in str(messages[0]).lower()

    def test_submission_fails_with_unverified_hash(self):
        """Test that submission fails with unverified hash."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            hash_verified=False,
        )
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.COMPLETED,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:submit", kwargs={"pk": self.project.pk})
        response = self.client.post(url)

        # Should redirect back to project detail
        assert response.status_code == HTTP_FOUND

        # Verify project was NOT submitted
        self.project.refresh_from_db()
        assert self.project.status == Project.Status.DRAFT

        # Verify error message
        messages = list(get_messages(response.wsgi_request))
        assert len(messages) == 1
        assert "hash" in str(messages[0]).lower()

    def test_submission_fails_if_already_submitted(self):
        """Test that submission fails if already submitted."""
        # Create completed file
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            hash_verified=True,
        )
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.COMPLETED,
        )

        # Mark as manufacturable (simulates completed check via mark_finished)
        self.project.is_manufacturable = True
        self.project.status = Project.Status.MANUFACTURABLE
        self.project.save()

        # Submit once
        self.project.submit()
        first_submitted_at = self.project.submitted_at

        # Try to submit again
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:submit", kwargs={"pk": self.project.pk})
        response = self.client.post(url)

        # Should redirect back to project detail
        assert response.status_code == HTTP_FOUND

        # Verify submitted_at didn't change
        self.project.refresh_from_db()
        assert self.project.submitted_at == first_submitted_at

        # Verify error message
        messages = list(get_messages(response.wsgi_request))
        assert len(messages) == 1
        assert "already" in str(messages[0]).lower()

    @patch("wafer_space.projects.tasks.check_process_job.delay")
    def test_prevents_double_submission_race_condition(self, mock_task):
        """Test that double submission is prevented even with race condition."""
        mock_task.return_value = Mock(id="task-123")

        # Create completed file
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            hash_verified=True,
        )
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.COMPLETED,
        )

        # Mark as manufacturable (simulates completed check via mark_finished)
        self.project.is_manufacturable = True
        self.project.status = Project.Status.MANUFACTURABLE
        self.project.save()

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:submit", kwargs={"pk": self.project.pk})

        # First submission
        response1 = self.client.post(url)
        assert response1.status_code == HTTP_FOUND

        # Second submission (simulating race condition)
        response2 = self.client.post(url)
        assert response2.status_code == HTTP_FOUND

        # Verify only submitted once
        self.project.refresh_from_db()
        assert self.project.status == Project.Status.SUBMITTED

        # Second request should have error message
        messages = list(get_messages(response2.wsgi_request))
        assert any("already" in str(m).lower() for m in messages)


@pytest.mark.django_db
class TestEnhancedProgressDashboard(TestCase):
    """Test enhanced progress dashboard features."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test project",
        )

    def test_detail_view_shows_progress_flag_when_downloading(self):
        """Test that detail view sets show_progress flag when downloading."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
        )

        # Create download attempt
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.DOWNLOADING,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert response.context["show_progress"] is True
        assert "progress" in response.context

    def test_detail_view_shows_progress_flag_when_pending(self):
        """Test that detail view sets show_progress flag when pending."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
        )

        # Create download attempt
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.PENDING,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert response.context["show_progress"] is True
        assert "progress" in response.context

    def test_detail_view_shows_progress_when_task_queued_no_attempt_yet(self):
        """Test show_progress is True when task queued but DownloadAttempt not created.

        This reproduces the bug where polling didn't start after URL submission:
        - User submits URL → ProjectFile created with download_task_id
        - User redirected to detail page
        - DownloadAttempt doesn't exist yet (created inside Celery task)
        - Before fix: show_progress was False → no polling JavaScript
        - After fix: show_progress is True → polling starts immediately

        VERIFIED: This test FAILS without the fix (show_progress is False)
                  and PASSES with the fix (show_progress is True)
        """
        ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            download_task_id="celery-task-123",  # Task dispatched
        )
        # Intentionally NOT creating DownloadAttempt to simulate race condition

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        # This assertion would FAIL before the fix
        assert response.context["show_progress"] is True
        assert "progress" in response.context
        # Verify polling JavaScript is included in the response
        assert b"Progress Polling" in response.content

    def test_detail_view_shows_error_flag_when_failed(self):
        """Test that detail view sets show_error flag when download failed."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            download_error="Connection timeout",
        )

        # Create download attempt
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.FAILED,
            download_error="Connection timeout",
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert response.context["show_error"] is True
        assert response.context["error_message"] == "Connection timeout"

    def test_detail_view_no_progress_when_completed(self):
        """Test that detail view doesn't set show_progress when completed."""
        ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        show_progress = response.context.get("show_progress", False)
        assert not show_progress

    @patch("wafer_space.projects.views.ProjectFileService.get_download_progress")
    def test_progress_view_returns_error_field_when_failed(self, mock_progress):
        """Test that progress view includes error field when download failed."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            download_error="Network error occurred",
        )

        # Create download attempt
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.FAILED,
            download_error="Network error occurred",
        )

        mock_progress.return_value = {
            "status": "failed",
            "progress": 0,
            "current": 0,
            "total": TEN_MB,
            "message": "Download failed",
        }

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:progress", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        data = response.json()
        assert data["status"] == "failed"
        assert "error" in data
        assert data["error"] == "Network error occurred"

    @patch("wafer_space.projects.views.ProjectFileService.get_download_progress")
    def test_progress_view_with_pending_status(self, mock_progress):
        """Test progress view with pending download status."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
        )

        # Create download attempt
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.PENDING,
        )

        mock_progress.return_value = {
            "status": "pending",
            "progress": 0,
            "current": 0,
            "total": TEN_MB,
            "message": "Download pending - waiting to start",
        }

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:progress", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        data = response.json()
        assert data["status"] == "pending"
        assert data["progress"] == 0
        assert "pending" in data["message"].lower()

    @patch("wafer_space.projects.views.ProjectFileService.get_download_progress")
    def test_progress_view_with_completed_status(self, mock_progress):
        """Test progress view with completed download status."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            file_size=TEN_MB,
        )

        # Create download attempt
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.COMPLETED,
        )

        mock_progress.return_value = {
            "status": "completed",
            "progress": 100,
            "current": TEN_MB,
            "total": TEN_MB,
            "message": "Download completed successfully",
        }

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:progress", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        data = response.json()
        assert data["status"] == "completed"
        assert data["progress"] == PROGRESS_COMPLETE
        assert data["current"] == TEN_MB
        assert data["total"] == TEN_MB


@pytest.mark.django_db
class TestProjectDetailViewManufacturabilityCheck(TestCase):
    """Test ProjectDetailView with manufacturability check integration."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test Description",
        )
        self.project_file = ProjectFile.objects.create(
            project=self.project,
            original_filename="test.gds",
            source_url="https://example.com/test.gds",
            is_active=True,
        )

    def test_detail_view_includes_check_when_check_exists(self):
        """Test that detail view includes check in context."""
        # Create a manufacturability check
        ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        # Log in and access detail view
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert "check" in response.context
        check = response.context["check"]
        assert check is not None
        assert check.status == ManufacturabilityCheck.Status.PENDING

    def test_detail_view_check_none_when_no_check(self):
        """Test that check is None when no check exists."""
        # Log in and access detail view
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert "check" in response.context
        assert response.context["check"] is None

    def test_detail_view_shows_completed_check(self):
        """Test that detail view shows completed check with results."""
        # Create a completed check
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        check.mark_dispatched(celery_job_id="test-job-id")
        exec_context = CheckExecutionContext(
            celery_worker_pid=12345,
            celery_worker_hostname="test-worker",
            docker_container_id="test-container-id",
            docker_image="test-image:latest",
            docker_image_digest="sha256:test",
            docker_command="docker run ...",
        )
        check.mark_running(context=exec_context)
        check.mark_finished(
            is_manufacturable=False,
            errors=[{"message": "Error 1"}, {"message": "Error 2"}],
            warnings=[{"message": "Warning 1"}],
            processing_logs="Test processing logs",
        )

        # Log in and access detail view
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        check = response.context["check"]
        assert check is not None
        assert check.status == ManufacturabilityCheck.Status.FINISHED
        assert check.is_manufacturable is False
        expected_errors = [{"message": "Error 1"}, {"message": "Error 2"}]
        assert check.errors == expected_errors
        assert check.warnings == [{"message": "Warning 1"}]

    def test_detail_view_shows_error_message_to_staff(self):
        """Test that staff users can see system error messages."""
        # Create a check with error status and error_message
        ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.ERROR,
            error_message="Docker container failed to start: OOM killed",
        )

        # Create staff user and log in
        User.objects.create_user(
            username="staffuser",
            email="staff@example.com",
            password=TEST_PASSWORD,
            is_staff=True,
        )
        self.client.login(username="staffuser", password=TEST_PASSWORD)

        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert b"System Error (Staff Only)" in response.content
        assert b"Docker container failed to start: OOM killed" in response.content

    def test_detail_view_hides_error_message_from_non_staff(self):
        """Test that non-staff users cannot see system error messages."""
        # Create a check with error status and error_message
        ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.ERROR,
            error_message="Docker container failed to start: OOM killed",
        )

        # Log in as the regular project owner (non-staff)
        self.client.login(username="testuser", password=TEST_PASSWORD)

        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        # The error message section should not be visible to non-staff
        assert b"System Error (Staff Only)" not in response.content
        # The actual error message content should not be visible either
        assert b"Docker container failed to start: OOM killed" not in response.content


@pytest.mark.django_db
class TestManufacturabilityCheckCancelView(TestCase):
    """Test ManufacturabilityCheckCancelView."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )
        self.other_user = User.objects.create_user(
            username="otheruser",
            email="other@example.com",
            password=TEST_PASSWORD,
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test project",
        )
        self.project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
        )

    def test_cancel_check_success(self):
        """Test successfully requesting cancellation of a check."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
            celery_job_id="celery-task-123",
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:cancel_check", kwargs={"pk": self.project.pk})
        response = self.client.post(url)

        assert response.status_code == HTTP_FOUND
        check.refresh_from_db()
        # Should be CANCELLING, not CANCELLED (cleanup task will complete it)
        assert check.status == ManufacturabilityCheck.Status.CANCELLING

    def test_cancel_check_processing_success(self):
        """Test successfully requesting cancellation of a processing check."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
            celery_job_id="celery-task-456",
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:cancel_check", kwargs={"pk": self.project.pk})
        response = self.client.post(url)

        assert response.status_code == HTTP_FOUND
        check.refresh_from_db()
        # Should be CANCELLING, not CANCELLED (cleanup task will complete it)
        assert check.status == ManufacturabilityCheck.Status.CANCELLING

    def test_cancel_check_already_completed(self):
        """Test cancelling already completed check shows warning."""
        ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:cancel_check", kwargs={"pk": self.project.pk})
        response = self.client.post(url, follow=True)

        assert response.status_code == HTTP_OK
        messages_list = list(response.context["messages"])
        assert len(messages_list) == 1
        assert "could not be cancelled" in str(messages_list[0]).lower()

    def test_cancel_check_no_active_file(self):
        """Test cancelling with no active file shows error."""
        self.project_file.is_active = False
        self.project_file.save()

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:cancel_check", kwargs={"pk": self.project.pk})
        response = self.client.post(url, follow=True)

        assert response.status_code == HTTP_OK
        messages_list = list(response.context["messages"])
        assert len(messages_list) == 1
        assert "no active file" in str(messages_list[0]).lower()

    def test_cancel_check_no_check_exists(self):
        """Test cancelling with no check shows error."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:cancel_check", kwargs={"pk": self.project.pk})
        response = self.client.post(url, follow=True)

        assert response.status_code == HTTP_OK
        messages_list = list(response.context["messages"])
        assert len(messages_list) == 1
        assert "no manufacturability check" in str(messages_list[0]).lower()

    def test_cancel_check_requires_authentication(self):
        """Test that cancel requires authentication."""
        url = reverse("projects:cancel_check", kwargs={"pk": self.project.pk})
        response = self.client.post(url)

        assert response.status_code == HTTP_FOUND
        assert "/accounts/login/" in response["Location"]

    def test_cancel_check_requires_ownership(self):
        """Test that only project owner can cancel check."""
        ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        # Log in as other user
        self.client.login(username="otheruser", password=TEST_PASSWORD)
        url = reverse("projects:cancel_check", kwargs={"pk": self.project.pk})
        response = self.client.post(url)

        # Should be forbidden (403)
        assert response.status_code == HTTP_FORBIDDEN

    def test_cancel_check_get_not_allowed(self):
        """Test that GET requests are not allowed."""
        ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:cancel_check", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        # GET should return 405 Method Not Allowed
        assert response.status_code == HTTP_METHOD_NOT_ALLOWED


@pytest.mark.django_db
class TestProjectFileSubmitURLViewWarning(TestCase):
    """Test submit-url page shows warning when check is running."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test project",
        )
        self.project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
        )

    def test_submit_url_shows_warning_for_queued_check(self):
        """Test submit URL page shows warning when queued check exists."""
        ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:submit_url", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert "running_check" in response.context
        assert response.context["running_check"] is not None
        assert b"will be cancelled" in response.content.lower() or (
            b"Will Be Cancelled" in response.content
        )

    def test_submit_url_shows_warning_for_processing_check(self):
        """Test submit URL page shows warning when processing check exists."""
        ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:submit_url", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert response.context["running_check"] is not None

    def test_submit_url_no_warning_for_completed_check(self):
        """Test submit URL page has no warning when check is completed."""
        ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:submit_url", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert response.context["running_check"] is None

    def test_submit_url_no_warning_when_no_check(self):
        """Test submit URL page has no warning when no check exists."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:submit_url", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert response.context["running_check"] is None


@pytest.mark.django_db
class TestProjectListViewStaff(TestCase):
    """Test ProjectListView with staff user access."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.owner = User.objects.create_user(
            username="owner",
            email="owner@example.com",
            password=TEST_PASSWORD,
        )
        self.project = Project.objects.create(
            user=self.owner,
            name="Owner Project",
            description="Owner description",
        )

    def test_project_list_shows_only_own_projects_for_regular_user(self):
        """Test that regular users only see their own projects in list."""
        # Create another user with a project
        other_user = User.objects.create_user(
            username="other",
            email="other@example.com",
            password=TEST_PASSWORD,
        )
        other_project = Project.objects.create(
            user=other_user,
            name="Other Project",
            description="Other description",
        )

        self.client.force_login(self.owner)
        response = self.client.get(reverse("projects:list"))

        assert response.status_code == HTTP_OK
        projects = list(response.context["object_list"])
        assert self.project in projects
        assert other_project not in projects

    def test_project_list_shows_all_projects_for_staff(self):
        """Test that staff users see all users' projects in list."""
        # Create another user with a project
        other_user = User.objects.create_user(
            username="other",
            email="other@example.com",
            password=TEST_PASSWORD,
        )
        other_project = Project.objects.create(
            user=other_user,
            name="Other Project",
            description="Other description",
        )

        staff_user = User.objects.create_user(
            username="staff",
            email="staff@example.com",
            password=TEST_PASSWORD,
            is_staff=True,
        )
        self.client.force_login(staff_user)

        response = self.client.get(reverse("projects:list"))
        assert response.status_code == HTTP_OK

        projects = list(response.context["object_list"])
        assert self.project in projects
        assert other_project in projects


@pytest.mark.django_db
class TestProjectUpdateViewStaff(TestCase):
    """Test ProjectUpdateView with staff user access."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.owner = User.objects.create_user(
            username="owner",
            email="owner@example.com",
            password=TEST_PASSWORD,
        )
        self.project = Project.objects.create(
            user=self.owner,
            name="Test Project",
            description="Test description",
        )

    def test_project_update_staff_access(self):
        """Test that staff user can access update view for any project."""
        staff_user = User.objects.create_user(
            username="staff",
            email="staff@example.com",
            password=TEST_PASSWORD,
            is_staff=True,
        )
        self.client.force_login(staff_user)

        response = self.client.get(
            reverse("projects:update", kwargs={"pk": self.project.pk})
        )
        assert response.status_code == HTTP_OK
        assert response.context["viewing_as_admin"] is True


@pytest.mark.django_db
class TestProjectDeleteViewStaff(TestCase):
    """Test ProjectDeleteView with staff user access."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.owner = User.objects.create_user(
            username="owner",
            email="owner@example.com",
            password=TEST_PASSWORD,
        )
        self.project = Project.objects.create(
            user=self.owner,
            name="Test Project",
            description="Test description",
        )

    def test_project_delete_staff_access(self):
        """Test that staff user can access delete view for any project."""
        staff_user = User.objects.create_user(
            username="staff",
            email="staff@example.com",
            password=TEST_PASSWORD,
            is_staff=True,
        )
        self.client.force_login(staff_user)

        response = self.client.get(
            reverse("projects:delete", kwargs={"pk": self.project.pk})
        )
        assert response.status_code == HTTP_OK
        assert response.context["viewing_as_admin"] is True

    def test_staff_can_actually_delete_project(self):
        """Test that staff user can POST to delete another user's project.

        This tests the fix for the FK constraint issue where audit logging
        would fail after the project was deleted (orphaned FK reference).

        Note: DELETE operations are intentionally NOT logged because:
        1. The project is deleted, so logging after fails (FK constraint)
        2. Creating log before delete causes orphaned FK (CASCADE timing)
        3. A proper fix requires making project FK nullable (SET_NULL)
        """
        staff_user = User.objects.create_user(
            username="staff_delete",
            email="staff_delete@example.com",
            password=TEST_PASSWORD,
            is_staff=True,
        )
        self.client.force_login(staff_user)

        project_pk = self.project.pk

        # POST to actually delete the project
        response = self.client.post(
            reverse("projects:delete", kwargs={"pk": project_pk})
        )

        # Should redirect on successful delete
        assert response.status_code == HTTP_FOUND

        # Verify project is actually deleted
        assert not Project.objects.filter(pk=project_pk).exists()
