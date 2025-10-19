"""Tests for project views."""

from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.contrib.messages import get_messages
from django.test import Client
from django.test import TestCase
from django.urls import reverse

from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.projects.security import SecurityValidationError
from wafer_space.users.models import User

from .constants import EXPECTED_USER_PROJECTS
from .constants import FIVE_MB
from .constants import HTTP_FORBIDDEN
from .constants import HTTP_FOUND
from .constants import HTTP_NOT_FOUND
from .constants import HTTP_OK
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
        assert "/accounts/login/" in response.url

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
        assert "/accounts/login/" in response.url

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
        active_file = ProjectFile.objects.create(
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
        assert response.context["active_file"] == active_file


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

    def test_requires_login(self):
        """Test that view requires login."""
        url = reverse("projects:create")
        response = self.client.get(url)

        # Should redirect to login
        assert response.status_code == HTTP_FOUND
        assert "/accounts/login/" in response.url

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
        }
        response = self.client.post(url, form_data)

        # Should redirect to detail page
        assert response.status_code == HTTP_FOUND

        # Verify project was created
        assert Project.objects.count() == 1
        project = Project.objects.first()
        assert project.name == "New Project"
        assert project.description == "New project description"
        assert project.user == self.user

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
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test project",
        )

    def test_requires_login(self):
        """Test that view requires login."""
        url = reverse("projects:update", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        # Should redirect to login
        assert response.status_code == HTTP_FOUND
        assert "/accounts/login/" in response.url

    def test_owner_can_update(self):
        """Test that owner can update project."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:update", kwargs={"pk": self.project.pk})

        form_data = {
            "name": "Updated Project",
            "description": "Updated description",
        }
        response = self.client.post(url, form_data)

        # Should redirect
        assert response.status_code == HTTP_FOUND

        # Verify project was updated
        self.project.refresh_from_db()
        assert self.project.name == "Updated Project"
        assert self.project.description == "Updated description"

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
        assert "/accounts/login/" in response.url

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
        assert "/accounts/login/" in response.url

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
        assert "/accounts/login/" in response.url

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
        ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            download_status=ProjectFile.DownloadStatus.DOWNLOADING,
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
        assert "/accounts/login/" in response.url

    def test_requires_ownership(self):
        """Test that only owner can submit project."""
        self.client.login(username="otheruser", password=TEST_PASSWORD)
        url = reverse("projects:submit", kwargs={"pk": self.project.pk})
        response = self.client.post(url)

        # Should return 403 Forbidden
        assert response.status_code == HTTP_FORBIDDEN

    def test_successful_submission(self):
        """Test successful project submission."""
        # Create completed and verified file
        ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            download_status=ProjectFile.DownloadStatus.COMPLETED,
            hash_verified=True,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:submit", kwargs={"pk": self.project.pk})
        response = self.client.post(url)

        # Should redirect to project detail
        assert response.status_code == HTTP_FOUND
        detail_url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        assert response.url == detail_url

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
            download_status=ProjectFile.DownloadStatus.PENDING,
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
        ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            download_status=ProjectFile.DownloadStatus.FAILED,
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
        ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            download_status=ProjectFile.DownloadStatus.COMPLETED,
            hash_verified=False,
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
        ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            download_status=ProjectFile.DownloadStatus.COMPLETED,
            hash_verified=True,
        )

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

    def test_prevents_double_submission_race_condition(self):
        """Test that double submission is prevented even with race condition."""
        # Create completed file
        ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            download_status=ProjectFile.DownloadStatus.COMPLETED,
            hash_verified=True,
        )

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
