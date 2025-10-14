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


@pytest.mark.django_db
class TestProjectListView(TestCase):
    """Test ProjectListView."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.other_user = User.objects.create_user(
            username="otheruser",
            email="other@example.com",
            password="testpass123",
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
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_shows_only_user_projects(self):
        """Test that view shows only current user's projects."""
        self.client.login(username="testuser", password="testpass123")
        url = reverse("projects:list")
        response = self.client.get(url)

        assert response.status_code == 200
        assert "projects" in response.context
        projects = response.context["projects"]

        # Should show 2 projects
        assert len(projects) == 2
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
            password="testpass123",
        )
        self.other_user = User.objects.create_user(
            username="otheruser",
            email="other@example.com",
            password="testpass123",
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
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_owner_can_view(self):
        """Test that owner can view project."""
        self.client.login(username="testuser", password="testpass123")
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == 200
        assert response.context["project"] == self.project

    def test_non_owner_cannot_view(self):
        """Test that non-owner cannot view project."""
        self.client.login(username="otheruser", password="testpass123")
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        # Should return 403 Forbidden
        assert response.status_code == 403

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

        self.client.login(username="testuser", password="testpass123")
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == 200
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
            password="testpass123",
        )

    def test_requires_login(self):
        """Test that view requires login."""
        url = reverse("projects:create")
        response = self.client.get(url)

        # Should redirect to login
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_displays_form(self):
        """Test that GET displays the form."""
        self.client.login(username="testuser", password="testpass123")
        url = reverse("projects:create")
        response = self.client.get(url)

        assert response.status_code == 200
        assert "form" in response.context

    def test_creates_project(self):
        """Test that POST creates a project."""
        self.client.login(username="testuser", password="testpass123")
        url = reverse("projects:create")

        form_data = {
            "name": "New Project",
            "description": "New project description",
        }
        response = self.client.post(url, form_data)

        # Should redirect to detail page
        assert response.status_code == 302

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
            password="testpass123",
        )
        self.other_user = User.objects.create_user(
            username="otheruser",
            email="other@example.com",
            password="testpass123",
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
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_owner_can_update(self):
        """Test that owner can update project."""
        self.client.login(username="testuser", password="testpass123")
        url = reverse("projects:update", kwargs={"pk": self.project.pk})

        form_data = {
            "name": "Updated Project",
            "description": "Updated description",
        }
        response = self.client.post(url, form_data)

        # Should redirect
        assert response.status_code == 302

        # Verify project was updated
        self.project.refresh_from_db()
        assert self.project.name == "Updated Project"
        assert self.project.description == "Updated description"

    def test_non_owner_cannot_update(self):
        """Test that non-owner cannot update project."""
        self.client.login(username="otheruser", password="testpass123")
        url = reverse("projects:update", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        # Should return 403 Forbidden
        assert response.status_code == 403


@pytest.mark.django_db
class TestProjectDeleteView(TestCase):
    """Test ProjectDeleteView."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.other_user = User.objects.create_user(
            username="otheruser",
            email="other@example.com",
            password="testpass123",
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
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_owner_can_delete(self):
        """Test that owner can delete project."""
        self.client.login(username="testuser", password="testpass123")
        url = reverse("projects:delete", kwargs={"pk": self.project.pk})

        response = self.client.post(url)

        # Should redirect to list page
        assert response.status_code == 302

        # Verify project was deleted
        assert Project.objects.count() == 0

    def test_non_owner_cannot_delete(self):
        """Test that non-owner cannot delete project."""
        self.client.login(username="otheruser", password="testpass123")
        url = reverse("projects:delete", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        # Should return 403 Forbidden
        assert response.status_code == 403


@pytest.mark.django_db
class TestProjectFileSubmitURLView(TestCase):
    """Test ProjectFileSubmitURLView."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.other_user = User.objects.create_user(
            username="otheruser",
            email="other@example.com",
            password="testpass123",
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
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_owner_can_view_form(self):
        """Test that owner can view form."""
        self.client.login(username="testuser", password="testpass123")
        url = reverse("projects:submit_url", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == 200
        assert "form" in response.context

    def test_non_owner_cannot_view_form(self):
        """Test that non-owner cannot view form."""
        self.client.login(username="otheruser", password="testpass123")
        url = reverse("projects:submit_url", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        # Should return 403 Forbidden
        assert response.status_code == 403

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

        self.client.login(username="testuser", password="testpass123")
        url = reverse("projects:submit_url", kwargs={"pk": self.project.pk})

        form_data = {
            "url": "https://github.com/user/repo/blob/main/file.gds",
            "expected_hash_md5": "",
            "expected_hash_sha1": "",
        }
        response = self.client.post(url, form_data)

        # Should redirect to detail page
        assert response.status_code == 302

        # Verify service was called
        mock_submit.assert_called_once()

    @patch("wafer_space.projects.views.ProjectFileService.submit_file_from_url")
    def test_submit_url_security_error(self, mock_submit):
        """Test URL submission with security error."""
        # Mock security validation error
        mock_submit.side_effect = SecurityValidationError("Cannot download from localhost")

        self.client.login(username="testuser", password="testpass123")
        url = reverse("projects:submit_url", kwargs={"pk": self.project.pk})

        form_data = {
            "url": "http://localhost/file.gds",
            "expected_hash_md5": "",
            "expected_hash_sha1": "",
        }
        response = self.client.post(url, form_data)

        # Should re-render form with error
        assert response.status_code == 200
        messages = list(get_messages(response.wsgi_request))
        assert any("Security validation failed" in str(m) for m in messages)


@pytest.mark.django_db
class TestProjectFileUploadView(TestCase):
    """Test ProjectFileUploadView."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.other_user = User.objects.create_user(
            username="otheruser",
            email="other@example.com",
            password="testpass123",
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test project",
        )

    def test_requires_login(self):
        """Test that view requires login."""
        url = reverse("projects:upload", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        # Should redirect to login
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_owner_can_view_form(self):
        """Test that owner can view form."""
        self.client.login(username="testuser", password="testpass123")
        url = reverse("projects:upload", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == 200
        assert "form" in response.context

    def test_non_owner_cannot_view_form(self):
        """Test that non-owner cannot view form."""
        self.client.login(username="otheruser", password="testpass123")
        url = reverse("projects:upload", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        # Should return 403 Forbidden
        assert response.status_code == 403


@pytest.mark.django_db
class TestProjectFileProgressView(TestCase):
    """Test ProjectFileProgressView."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.other_user = User.objects.create_user(
            username="otheruser",
            email="other@example.com",
            password="testpass123",
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
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_non_owner_cannot_view_progress(self):
        """Test that non-owner cannot view progress."""
        self.client.login(username="otheruser", password="testpass123")
        url = reverse("projects:progress", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        # Should return 403 Forbidden
        assert response.status_code == 403

    def test_no_active_file_returns_404(self):
        """Test that no active file returns 404."""
        self.client.login(username="testuser", password="testpass123")
        url = reverse("projects:progress", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        # Should return 404
        assert response.status_code == 404
        data = response.json()
        assert "error" in data

    @patch("wafer_space.projects.views.ProjectFileService.get_download_progress")
    def test_returns_progress_json(self, mock_progress):
        """Test that view returns progress as JSON."""
        # Create active file
        active_file = ProjectFile.objects.create(
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
            "progress": 45,
            "current": 4718592,
            "total": 10485760,
            "message": "Downloaded 4,718,592 of 10,485,760 bytes",
        }

        self.client.login(username="testuser", password="testpass123")
        url = reverse("projects:progress", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "downloading"
        assert data["progress"] == 45
        assert data["current"] == 4718592
        assert data["total"] == 10485760
