"""Tests for project views."""

from datetime import timedelta
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.contrib.messages import get_messages
from django.core.cache import cache
from django.test import Client
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from wafer_space.core.enums import SlotSize
from wafer_space.projects.models import DownloadAttempt
from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.projects.security import SecurityValidationError
from wafer_space.projects.tests.factories import ManufacturabilityCheckFactory
from wafer_space.projects.tests.factories import ProjectFactory
from wafer_space.projects.tests.factories import ProjectFileFactory
from wafer_space.shuttles.models import Shuttle
from wafer_space.shuttles.models import ShuttleSlot
from wafer_space.users.models import User
from wafer_space.users.tests.factories import UserFactory

from .constants import EXPECTED_CHECKS_AFTER_COB_TOGGLE
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
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.other_user = User.objects.create_user(
            username="otheruser", email="other@example.com", password=TEST_PASSWORD
        )

        # Create projects for both users
        self.project1 = Project.objects.create(
            user=self.user, name="Project 1", description="First project"
        )
        self.project2 = Project.objects.create(
            user=self.user, name="Project 2", description="Second project"
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
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.other_user = User.objects.create_user(
            username="otheruser", email="other@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(
            user=self.user, name="Test Project", description="Test project"
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
            reverse("projects:detail", kwargs={"pk": self.project.pk})
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
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.shuttle = Shuttle.objects.create(
            name="G800", description="Test Shuttle", status=Shuttle.Status.OPEN
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
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.other_user = User.objects.create_user(
            username="otheruser", email="other@example.com", password=TEST_PASSWORD
        )
        self.shuttle = Shuttle.objects.create(
            name="G800", description="Test Shuttle", status=Shuttle.Status.OPEN
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

    def test_owner_can_update_project_details(self):
        """Test that owner can update name, description, and visibility.

        Regular users can edit name, description, visibility, repository URL,
        and license settings. Staff-only fields (shuttle, project_id, slot_size)
        are not available to regular users.
        """
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:update", kwargs={"pk": self.project.pk})

        # Owner submits updated project details
        form_data = {
            "name": "Updated Project Name",
            "description": "Updated project description",
            "is_public": True,
            "repository_url": "",
            "license_type": "proprietary",
            "other_license_spdx_id": "",
            "proprietary_terms_url": "",
        }
        response = self.client.post(url, form_data)

        # Should redirect
        assert response.status_code == HTTP_FOUND

        # Verify all fields were updated
        self.project.refresh_from_db()
        assert self.project.name == "Updated Project Name"
        assert self.project.description == "Updated project description"
        assert self.project.is_public is True

    def test_owner_gets_form_with_disabled_core_fields(self):
        """Test that owner sees form with core fields disabled."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:update", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert response.context["is_new"] is False
        # The form should have all fields
        form = response.context["form"]
        assert "name" in form.fields
        assert "description" in form.fields
        assert "is_public" in form.fields
        assert "repository_url" in form.fields
        assert "license_type" in form.fields
        # Core fields are present but DISABLED for non-staff
        assert "shuttle" in form.fields
        assert form.fields["shuttle"].disabled is True
        assert "project_id" in form.fields
        assert form.fields["project_id"].disabled is True
        assert "slot_size" in form.fields
        assert form.fields["slot_size"].disabled is True

    def test_staff_can_update_all_fields(self):
        """Test that staff can update all project fields."""
        User.objects.create_user(
            username="staffuser",
            email="staff@example.com",
            password=TEST_PASSWORD,
            is_staff=True,
        )
        self.client.login(username="staffuser", password=TEST_PASSWORD)
        url = reverse("projects:update", kwargs={"pk": self.project.pk})

        form_data = {
            "name": "Updated Project",
            "description": "Updated description",
            "shuttle": self.shuttle.pk,
            "project_id": "UPDT",  # Different from original to test update
            "slot_size": "0p5x1",
            "is_public": True,
            # License fields
            "license_type": "proprietary",
            "other_license_spdx_id": "",
            "proprietary_terms_url": "",
        }
        response = self.client.post(url, form_data)

        # Should redirect
        assert response.status_code == HTTP_FOUND

        # Verify project was updated
        self.project.refresh_from_db()
        assert self.project.name == "Updated Project"
        assert self.project.description == "Updated description"
        assert self.project.project_id == "UPDT"  # Core field updated by staff
        assert self.project.slot_size == "0p5x1"
        assert self.project.is_public is True

    def test_non_owner_cannot_update(self):
        """Test that non-owner cannot update project."""
        self.client.login(username="otheruser", password=TEST_PASSWORD)
        url = reverse("projects:update", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        # Should return 403 Forbidden
        assert response.status_code == HTTP_FORBIDDEN

    def _cob_form_data(self, *, chip_on_board: bool) -> dict[str, str]:
        """Valid update-form payload toggling only chip_on_board."""
        data = {
            "name": self.project.name,
            "description": self.project.description,
            "repository_url": "",
            "license_type": "proprietary",
            "other_license_spdx_id": "",
            "proprietary_terms_url": "",
        }
        if chip_on_board:
            data["chip_on_board"] = "on"
        return data

    def _make_submitted_check(
        self, status: ManufacturabilityCheck.Status
    ) -> ManufacturabilityCheck:
        """Attach a submitted file with a check to self.project."""
        project_file = ProjectFileFactory(project=self.project)
        self.project.submitted_file = project_file
        self.project.save()
        return ManufacturabilityCheckFactory(
            project=self.project,
            project_file=project_file,
            status=status,
        )

    def test_toggling_cob_creates_cob_change_check(self):
        """Enabling CoB on a project with a check creates one COB_CHANGE check."""
        check = self._make_submitted_check(ManufacturabilityCheck.Status.FINISHED)
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:update", kwargs={"pk": self.project.pk})

        response = self.client.post(url, self._cob_form_data(chip_on_board=True))

        assert response.status_code == HTTP_FOUND
        self.project.refresh_from_db()
        assert self.project.chip_on_board is True
        checks = ManufacturabilityCheck.objects.filter(
            project_file=check.project_file
        ).order_by("created_at")
        assert checks.count() == EXPECTED_CHECKS_AFTER_COB_TOGGLE
        new_check = checks.last()
        assert new_check is not None
        assert (
            new_check.trigger_reason == ManufacturabilityCheck.TriggerReason.COB_CHANGE
        )
        assert new_check.parent_check == check

    def test_toggling_cob_cancels_in_progress_check(self):
        """Enabling CoB while a check is RUNNING marks it CANCELLING."""
        check = self._make_submitted_check(ManufacturabilityCheck.Status.RUNNING)
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:update", kwargs={"pk": self.project.pk})

        self.client.post(url, self._cob_form_data(chip_on_board=True))

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLING

    def test_toggling_cob_on_draft_only_persists(self):
        """No submitted file/check: the flag is saved, no check is created."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:update", kwargs={"pk": self.project.pk})

        self.client.post(url, self._cob_form_data(chip_on_board=True))

        self.project.refresh_from_db()
        assert self.project.chip_on_board is True
        assert ManufacturabilityCheck.objects.filter(project=self.project).count() == 0

    def test_unchanged_cob_creates_no_check(self):
        """Submitting the form with CoB unchanged creates no new check."""
        check = self._make_submitted_check(ManufacturabilityCheck.Status.FINISHED)
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:update", kwargs={"pk": self.project.pk})

        self.client.post(url, self._cob_form_data(chip_on_board=False))

        assert (
            ManufacturabilityCheck.objects.filter(
                project_file=check.project_file
            ).count()
            == 1
        )


@pytest.mark.django_db
class TestProjectDeleteView(TestCase):
    """Test ProjectDeleteView."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.other_user = User.objects.create_user(
            username="otheruser", email="other@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(
            user=self.user, name="Test Project", description="Test project"
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
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.other_user = User.objects.create_user(
            username="otheruser", email="other@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(
            user=self.user, name="Test Project", description="Test project"
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
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.other_user = User.objects.create_user(
            username="otheruser", email="other@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(
            user=self.user, name="Test Project", description="Test project"
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
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.other_user = User.objects.create_user(
            username="otheruser", email="other@example.com", password=TEST_PASSWORD
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

    def test_successful_submission(self):
        """Test successful project submission."""

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
        self.project.submitted_file = project_file
        self.project.status = Project.Status.MANUFACTURABLE
        self.project.save()
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )

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
        self.project.submitted_file = project_file
        self.project.status = Project.Status.MANUFACTURABLE
        self.project.save()
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
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
        self.project.submitted_file = project_file
        self.project.status = Project.Status.MANUFACTURABLE
        self.project.save()
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
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


@pytest.mark.django_db
class TestEnhancedProgressDashboard(TestCase):
    """Test enhanced progress dashboard features."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(
            user=self.user, name="Test Project", description="Test project"
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
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(
            user=self.user, name="Test Project", description="Test Description"
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
        # New pathway: PENDING -> DISPATCHING -> STARTING -> RUNNING
        check.mark_dispatching(server_id="server-1")
        check.mark_starting(
            docker_image="test-image:latest",
            docker_image_digest="sha256:abc123",
        )
        check.mark_running(
            docker_container_id="test-container-id",
            docker_command="docker run ...",
        )
        check.mark_analyzing(docker_exit_code=1)
        check.mark_finished(
            is_manufacturable=False,
            errors=["Error 1", "Error 2"],
            warnings=["Warning 1"],
            tool_versions={"precheck": "1.0.0"},
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
        expected_errors = ["Error 1", "Error 2"]
        assert check.errors == expected_errors
        assert check.warnings == ["Warning 1"]

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
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.other_user = User.objects.create_user(
            username="otheruser", email="other@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(
            user=self.user, name="Test Project", description="Test project"
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
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse(
            "projects:cancel_check",
            kwargs={"pk": self.project.pk, "check_id": check.pk},
        )
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
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse(
            "projects:cancel_check",
            kwargs={"pk": self.project.pk, "check_id": check.pk},
        )
        response = self.client.post(url)

        assert response.status_code == HTTP_FOUND
        check.refresh_from_db()
        # Should be CANCELLING, not CANCELLED (cleanup task will complete it)
        assert check.status == ManufacturabilityCheck.Status.CANCELLING

    def test_cancel_check_already_completed(self):
        """Test cancelling already completed check shows warning."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse(
            "projects:cancel_check",
            kwargs={"pk": self.project.pk, "check_id": check.pk},
        )
        response = self.client.post(url, follow=True)

        assert response.status_code == HTTP_OK
        messages_list = list(response.context["messages"])
        assert len(messages_list) == 1
        assert "could not be cancelled" in str(messages_list[0]).lower()

    def test_cancel_check_nonexistent_returns_404(self):
        """Test cancelling nonexistent check returns 404."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse(
            "projects:cancel_check",
            kwargs={"pk": self.project.pk, "check_id": 99999},
        )
        response = self.client.post(url)

        assert response.status_code == HTTP_NOT_FOUND

    def test_cancel_check_wrong_project_returns_404(self):
        """Test cancelling check with wrong project pk returns 404."""
        # Create another project
        other_project = Project.objects.create(
            user=self.user, name="Other Project", description="Other"
        )
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        # Try to cancel check from self.project using other_project's pk
        url = reverse(
            "projects:cancel_check",
            kwargs={"pk": other_project.pk, "check_id": check.pk},
        )
        response = self.client.post(url)

        # Should be 404 because check doesn't belong to other_project
        assert response.status_code == HTTP_NOT_FOUND

    def test_cancel_check_requires_authentication(self):
        """Test that cancel requires authentication."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        url = reverse(
            "projects:cancel_check",
            kwargs={"pk": self.project.pk, "check_id": check.pk},
        )
        response = self.client.post(url)

        assert response.status_code == HTTP_FOUND
        assert "/accounts/login/" in response["Location"]

    def test_cancel_check_requires_ownership(self):
        """Test that non-owner, non-staff users cannot cancel check."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        # Log in as other user
        self.client.login(username="otheruser", password=TEST_PASSWORD)
        url = reverse(
            "projects:cancel_check",
            kwargs={"pk": self.project.pk, "check_id": check.pk},
        )
        response = self.client.post(url)

        # Should be forbidden (403)
        assert response.status_code == HTTP_FORBIDDEN

    def test_cancel_check_get_not_allowed(self):
        """Test that GET requests are not allowed."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse(
            "projects:cancel_check",
            kwargs={"pk": self.project.pk, "check_id": check.pk},
        )
        response = self.client.get(url)

        # GET should return 405 Method Not Allowed
        assert response.status_code == HTTP_METHOD_NOT_ALLOWED

    def test_staff_user_can_cancel_any_check(self):
        """Test that staff users can cancel any project's check."""
        staff_user = User.objects.create_user(
            username="staffuser",
            email="staff@example.com",
            password=TEST_PASSWORD,
            is_staff=True,
        )
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        self.client.login(username="staffuser", password=TEST_PASSWORD)
        url = reverse(
            "projects:cancel_check",
            kwargs={"pk": self.project.pk, "check_id": check.pk},
        )
        response = self.client.post(url)

        assert response.status_code == HTTP_FOUND
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLING
        # Verify admin cancellation is logged
        assert f"Cancelled by admin ({staff_user.username})" in check.processing_logs

    def test_superuser_can_cancel_any_check(self):
        """Test that superusers can cancel any project's check."""
        superuser = User.objects.create_superuser(
            username="superuser",
            email="super@example.com",
            password=TEST_PASSWORD,
        )
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        self.client.login(username="superuser", password=TEST_PASSWORD)
        url = reverse(
            "projects:cancel_check",
            kwargs={"pk": self.project.pk, "check_id": check.pk},
        )
        response = self.client.post(url)

        assert response.status_code == HTTP_FOUND
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLING
        # Verify admin cancellation is logged
        assert f"Cancelled by admin ({superuser.username})" in check.processing_logs

    def test_owner_cancel_logs_correct_reason(self):
        """Test that owner cancellation logs 'Cancelled by owner'."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse(
            "projects:cancel_check",
            kwargs={"pk": self.project.pk, "check_id": check.pk},
        )
        self.client.post(url)

        check.refresh_from_db()
        assert "Cancelled by owner" in check.processing_logs


@pytest.mark.django_db
class TestProjectFileSubmitURLViewWarning(TestCase):
    """Test submit-url page shows warning when check is running."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(
            user=self.user, name="Test Project", description="Test project"
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
class TestProjectDetailSlotVisibility:
    """Test slot assignment visibility on project detail page."""

    def test_staff_sees_slot_assignments(self, client):
        """Staff should see slot assignments on project detail."""
        user = UserFactory(is_staff=True)
        client.force_login(user)

        shuttle = Shuttle.objects.create(
            name="G810", description="Test shuttle", status=Shuttle.Status.OPEN
        )
        project = ProjectFactory(shuttle=shuttle)

        # Assign to two slots
        slot1 = ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.RESERVED,
        )
        slot1.project = project
        slot1.reserved_by = user
        slot1.save()

        slot2 = ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=1,
            column=2,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.RESERVED,
        )
        slot2.project = project
        slot2.reserved_by = user
        slot2.save()

        url = reverse("projects:detail", kwargs={"pk": project.pk})
        response = client.get(url)

        assert response.status_code == HTTP_OK
        content = response.content.decode()

        # Should show slot assignments
        assert "Assigned Slots" in content or "Grid Position" in content
        assert "A1" in content  # slot1 position
        assert "C2" in content  # slot2 position

    def test_regular_user_does_not_see_slots(self, client):
        """Regular users should not see slot assignments."""
        user = UserFactory(is_staff=False)
        shuttle = Shuttle.objects.create(
            name="G811", description="Test shuttle", status=Shuttle.Status.OPEN
        )
        # Create project with shuttle already assigned (core fields are immutable)
        project = ProjectFactory(user=user, shuttle=shuttle)
        client.force_login(user)

        slot = ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.RESERVED,
        )
        slot.project = project
        slot.save()

        url = reverse("projects:detail", kwargs={"pk": project.pk})
        response = client.get(url)

        assert response.status_code == HTTP_OK
        content = response.content.decode()

        # Should NOT show slot section
        assert "Assigned Slots" not in content
        assert "Grid Position" not in content


@pytest.mark.django_db
class TestProjectListViewStaff(TestCase):
    """Test ProjectListView with staff user access."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.owner = User.objects.create_user(
            username="owner", email="owner@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(
            user=self.owner, name="Owner Project", description="Owner description"
        )

    def test_project_list_shows_only_own_projects_for_regular_user(self):
        """Test that regular users only see their own projects in list."""
        # Create another user with a project
        other_user = User.objects.create_user(
            username="other", email="other@example.com", password=TEST_PASSWORD
        )
        other_project = Project.objects.create(
            user=other_user, name="Other Project", description="Other description"
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
            username="other", email="other@example.com", password=TEST_PASSWORD
        )
        other_project = Project.objects.create(
            user=other_user, name="Other Project", description="Other description"
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
            username="owner", email="owner@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(
            user=self.owner, name="Test Project", description="Test description"
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
            username="owner", email="owner@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(
            user=self.owner, name="Test Project", description="Test description"
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


@pytest.mark.django_db
class TestCheckDrcUpdateRequeue:
    """Tests for check_drc_update_requeue view."""

    def setup_method(self):
        """Set up test data."""
        cache.clear()
        self.user = UserFactory()
        self.project = ProjectFactory(user=self.user)
        self.project_file = ProjectFileFactory(project=self.project, is_active=True)

    def test_requeue_success(self, client):
        """Successful requeue redirects with success message."""
        # Create finished check with outdated digest
        check = ManufacturabilityCheckFactory(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest=(
                "sha256:old123456789012345678901234567890123456789012345678901234567"
            ),
            container_started_at=timezone.now() - timedelta(hours=2),
        )
        # Establish latest digest
        ManufacturabilityCheckFactory(
            docker_image_digest=(
                "sha256:new456789012345678901234567890123456789012345678901234567890"
            ),
            container_started_at=timezone.now(),
        )
        cache.clear()

        client.force_login(self.user)
        response = client.post(
            reverse("projects:check_drc_update_requeue", args=[check.id])
        )

        assert response.status_code == HTTP_FOUND
        assert response.url == reverse("projects:detail", args=[self.project.id])

        # Verify new check was created
        new_check = ManufacturabilityCheck.objects.filter(
            parent_check=check,
            trigger_reason=ManufacturabilityCheck.TriggerReason.DRC_UPDATE,
        ).first()
        assert new_check is not None

    def test_requeue_permission_denied_other_user(self, client):
        """Non-owner non-staff cannot requeue."""
        check = ManufacturabilityCheckFactory(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest=(
                "sha256:old123456789012345678901234567890123456789012345678901234567"
            ),
        )
        other_user = UserFactory()

        client.force_login(other_user)
        response = client.post(
            reverse("projects:check_drc_update_requeue", args=[check.id])
        )

        assert response.status_code == HTTP_FORBIDDEN

    def test_requeue_allowed_for_staff(self, client):
        """Staff can requeue any project's check."""
        check = ManufacturabilityCheckFactory(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest=(
                "sha256:old123456789012345678901234567890123456789012345678901234567"
            ),
            container_started_at=timezone.now() - timedelta(hours=2),
        )
        ManufacturabilityCheckFactory(
            docker_image_digest=(
                "sha256:new456789012345678901234567890123456789012345678901234567890"
            ),
            container_started_at=timezone.now(),
        )
        cache.clear()
        staff_user = UserFactory(is_staff=True)

        client.force_login(staff_user)
        response = client.post(
            reverse("projects:check_drc_update_requeue", args=[check.id])
        )

        assert response.status_code == HTTP_FOUND

    def test_requeue_invalid_check_shows_error(self, client):
        """Requeue of already-latest check shows error message."""
        check = ManufacturabilityCheckFactory(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest=(
                "sha256:latest123456789012345678901234567890123456789012345678901234"
            ),
            container_started_at=timezone.now(),
        )
        cache.clear()

        client.force_login(self.user)
        response = client.post(
            reverse("projects:check_drc_update_requeue", args=[check.id]),
            follow=True,
        )

        assert response.status_code == HTTP_OK
        messages = list(response.context["messages"])
        assert len(messages) == 1
        assert "already using latest" in str(messages[0])

    def test_requeue_requires_login(self, client):
        """Unauthenticated users are redirected to login."""
        check = ManufacturabilityCheckFactory(
            project=self.project,
            project_file=self.project_file,
        )

        response = client.post(
            reverse("projects:check_drc_update_requeue", args=[check.id])
        )

        assert response.status_code == HTTP_FOUND
        assert "/accounts/login/" in response.url

    def test_requeue_requires_post(self, client):
        """GET requests are not allowed."""
        check = ManufacturabilityCheckFactory(
            project=self.project,
            project_file=self.project_file,
        )

        client.force_login(self.user)
        response = client.get(
            reverse("projects:check_drc_update_requeue", args=[check.id])
        )

        assert response.status_code == HTTP_METHOD_NOT_ALLOWED
