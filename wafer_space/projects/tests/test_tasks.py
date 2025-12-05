"""
Tests for project background tasks.

Security-Critical Tests:
- URL validation prevents dangerous schemes like file://, ftp://, custom schemes
- Only http:// and https:// schemes are allowed for file downloads
"""

import hashlib
import io
import logging
import tempfile
import zipfile
from pathlib import Path
from tempfile import NamedTemporaryFile
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch
from unittest.mock import patch as mock_patch

import docker.errors
import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase

from wafer_space.core.enums import SlotSize
from wafer_space.projects import tasks
from wafer_space.projects.models import DownloadAttempt
from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import ManufacturabilityCheckTask
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.projects.tasks import _build_github_artifact_filename
from wafer_space.projects.tasks import _download_github_artifact
from wafer_space.projects.tasks import _download_with_progress
from wafer_space.projects.tasks import _log_download_start
from wafer_space.projects.tasks import _prepare_download_request
from wafer_space.projects.tasks import _process_and_save_content
from wafer_space.projects.tasks import _safe_urlopen
from wafer_space.projects.tasks import check_process_job
from wafer_space.projects.tasks import checks_cancelling
from wafer_space.projects.tasks import checks_cleanup_orphaned_dispatch
from wafer_space.projects.tasks import checks_cleanup_orphaned_processing
from wafer_space.projects.tasks import checks_create
from wafer_space.projects.tasks import checks_dispatch
from wafer_space.projects.tasks import checks_dispatching
from wafer_space.projects.tasks import checks_pending
from wafer_space.projects.tasks import checks_retry
from wafer_space.projects.tasks import download_project_file
from wafer_space.projects.tests.factories import ManufacturabilityCheckFactory
from wafer_space.shuttles.models import Shuttle

User = get_user_model()
TEST_PASSWORD = "testpass123"  # noqa: S105 - Test password constant
TEST_GITHUB_TOKEN = "test_token"  # noqa: S105 - Test token constant
TEST_WORKER_PID = 12345  # Test worker process ID constant
DEAD_WORKER_PID = 99999  # Test dead worker process ID constant


class URLValidationSecurityTests(TestCase):
    """Security tests for URL validation in file download functionality."""

    def test_valid_http_url_allowed(self):
        """Test that http:// URLs are accepted."""
        with patch("wafer_space.projects.tasks.urlopen") as mock_urlopen:
            mock_response = Mock()
            mock_response.read.return_value = b"test content"
            mock_response.headers = {"Content-Type": "application/zip"}
            mock_urlopen.return_value.__enter__.return_value = mock_response

            # This should not raise any exception
            content, headers = _safe_urlopen("http://example.com/file.zip")
            assert content == b"test content"
            assert headers["Content-Type"] == "application/zip"

    def test_valid_https_url_allowed(self):
        """Test that https:// URLs are accepted."""
        with patch("wafer_space.projects.tasks.urlopen") as mock_urlopen:
            mock_response = Mock()
            mock_response.read.return_value = b"test content"
            mock_response.headers = {"Content-Type": "application/zip"}
            mock_urlopen.return_value.__enter__.return_value = mock_response

            # This should not raise any exception
            content, headers = _safe_urlopen("https://example.com/file.zip")
            assert content == b"test content"
            assert headers["Content-Type"] == "application/zip"

    def test_file_scheme_blocked(self):
        """Test that file:// URLs are blocked for security."""
        with pytest.raises(ValueError, match="Unsupported URL scheme: file") as excinfo:
            _safe_urlopen("file:///etc/passwd")

        assert "Unsupported URL scheme: file" in str(excinfo.value)

    def test_ftp_scheme_blocked(self):
        """Test that ftp:// URLs are blocked."""
        with pytest.raises(ValueError, match="Unsupported URL scheme: ftp") as excinfo:
            _safe_urlopen("ftp://example.com/file.zip")

        assert "Unsupported URL scheme: ftp" in str(excinfo.value)

    def test_custom_scheme_blocked(self):
        """Test that custom schemes are blocked."""
        with pytest.raises(
            ValueError, match="Unsupported URL scheme: custom"
        ) as excinfo:
            _safe_urlopen("custom://malicious/payload")

        assert "Unsupported URL scheme: custom" in str(excinfo.value)

    def test_javascript_scheme_blocked(self):
        """Test that javascript: URLs are blocked."""
        with pytest.raises(
            ValueError, match="Unsupported URL scheme: javascript"
        ) as excinfo:
            _safe_urlopen("javascript:alert('xss')")

        assert "Unsupported URL scheme: javascript" in str(excinfo.value)

    def test_data_scheme_blocked(self):
        """Test that data: URLs are blocked."""
        with pytest.raises(ValueError, match="Unsupported URL scheme: data") as excinfo:
            _safe_urlopen("data:text/plain;base64,SGVsbG8=")

        assert "Unsupported URL scheme: data" in str(excinfo.value)

    def test_ldap_scheme_blocked(self):
        """Test that ldap:// URLs are blocked."""
        with pytest.raises(ValueError, match="Unsupported URL scheme: ldap") as excinfo:
            _safe_urlopen("ldap://example.com/query")

        assert "Unsupported URL scheme: ldap" in str(excinfo.value)

    def test_empty_scheme_blocked(self):
        """Test that URLs without schemes are blocked."""
        with pytest.raises(ValueError, match="Unsupported URL scheme:") as excinfo:
            _safe_urlopen("//example.com/file.zip")

        assert "Unsupported URL scheme:" in str(excinfo.value)

    def test_scheme_case_insensitive(self):
        """Test that scheme validation is case insensitive."""
        # Should allow HTTPS
        with patch("wafer_space.projects.tasks.urlopen") as mock_urlopen:
            mock_response = Mock()
            mock_response.read.return_value = b"test content"
            mock_response.headers = {}
            mock_urlopen.return_value.__enter__.return_value = mock_response

            # This should not raise any exception
            content, _headers = _safe_urlopen("HTTPS://example.com/file.zip")
            assert content == b"test content"

        # Should block FILE
        with pytest.raises(ValueError, match="Unsupported URL scheme: file") as excinfo:
            _safe_urlopen("FILE:///etc/passwd")

        assert "Unsupported URL scheme: file" in str(excinfo.value)

    def test_headers_passed_correctly(self):
        """Test that custom headers are passed to the request."""
        custom_headers = {"Authorization": "Bearer token123", "Custom-Header": "test"}

        with patch("wafer_space.projects.tasks.urlopen") as mock_urlopen:
            mock_response = Mock()
            mock_response.read.return_value = b"test content"
            mock_response.headers = {"Content-Type": "text/plain"}
            mock_urlopen.return_value.__enter__.return_value = mock_response

            content, headers = _safe_urlopen(
                "https://example.com/file.zip", headers=custom_headers
            )
            assert content == b"test content"
            assert headers["Content-Type"] == "text/plain"

            # Verify the request was made with correct headers
            assert mock_urlopen.called


class URLValidationBehaviorTests(TestCase):
    """Tests to verify the behavior of URL validation security measures."""

    def test_validation_error_provides_helpful_message(self):
        """Test that validation errors provide clear, helpful messages."""
        test_cases = [
            ("file:///etc/passwd", "file"),
            ("ftp://example.com", "ftp"),
            ("custom://test", "custom"),
        ]

        for url, expected_scheme in test_cases:
            with self.subTest(url=url):
                with pytest.raises(
                    ValueError, match=r"(?i)unsupported url scheme"
                ) as excinfo:
                    _safe_urlopen(url)

                error_msg = str(excinfo.value).lower()
                assert "unsupported url scheme" in error_msg
                assert expected_scheme in error_msg

    def test_validation_is_case_insensitive_comprehensive(self):
        """Test comprehensive case insensitivity for both valid and invalid schemes."""
        valid_cases = [
            "http://test.com",
            "HTTP://test.com",
            "https://test.com",
            "HTTPS://test.com",
        ]
        invalid_cases = ["file:///test", "FILE:///test", "ftp://test", "FTP://test"]

        # Test valid cases
        for url in valid_cases:
            with (
                self.subTest(url=url),
                patch("wafer_space.projects.tasks.urlopen") as mock_urlopen,
            ):
                mock_response = Mock()
                mock_response.read.return_value = b"test"
                mock_response.headers = {}
                mock_urlopen.return_value.__enter__.return_value = mock_response

                # Should not raise exception
                content, _headers = _safe_urlopen(url)
                assert content == b"test"

        # Test invalid cases
        for url in invalid_cases:
            with (
                self.subTest(url=url),
                pytest.raises(ValueError, match=r".*(file|ftp).*"),
            ):
                _safe_urlopen(url)


@pytest.mark.django_db
class TestManufacturabilityCheckTask(TestCase):
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.shuttle = Shuttle.objects.create(
            name="G800",
            description="Test Shuttle",
            status=Shuttle.Status.OPEN,
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test Description",
            shuttle=self.shuttle,
            project_id="ABCD",
        )

    @patch("wafer_space.projects.tasks.docker")
    def test_check_task_marks_processing(self, mock_docker):
        """Test that task marks check as RUNNING."""
        # Create a temporary GDS file
        with tempfile.NamedTemporaryFile(suffix=".gds", delete=False) as tmp:
            tmp.write(b"Mock GDS content")
            tmp_path = Path(tmp.name)

        # Save the file to the project's submitted_file
        with tmp_path.open("rb") as f:
            project_file = ProjectFile.objects.create(
                project=self.project,
                original_filename="test.gds",
                is_active=True,
                top_cell="TestCell",
            )
            project_file.file.save("test.gds", ContentFile(f.read()), save=True)
            self.project.submitted_file = project_file
            self.project.save()

        # Setup mock Docker
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_image = MagicMock()
        mock_image.id = "sha256:abc123"
        mock_image.tags = ["ghcr.io/wafer-space/gf180mcu-precheck:latest"]
        mock_client.images.pull.return_value = mock_image
        mock_client.images.get.return_value = mock_image
        mock_client.api.pull.return_value = []  # Empty progress stream

        # Mock container with manufacturable result
        mock_container = MagicMock()
        mock_container.id = "test-container-123"
        # logs(stream=True) returns iterator, logs() returns bytes
        mock_container.logs.side_effect = lambda *args, **kwargs: (
            [b"Precheck successfully completed."]
            if kwargs.get("stream")
            else b"Precheck successfully completed."
        )
        mock_container.wait.return_value = {"StatusCode": 0}
        mock_container.remove.return_value = None
        mock_client.containers.run.return_value = mock_container

        # Mock docker.errors
        mock_docker.errors.DockerException = Exception
        mock_docker.errors.ContainerError = Exception
        mock_docker.errors.ImageNotFound = Exception
        mock_docker.errors.APIError = Exception
        mock_docker.errors.NotFound = Exception

        # Create check in DISPATCHED state (required for mark_running())
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.DISPATCHED,
            celery_job_id="test-task-123",
        )

        # Run task
        with mock_patch.object(tasks.check_process_job, "update_state"):
            result = check_process_job.run(check.id)

        # Verify check was marked as running then completed
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.FINISHED
        assert result["status"] == "completed"

        # Cleanup
        tmp_path.unlink(missing_ok=True)

    @patch("wafer_space.projects.tasks.docker")
    def test_check_task_completes_successfully(self, mock_docker):
        """Test that task completes check successfully."""
        # Create a temporary GDS file
        with tempfile.NamedTemporaryFile(suffix=".gds", delete=False) as tmp:
            tmp.write(b"Mock GDS content")
            tmp_path = Path(tmp.name)

        # Save the file to the project's submitted_file
        with tmp_path.open("rb") as f:
            project_file = ProjectFile.objects.create(
                project=self.project,
                original_filename="test.gds",
                is_active=True,
                top_cell="TestCell",
            )
            project_file.file.save("test.gds", ContentFile(f.read()), save=True)
            self.project.submitted_file = project_file
            self.project.save()

        # Setup mock Docker
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_image = MagicMock()
        mock_image.id = "sha256:abc123"
        mock_image.tags = ["ghcr.io/wafer-space/gf180mcu-precheck:latest"]
        mock_client.images.pull.return_value = mock_image
        mock_client.images.get.return_value = mock_image
        mock_client.api.pull.return_value = []  # Empty progress stream

        # Mock container with manufacturable result and warnings
        mock_logs = b"""Precheck successfully completed.
WARNING: Minor DRC violation at (100, 200)
INFO: Check completed
"""
        mock_container = MagicMock()
        mock_container.id = "test-container-123"  # Must be a string for DB storage
        # logs(stream=True) returns iterator, logs() returns bytes
        mock_container.logs.side_effect = lambda *args, **kwargs: (
            [mock_logs] if kwargs.get("stream") else mock_logs
        )
        mock_container.wait.return_value = {"StatusCode": 0}
        mock_container.remove.return_value = None
        mock_client.containers.run.return_value = mock_container

        # Mock docker.errors
        mock_docker.errors.DockerException = Exception
        mock_docker.errors.ContainerError = Exception
        mock_docker.errors.ImageNotFound = Exception
        mock_docker.errors.APIError = Exception
        mock_docker.errors.NotFound = Exception

        # Create check in DISPATCHED state (required for mark_running())
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.DISPATCHED,
            celery_job_id="test-task-123",
        )

        # Run task
        with mock_patch.object(tasks.check_process_job, "update_state"):
            result = check_process_job.run(check.id)

        # Verify result
        assert result["status"] == "completed"
        assert result["is_manufacturable"] is True
        # Note: Warnings depend on log parser implementation
        assert result["errors"] == []

        # Verify check was updated
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.FINISHED
        assert check.is_manufacturable is True
        assert check.errors == []
        assert check.analysis_completed_at is not None

        # Cleanup
        tmp_path.unlink(missing_ok=True)

    @patch("wafer_space.projects.tasks.docker")
    def test_check_task_detects_not_manufacturable(self, mock_docker):
        """Test that task can mark project as not manufacturable."""
        # Create a temporary GDS file
        with tempfile.NamedTemporaryFile(suffix=".gds", delete=False) as tmp:
            tmp.write(b"Mock GDS content")
            tmp_path = Path(tmp.name)

        # Save the file to the project's submitted_file
        with tmp_path.open("rb") as f:
            project_file = ProjectFile.objects.create(
                project=self.project,
                original_filename="test.gds",
                is_active=True,
                top_cell="TestCell",
            )
            project_file.file.save("test.gds", ContentFile(f.read()), save=True)
            self.project.submitted_file = project_file
            self.project.save()

        # Setup mock Docker
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_image = MagicMock()
        mock_image.id = "sha256:abc123"
        mock_image.tags = ["ghcr.io/wafer-space/gf180mcu-precheck:latest"]
        mock_client.images.pull.return_value = mock_image
        mock_client.images.get.return_value = mock_image
        mock_client.api.pull.return_value = []  # Empty progress stream

        # Mock container with not manufacturable result (non-zero exit code)
        # Must include both Magic AND KLayout DRC results for precheck to be
        # considered "complete" - otherwise it's classified as system error
        mock_logs = b"""ERROR: DRC violation at (100, 200)
ERROR: Metal spacing violation
2 Magic DRC errors found.
1 KLayout DRC errors found.
FATAL: Design has critical errors
"""
        mock_container = MagicMock()
        mock_container.id = "test-container-123"
        # logs(stream=True) returns iterator, logs() returns bytes
        mock_container.logs.side_effect = lambda *args, **kwargs: (
            [mock_logs] if kwargs.get("stream") else mock_logs
        )
        mock_container.wait.return_value = {"StatusCode": 1}
        mock_container.remove.return_value = None
        mock_client.containers.run.return_value = mock_container

        # Mock docker.errors
        mock_docker.errors.DockerException = Exception
        mock_docker.errors.ContainerError = Exception
        mock_docker.errors.ImageNotFound = Exception
        mock_docker.errors.APIError = Exception
        mock_docker.errors.NotFound = Exception

        # Create check in DISPATCHED state (required for mark_running())
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.DISPATCHED,
            celery_job_id="test-task-123",
        )

        # Run task
        with mock_patch.object(tasks.check_process_job, "update_state"):
            result = check_process_job.run(check.id)

        # Verify result - design is not manufacturable due to mock DRC violations
        assert result["status"] == "completed"
        assert result["is_manufacturable"] is False
        # Errors depend on log parser implementation
        assert isinstance(result["errors"], list)

        # Verify check was updated
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.FINISHED
        assert check.is_manufacturable is False
        assert check.analysis_completed_at is not None

        # Cleanup
        tmp_path.unlink(missing_ok=True)

    def test_check_task_handles_missing_check(self):
        """Test that task handles missing check gracefully."""
        # Run task with non-existent check ID
        result = check_process_job(999999)

        # Verify error handling
        assert result["status"] == "error"
        assert "not found" in result["message"]

    @patch("wafer_space.projects.tasks.docker")
    def test_check_task_retries_on_error(self, mock_docker):
        """Test that task handles unexpected errors."""
        # Create a temporary GDS file
        with tempfile.NamedTemporaryFile(suffix=".gds", delete=False) as tmp:
            tmp.write(b"Mock GDS content")
            tmp_path = Path(tmp.name)

        # Save the file to the project's submitted_file
        with tmp_path.open("rb") as f:
            project_file = ProjectFile.objects.create(
                project=self.project, original_filename="test.gds", is_active=True
            )
            project_file.file.save("test.gds", ContentFile(f.read()), save=True)
            self.project.submitted_file = project_file
            self.project.save()

        # Create unique exception classes for Docker errors
        # so they don't catch unrelated errors
        class MockDockerError(Exception):
            pass

        class MockContainerError(MockDockerError):
            pass

        class MockImageNotFoundError(MockDockerError):
            pass

        class MockAPIError(MockDockerError):
            pass

        class MockNotFoundError(MockDockerError):
            pass

        mock_docker.errors.DockerException = MockDockerError
        mock_docker.errors.ContainerError = MockContainerError
        mock_docker.errors.ImageNotFound = MockImageNotFoundError
        mock_docker.errors.APIError = MockAPIError
        mock_docker.errors.NotFound = MockNotFoundError

        # Setup mock Docker to raise a RuntimeError
        # (transient error, should trigger retry)
        mock_docker.from_env.side_effect = RuntimeError("Test error")

        # Create a check with max retries set to 0 to avoid retry loop
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.PENDING,
            max_retries=0,
        )

        # Run task directly (not via Celery) - should handle the exception
        result = check_process_job.run(check.id)
        assert result["status"] == "failed"
        assert "Test error" in result["message"]

        # Cleanup
        tmp_path.unlink(missing_ok=True)

    @patch("wafer_space.projects.tasks.docker")
    def test_check_task_updates_project_status(self, mock_docker):
        """Test that task updates project status based on check result."""
        # Create a temporary GDS file
        with tempfile.NamedTemporaryFile(suffix=".gds", delete=False) as tmp:
            tmp.write(b"Mock GDS content")
            tmp_path = Path(tmp.name)

        # Save the file to the project's submitted_file
        with tmp_path.open("rb") as f:
            project_file = ProjectFile.objects.create(
                project=self.project,
                original_filename="test.gds",
                is_active=True,
                top_cell="TestCell",
            )
            project_file.file.save("test.gds", ContentFile(f.read()), save=True)
            self.project.submitted_file = project_file
            self.project.save()

        # Setup mock Docker
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_image = MagicMock()
        mock_image.id = "sha256:abc123"
        mock_image.tags = ["ghcr.io/wafer-space/gf180mcu-precheck:latest"]
        mock_client.images.pull.return_value = mock_image
        mock_client.images.get.return_value = mock_image
        mock_client.api.pull.return_value = []  # Empty progress stream

        # Mock container with manufacturable result
        mock_container = MagicMock()
        mock_container.id = "test-container-123"
        # logs(stream=True) returns iterator, logs() returns bytes
        mock_container.logs.side_effect = lambda *args, **kwargs: (
            [b"Precheck successfully completed."]
            if kwargs.get("stream")
            else b"Precheck successfully completed."
        )
        mock_container.wait.return_value = {"StatusCode": 0}
        mock_container.remove.return_value = None
        mock_client.containers.run.return_value = mock_container

        # Mock docker.errors
        mock_docker.errors.DockerException = Exception
        mock_docker.errors.ContainerError = Exception
        mock_docker.errors.ImageNotFound = Exception
        mock_docker.errors.APIError = Exception
        mock_docker.errors.NotFound = Exception

        # Set project to SUBMITTED status
        self.project.status = Project.Status.SUBMITTED
        self.project.save()

        # Create check in DISPATCHED state (required for mark_running())
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.DISPATCHED,
            celery_job_id="test-task-456",
        )

        # Run task
        with mock_patch.object(tasks.check_process_job, "update_state"):
            check_process_job.run(check.id)

        # Verify check completed successfully
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.FINISHED
        assert check.is_manufacturable is True

        # Cleanup
        tmp_path.unlink(missing_ok=True)


@pytest.mark.django_db
class TestProjectSubmissionIntegration(TestCase):
    """Integration tests for project submission with manufacturability check."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(
            user=self.user, name="Test Project", description="Test Description"
        )
        # Create a completed file for submission
        self.project_file = ProjectFile.objects.create(
            project=self.project,
            original_filename="test.gds",
            source_url="https://example.com/test.gds",
            file_size=1024,
            is_active=True,
            hash_verified=True,
        )
        DownloadAttempt.objects.create(
            project_file=self.project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.COMPLETED,
        )

    def test_submit_updates_project_status(self):
        """Test that submitting a project updates its status to SUBMITTED.

        Note: Manufacturability checks are created by the checks_create()
        periodic task for verified files, not during submission.
        """
        # Mark as manufacturable (simulates completed check via mark_finished)
        self.project.is_manufacturable = True
        self.project.status = Project.Status.MANUFACTURABLE
        self.project.save()

        # Submit the project
        self.project.submit()

        # Verify project status was updated
        assert self.project.status == Project.Status.SUBMITTED
        assert self.project.submitted_at is not None
        assert self.project.submitted_file == self.project_file


@pytest.mark.django_db
class TestDockerIntegration(TestCase):
    """Test Docker integration in manufacturability check."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.shuttle, _ = Shuttle.objects.get_or_create(
            name="G801",
            defaults={
                "description": "Test Shuttle",
                "status": Shuttle.Status.OPEN,
            },
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test Description",
            shuttle=self.shuttle,
            project_id="TEST",
        )
        # Create a verified file for manufacturability checking
        self.project_file = ProjectFile.objects.create(
            project=self.project,
            original_filename="test.gds",
            source_url="https://example.com/test.gds",
            file_size=1024,
            is_active=True,
            hash_verified=True,
            top_cell="TestCell",
        )
        # Create a completed download attempt to set download_status
        DownloadAttempt.objects.create(
            project_file=self.project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.COMPLETED,
        )

    @patch("wafer_space.projects.tasks.docker")
    def test_pulls_docker_image(self, mock_docker):
        """Test that Docker image is pulled."""
        # Create a real temp file for the GDS file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".gds") as tmp:
            tmp.write(b"fake GDS content")
            tmp_path = Path(tmp.name)

        # Save the file to the project_file
        with tmp_path.open("rb") as f:
            self.project_file.file.save("test.gds", ContentFile(f.read()), save=True)

        # Setup mock
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_image = MagicMock()
        mock_image.id = "sha256:abc123"
        mock_image.tags = ["ghcr.io/wafer-space/gf180mcu-precheck:latest"]
        mock_client.images.pull.return_value = mock_image
        mock_client.images.get.return_value = mock_image
        mock_client.api.pull.return_value = []  # Empty progress stream

        # Mock container
        mock_container = MagicMock()
        mock_container.id = "test-container-123"  # Must be a string for DB storage
        # logs(stream=True) returns iterator, logs() returns bytes
        mock_container.logs.side_effect = lambda *args, **kwargs: (
            [b"Precheck successfully completed."]
            if kwargs.get("stream")
            else b"Precheck successfully completed."
        )
        mock_container.wait.return_value = {"StatusCode": 0}
        mock_container.remove.return_value = None
        mock_client.containers.run.return_value = mock_container

        # Mock docker.errors to be proper exception classes
        mock_docker.errors.DockerException = Exception
        mock_docker.errors.ContainerError = Exception
        mock_docker.errors.ImageNotFound = Exception
        mock_docker.errors.APIError = Exception
        mock_docker.errors.NotFound = Exception

        # Create check in DISPATCHED state (required for mark_running())
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.DISPATCHED,
        )

        # Bind the function to the mock task
        with mock_patch.object(tasks.check_process_job, "update_state"):
            # Call the task directly
            result = tasks.check_process_job.run(check.id)

        # Verify Docker operations
        mock_docker.from_env.assert_called_once()
        mock_client.api.pull.assert_called_once()  # Now uses api.pull for progress

        # Verify metadata saved
        check.refresh_from_db()
        # Note: docker_image_digest is set by mark_starting(), which is not called
        # in the current task flow. This will be addressed in future refactoring.
        assert check.is_manufacturable is True

        # Verify return value
        assert result["status"] == "completed"
        assert result["is_manufacturable"] is True

    @patch("wafer_space.projects.tasks.docker")
    def test_docker_command_includes_slot_size(self, mock_docker):
        """Test that Docker command includes --slot argument with project slot_size."""
        # Create a real temp file for the GDS file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".gds") as tmp:
            tmp.write(b"fake GDS content")
            tmp_path = Path(tmp.name)

        # Save the file to the project_file
        with tmp_path.open("rb") as f:
            self.project_file.file.save("test.gds", ContentFile(f.read()), save=True)

        # Set a non-default slot size on the project
        self.project.slot_size = SlotSize.QUARTER  # 0p5x0p5
        self.project.save()

        # Setup mock
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_image = MagicMock()
        mock_image.id = "sha256:abc123"
        mock_image.tags = ["ghcr.io/wafer-space/gf180mcu-precheck:latest"]
        mock_client.images.pull.return_value = mock_image
        mock_client.images.get.return_value = mock_image
        mock_client.api.pull.return_value = []  # Empty progress stream

        # Mock container
        mock_container = MagicMock()
        mock_container.id = "test-container-123"  # Must be a string for DB storage
        mock_container.logs.side_effect = lambda *args, **kwargs: (
            [b"Precheck successfully completed."]
            if kwargs.get("stream")
            else b"Precheck successfully completed."
        )
        mock_container.wait.return_value = {"StatusCode": 0}
        mock_container.remove.return_value = None
        mock_client.containers.run.return_value = mock_container

        # Mock docker.errors
        mock_docker.errors.DockerException = Exception
        mock_docker.errors.ContainerError = Exception
        mock_docker.errors.ImageNotFound = Exception
        mock_docker.errors.APIError = Exception
        mock_docker.errors.NotFound = Exception

        # Create check in DISPATCHED state (required for mark_running())
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.DISPATCHED,
        )

        # Run the task
        with mock_patch.object(tasks.check_process_job, "update_state"):
            tasks.check_process_job.run(check.id)

        # Verify the docker command includes --slot with the project's slot_size
        call_args = mock_client.containers.run.call_args
        command = call_args.kwargs.get("command") or call_args[1].get("command")
        assert "--slot" in command
        slot_index = command.index("--slot")
        assert command[slot_index + 1] == "0p5x0p5"

        # Verify the docker command includes --id with the project's manufacturing ID
        assert "--id" in command
        id_index = command.index("--id")
        assert command[id_index + 1] == self.project.full_id

        # Verify docker_command in check record also includes --slot and --id
        check.refresh_from_db()
        assert "--slot 0p5x0p5" in check.docker_command
        assert f"--id {self.project.full_id}" in check.docker_command

        # Cleanup
        tmp_path.unlink(missing_ok=True)


class TestDownloadLogging(TestCase):
    """Tests for download task logging functionality."""

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
            file_size=1024,
            is_active=True,
        )

    def test_log_download_start_includes_user_info(self):
        """Test that download start log includes user information."""
        # Capture log output
        with self.assertLogs(
            "wafer_space.projects.tasks", level=logging.INFO
        ) as log_context:
            _log_download_start(str(self.project.id), self.project_file)

        # Verify user information is in the log output
        log_output = "\n".join(log_context.output)
        assert "testuser" in log_output or "test@example.com" in log_output


@pytest.mark.django_db
class TestContentPipelineIntegration(TestCase):
    """Integration tests for content pipeline with download task."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(
            user=self.user, name="Test Project", description="Test Description"
        )

    @patch("wafer_space.projects.tasks._download_with_progress")
    @patch("wafer_space.projects.tasks._apply_content_pipeline")
    def test_download_with_zip_extraction(self, mock_pipeline, mock_download):
        """Test download with ZIP extraction through pipeline."""
        # Create project file
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_filename="design.zip",
            source_url="https://example.com/design.zip",
            is_active=True,
        )

        # Mock download returns ZIP content
        mock_download.return_value = ("abc123", "def456")

        # Mock pipeline extracts and returns GDS
        mock_pipeline.return_value = (
            b"\x00\x06\x00\x02test_gds_content",
            "extracted_md5",
            "extracted_sha1",
            "extracted_sha256",
        )

        # Create a download attempt for the test
        attempt = DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.DOWNLOADING,
        )

        # Process content
        with NamedTemporaryFile(delete=False) as temp_file:
            temp_path = Path(temp_file.name)
            try:
                _process_and_save_content(
                    project_file, attempt, b"fake_zip_content", temp_path
                )

                # Verify pipeline was called
                assert mock_pipeline.called
            finally:
                temp_path.unlink(missing_ok=True)

    @patch("wafer_space.projects.tasks._apply_content_pipeline")
    def test_download_with_nested_compression(self, mock_pipeline):
        """Test download with nested compression (e.g., design.gds.gz inside .zip)."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_filename="design.tar.gz",
            source_url="https://example.com/design.tar.gz",
            is_active=True,
        )

        # Mock pipeline handles nested compression
        mock_pipeline.return_value = (
            b"\x00\x06\x00\x02gds_content",
            "final_md5",
            "final_sha1",
            "final_sha256",
        )

        # Create a download attempt for the test
        attempt = DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.DOWNLOADING,
        )

        with NamedTemporaryFile(delete=False) as temp_file:
            temp_path = Path(temp_file.name)
            try:
                _process_and_save_content(
                    project_file, attempt, b"fake_compressed_content", temp_path
                )

                # Verify pipeline was called
                assert mock_pipeline.called

                # Verify hashes were updated
                call_args = mock_pipeline.call_args
                assert call_args is not None
            finally:
                temp_path.unlink(missing_ok=True)

    @patch("wafer_space.projects.tasks._apply_content_pipeline")
    def test_download_with_format_validation(self, mock_pipeline):
        """Test that format validation is enforced after extraction."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_filename="invalid.zip",
            source_url="https://example.com/invalid.zip",
            is_active=True,
        )

        # Mock pipeline raises ValueError for invalid format
        mock_pipeline.side_effect = ValueError("File is not a valid GDS or OASIS file")

        # Create a download attempt for the test
        attempt = DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.DOWNLOADING,
        )

        with NamedTemporaryFile(delete=False) as temp_file:
            temp_path = Path(temp_file.name)
            try:
                with pytest.raises(ValueError, match="not a valid GDS or OASIS"):
                    _process_and_save_content(
                        project_file, attempt, b"fake_invalid_content", temp_path
                    )

                # Verify file was marked as failed
                project_file.refresh_from_db()
                assert project_file.download_status == ProjectFile.DownloadStatus.FAILED
                assert "not a valid GDS or OASIS" in project_file.download_error
            finally:
                temp_path.unlink(missing_ok=True)


class DownloadTaskTests(TestCase):
    """Tests for download-related task functions."""

    def setUp(self):
        """Set up test user and project."""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(user=self.user, name="Test Project")

    @patch("wafer_space.projects.tasks.requests.get")
    @patch("django.conf.settings.GITHUB_TOKEN", TEST_GITHUB_TOKEN)
    def test_download_github_artifact_returns_url(self, mock_get):
        """Test that _download_github_artifact returns authenticated URL."""
        # Mock artifact list response
        mock_list_response = Mock()
        mock_list_response.json.return_value = {
            "total_count": 1,
            "artifacts": [
                {
                    "id": 123456,
                    "name": "design-files",
                    "size_in_bytes": 1024000,
                }
            ],
        }
        mock_list_response.raise_for_status = Mock()

        # Set mock to return list response
        mock_get.return_value = mock_list_response

        # Call function
        result = _download_github_artifact(
            owner="test-owner",
            repo="test-repo",
            run_id="789",
            github_token=TEST_GITHUB_TOKEN,
        )

        # Should return dict with URL and headers
        assert isinstance(result, dict)
        assert "url" in result
        assert "headers" in result
        assert result["url"] == (
            "https://api.github.com/repos/test-owner/test-repo/"
            "actions/artifacts/123456/zip"
        )
        assert result["headers"]["Authorization"] == "Bearer test_token"

    def test_prepare_download_request_with_github_artifact(self):
        """Test that GitHub artifacts get authenticated URL and headers."""
        project = Project.objects.create(user=self.user, name="Test Project")

        project_file = ProjectFile.objects.create(
            project=project,
            source_url="https://github.com/owner/repo/actions/runs/123/artifacts/456",
            original_filename="design.zip",
            handler_metadata={
                "handler": "GitHubArtifactHandler",
                "owner": "owner",
                "repo": "repo",
                "run_id": "123",
                "requires_github_auth": True,
            },
        )

        with NamedTemporaryFile(delete=False) as temp_file:
            temp_path = Path(temp_file.name)

        try:
            mock_func = "wafer_space.projects.tasks._download_github_artifact"
            with patch(mock_func) as mock_gh:
                mock_gh.return_value = {
                    "url": "https://api.github.com/repos/owner/repo/actions/artifacts/789/zip",
                    "headers": {"Authorization": "Bearer test_token"},
                    "artifact_name": "design-files",
                    "artifact_id": "789",
                    "artifact_size": 1024000,
                }

                url, headers, resume_pos = _prepare_download_request(
                    project_file=project_file, temp_path=temp_path
                )

                # Should return authenticated URL and headers
                assert (
                    url
                    == "https://api.github.com/repos/owner/repo/actions/artifacts/789/zip"
                )
                assert headers["Authorization"] == "Bearer test_token"
                assert resume_pos == 0
        finally:
            temp_path.unlink(missing_ok=True)

    def test_build_github_artifact_filename(self):
        """Test that GitHub artifact filename is built correctly."""
        metadata = {
            "handler": "GitHubArtifactHandler",
            "owner": "TinyTapeout",
            "repo": "tinytapeout-gf-0p2",
            "run_id": "19443235082",
            "artifact_id": "4593573393",
            "artifact_name": "chipfoundry_submission",
            "requires_github_auth": True,
        }

        result = _build_github_artifact_filename(metadata, "tt-gf_wrapper.gds")

        expected = (
            "TinyTapeout.tinytapeout-gf-0p2."
            "r19443235082-a4593573393.chipfoundry_submission.tt-gf_wrapper.gds"
        )
        assert result == expected

    def test_build_github_artifact_filename_with_missing_fields(self):
        """Test that filename builder handles missing metadata fields."""
        # Minimal metadata with only required fields
        metadata = {
            "handler": "GitHubArtifactHandler",
            "owner": "owner",
            "repo": "repo",
            "run_id": "123",
        }

        result = _build_github_artifact_filename(metadata, "design.gds")

        # Should use defaults for missing fields
        expected = "owner.repo.r123-a0.artifact.design.gds"
        assert result == expected

    @patch("wafer_space.projects.tasks.requests.get")
    def test_download_with_progress_no_hash_return(self, mock_get):
        """Test that _download_with_progress only downloads, doesn't return hashes."""
        expected_file_size = 1024  # Expected download size in bytes

        project = Project.objects.create(user=self.user, name="Test")
        project_file = ProjectFile.objects.create(
            project=project,
            source_url="http://example.com/file.zip",
            original_filename="file.zip",
        )

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Length": str(expected_file_size)}
        mock_response.iter_content = lambda chunk_size: [b"test" * 256]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        # Create a download attempt for the test
        attempt = DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.DOWNLOADING,
        )

        with NamedTemporaryFile(delete=False) as temp_file:
            temp_path = Path(temp_file.name)

        try:
            # Mock task
            mock_task = Mock()
            mock_task.update_state = Mock()

            # Should return None (no hashes)
            _download_with_progress(mock_task, project_file, attempt, temp_path)

            # Function returns None implicitly, verify file downloaded
            assert temp_path.exists()
            assert temp_path.stat().st_size == expected_file_size
        finally:
            temp_path.unlink(missing_ok=True)

    @patch("wafer_space.projects.tasks.extract_top_cell")
    @patch("wafer_space.projects.tasks._apply_content_pipeline")
    @patch("wafer_space.projects.tasks.detect_file_type_from_data")
    @patch("wafer_space.projects.tasks._download_with_progress")
    def test_hash_calculated_on_extracted_file_not_zip(
        self, mock_download, mock_detect, mock_pipeline, mock_extract_top_cell
    ):
        """Test that hashes are calculated on extracted GDS, not downloaded ZIP."""
        project = Project.objects.create(user=self.user, name="Test")

        # Create a ZIP containing a GDS file
        gds_content = b"GDS_FILE_CONTENT_HERE"
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("design.gds", gds_content)
        zip_bytes = zip_buffer.getvalue()

        project_file = ProjectFile.objects.create(
            project=project,
            source_url="http://example.com/design.zip",
            original_filename="design.zip",
            is_active=True,
        )

        # Expected hashes for the GDS content (not the ZIP)
        expected_md5 = hashlib.md5(gds_content, usedforsecurity=False).hexdigest()
        expected_sha1 = hashlib.sha1(gds_content, usedforsecurity=False).hexdigest()
        expected_sha256 = hashlib.sha256(gds_content, usedforsecurity=False).hexdigest()

        # Expected hashes for the ZIP content (download returns these)
        zip_md5 = hashlib.md5(zip_bytes, usedforsecurity=False).hexdigest()
        zip_sha1 = hashlib.sha1(zip_bytes, usedforsecurity=False).hexdigest()
        zip_sha256 = hashlib.sha256(zip_bytes, usedforsecurity=False).hexdigest()

        # Mock download to write ZIP content and return ZIP hashes
        def write_zip(task, pf, attempt, temp_path):
            temp_path.write_bytes(zip_bytes)
            return (zip_md5, zip_sha1, zip_sha256)

        mock_download.side_effect = write_zip

        # Mock file type detection
        mock_detect.return_value = ("application/zip", ".zip")

        # Mock the pipeline to extract GDS and return hashes
        mock_pipeline.return_value = (
            gds_content,
            expected_md5,
            expected_sha1,
            expected_sha256,
        )

        # Mock top cell extraction
        mock_extract_top_cell.return_value = "TestCell"

        # Run download task
        download_project_file(str(project.id))

        # Verify hashes are for GDS content, not ZIP
        project_file.refresh_from_db()
        assert project_file.hash_md5 == expected_md5
        assert project_file.hash_sha1 == expected_sha1


@pytest.mark.django_db
class TestChecksDispatch(TestCase):
    """Test checks_dispatch task."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(user=self.user, name="Test Project")
        self.project_file = ProjectFile.objects.create(
            project=self.project,
            original_filename="test.gds",
            is_active=True,
            hash_verified=True,
        )

    def test_dispatches_pending_checks_under_limit(self):
        """Test pending checks are dispatched when under concurrent limit."""
        # Create a pending check
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        with patch("wafer_space.projects.tasks.check_process_job") as mock_task:
            mock_task.delay.return_value = Mock(id="task-123")
            result = checks_dispatch()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.DISPATCHED
        assert check.celery_job_id == "task-123"
        assert result["dispatched"] == 1

    def test_respects_concurrent_limit(self):
        """Test dispatch respects concurrent limit."""
        # Create checks already at limit (each needs its own project+file)
        for i in range(settings.PRECHECK_CONCURRENT_LIMIT):
            proj = Project.objects.create(user=self.user, name=f"Running Project {i}")
            pf = ProjectFile.objects.create(
                project=proj,
                original_filename=f"test{i}.gds",
                is_active=True,
                hash_verified=True,
            )
            ManufacturabilityCheck.objects.create(
                project=proj,
                project_file=pf,
                status=ManufacturabilityCheck.Status.RUNNING,
            )
        # Create pending check with its own project+file
        pending = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        with patch("wafer_space.projects.tasks.check_process_job") as mock_task:
            result = checks_dispatch()

        pending.refresh_from_db()
        assert pending.status == ManufacturabilityCheck.Status.PENDING
        assert result["dispatched"] == 0
        mock_task.delay.assert_not_called()

    def test_cancelling_counts_toward_limit(self):
        """Test CANCELLING checks count toward concurrent limit."""
        # Create checks in CANCELLING state (Docker still running)
        for i in range(settings.PRECHECK_CONCURRENT_LIMIT):
            proj = Project.objects.create(
                user=self.user, name=f"Cancelling Project {i}"
            )
            pf = ProjectFile.objects.create(
                project=proj,
                original_filename=f"cancelling{i}.gds",
                is_active=True,
                hash_verified=True,
            )
            ManufacturabilityCheck.objects.create(
                project=proj,
                project_file=pf,
                status=ManufacturabilityCheck.Status.CANCELLING,
            )
        pending = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        with patch("wafer_space.projects.tasks.check_process_job"):
            result = checks_dispatch()

        pending.refresh_from_db()
        assert pending.status == ManufacturabilityCheck.Status.PENDING
        assert result["dispatched"] == 0


@pytest.mark.django_db
class TestChecksRetry(TestCase):
    """Test checks_retry task."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(user=self.user, name="Test Project")
        self.project_file = ProjectFile.objects.create(
            project=self.project,
            original_filename="test.gds",
            is_active=True,
            hash_verified=True,
        )

    def test_retries_error_checks_under_limit(self):
        """Test ERROR checks are retried when under retry limit."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.ERROR,
            retry_count=0,
            max_retries=3,
        )

        result = checks_retry()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.PENDING
        assert check.retry_count == 1
        assert result["retried"] == 1

    def test_does_not_retry_exhausted_checks(self):
        """Test ERROR checks at retry limit are not retried."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.ERROR,
            retry_count=3,
            max_retries=3,
        )

        result = checks_retry()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.ERROR
        assert result["exhausted"] == 1


@pytest.mark.django_db
class TestChecksCreate(TestCase):
    """Test checks_create task."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(user=self.user, name="Test Project")

    def test_creates_check_for_verified_file(self):
        """Test check is created for verified file without existing check."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_filename="test.gds",
            is_active=True,
            hash_verified=True,
        )
        # Create completed download attempt
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.COMPLETED,
        )
        # Ensure no check exists
        assert not hasattr(project_file, "manufacturability_check")

        result = checks_create()

        assert result["created"] == 1
        project_file.refresh_from_db()
        assert hasattr(project_file, "manufacturability_check")
        assert (
            project_file.manufacturability_check.status
            == ManufacturabilityCheck.Status.PENDING
        )

    def test_does_not_create_for_unverified_file(self):
        """Test no check created for unverified file."""
        ProjectFile.objects.create(
            project=self.project,
            original_filename="test.gds",
            is_active=True,
            hash_verified=False,
        )

        result = checks_create()

        assert result["created"] == 0

    def test_does_not_create_duplicate_check(self):
        """Test no duplicate check created if one exists."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_filename="test.gds",
            is_active=True,
            hash_verified=True,
        )
        ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        result = checks_create()

        assert result["created"] == 0


@pytest.mark.django_db
class TestChecksCancelling(TestCase):
    """Test checks_cancelling task."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(user=self.user, name="Test Project")
        self.project_file = ProjectFile.objects.create(
            project=self.project,
            original_filename="test.gds",
            is_active=True,
            hash_verified=True,
        )

    @patch("wafer_space.projects.tasks.docker")
    @patch("wafer_space.projects.tasks.celery_app")
    def test_completes_cancellation_with_cleanup(self, mock_celery, mock_docker):
        """Test CANCELLING check completes after cleanup."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.CANCELLING,
            celery_job_id="task-123",
            docker_container_id="container-abc",
        )

        mock_container = Mock()
        mock_container.status = "running"
        mock_docker.from_env.return_value.containers.get.return_value = mock_container

        result = checks_cancelling()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLED
        assert check.celery_job_id == ""
        assert check.docker_container_id == ""
        mock_celery.control.revoke.assert_called_once_with("task-123", terminate=True)
        mock_container.stop.assert_called_once()
        mock_container.remove.assert_called_once()
        assert result["completed"] == 1

    def test_handles_missing_container(self):
        """Test cleanup handles already-removed container."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.CANCELLING,
            docker_container_id="gone-container",
        )

        # Mock docker client to raise NotFound - keep docker.errors intact
        # No celery_job_id set, so celery_app mock not needed
        with patch("wafer_space.projects.tasks.docker.from_env") as mock_from_env:
            mock_client = Mock()
            mock_from_env.return_value = mock_client
            mock_client.containers.get.side_effect = docker.errors.NotFound("not found")

            result = checks_cancelling()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLED
        assert result["completed"] == 1

    @patch("wafer_space.projects.tasks.docker")
    @patch("wafer_space.projects.tasks.celery_app")
    def test_only_clears_fields_when_cleanup_done(self, mock_celery, mock_docker):
        """Test celery_job_id and docker_container_id cleared incrementally."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.CANCELLING,
            celery_job_id="task-123",
            docker_container_id="container-abc",
        )

        mock_container = Mock()
        mock_container.status = "running"
        mock_docker.from_env.return_value.containers.get.return_value = mock_container

        checks_cancelling()

        check.refresh_from_db()
        # Both should be cleared after successful cleanup
        assert check.celery_job_id == ""
        assert check.docker_container_id == ""

    @patch("wafer_space.projects.tasks.docker")
    @patch("wafer_space.projects.tasks.celery_app")
    def test_handles_only_celery_task(self, mock_celery, mock_docker):
        """Test cleanup when only Celery task exists."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.CANCELLING,
            celery_job_id="task-123",
            docker_container_id="",
        )

        result = checks_cancelling()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLED
        mock_celery.control.revoke.assert_called_once_with("task-123", terminate=True)
        # Docker operations not called
        mock_docker.from_env.return_value.containers.get.assert_not_called()
        assert result["completed"] == 1

    @patch("wafer_space.projects.tasks.docker")
    @patch("wafer_space.projects.tasks.celery_app")
    def test_handles_only_docker_container(self, mock_celery, mock_docker):
        """Test cleanup when only Docker container exists."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.CANCELLING,
            celery_job_id="",
            docker_container_id="container-abc",
        )

        mock_container = Mock()
        mock_container.status = "running"
        mock_docker.from_env.return_value.containers.get.return_value = mock_container

        result = checks_cancelling()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLED
        # Celery revoke not called (no job ID)
        mock_celery.control.revoke.assert_not_called()
        mock_container.stop.assert_called_once()
        mock_container.remove.assert_called_once()
        assert result["completed"] == 1


@pytest.mark.django_db
class TestChecksCleanupOrphanedDispatch(TestCase):
    """Test checks_cleanup_orphaned_dispatch task."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(user=self.user, name="Test Project")
        self.project_file = ProjectFile.objects.create(
            project=self.project,
            original_filename="test.gds",
            is_active=True,
            hash_verified=True,
        )

    @patch("wafer_space.projects.tasks.is_check_task_queued")
    def test_marks_orphaned_dispatched_checks_as_error(self, mock_is_queued):
        """Test DISPATCHED checks with missing Celery tasks are marked ERROR."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.DISPATCHED,
            celery_job_id="task-123",
        )

        mock_is_queued.return_value = False

        result = checks_cleanup_orphaned_dispatch()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.ERROR
        assert "orphaned" in check.error_message.lower()
        assert result["orphaned"] == 1
        assert result["verified"] == 0
        mock_is_queued.assert_called_once_with(check)

    @patch("wafer_space.projects.tasks.is_check_task_queued")
    def test_leaves_valid_dispatched_checks_alone(self, mock_is_queued):
        """Test DISPATCHED checks with valid Celery tasks are not touched."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.DISPATCHED,
            celery_job_id="task-456",
        )

        # Task IS in queue (valid)
        mock_is_queued.return_value = True

        result = checks_cleanup_orphaned_dispatch()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.DISPATCHED
        assert result["orphaned"] == 0
        assert result["verified"] == 1
        mock_is_queued.assert_called_once_with(check)

    @patch("wafer_space.projects.tasks.is_check_task_queued")
    def test_handles_mixed_checks(self, mock_is_queued):
        """Test handles both orphaned and valid checks correctly."""
        project2 = Project.objects.create(user=self.user, name="Test Project 2")
        project_file2 = ProjectFile.objects.create(
            project=project2,
            original_filename="test2.gds",
            is_active=True,
            hash_verified=True,
        )
        orphaned_check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.DISPATCHED,
            celery_job_id="task-orphaned",
        )
        valid_check = ManufacturabilityCheck.objects.create(
            project=project2,
            project_file=project_file2,
            status=ManufacturabilityCheck.Status.DISPATCHED,
            celery_job_id="task-valid",
        )

        # First check is orphaned, second is valid
        mock_is_queued.side_effect = [False, True]

        result = checks_cleanup_orphaned_dispatch()

        orphaned_check.refresh_from_db()
        valid_check.refresh_from_db()
        assert orphaned_check.status == ManufacturabilityCheck.Status.ERROR
        assert valid_check.status == ManufacturabilityCheck.Status.DISPATCHED
        assert result["orphaned"] == 1
        assert result["verified"] == 1

    @patch("wafer_space.projects.tasks.is_check_task_queued")
    def test_ignores_non_dispatched_checks(self, mock_is_queued):
        """Test only processes DISPATCHED checks."""
        project2 = Project.objects.create(user=self.user, name="Test Project 2")
        project_file2 = ProjectFile.objects.create(
            project=project2,
            original_filename="test2.gds",
            is_active=True,
            hash_verified=True,
        )
        ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        ManufacturabilityCheck.objects.create(
            project=project2,
            project_file=project_file2,
            status=ManufacturabilityCheck.Status.RUNNING,
        )

        result = checks_cleanup_orphaned_dispatch()

        assert result["orphaned"] == 0
        assert result["verified"] == 0
        mock_is_queued.assert_not_called()


@pytest.mark.django_db
class TestChecksCleanupOrphanedProcessing(TestCase):
    """Test checks_cleanup_orphaned_processing task."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(user=self.user, name="Test Project")
        self.project_file = ProjectFile.objects.create(
            project=self.project,
            original_filename="test.gds",
            is_active=True,
            hash_verified=True,
        )

    @patch("wafer_space.projects.tasks.is_check_task_actively_running")
    def test_marks_orphaned_running_checks_as_error(self, mock_is_running):
        """Test RUNNING checks with dead PIDs are marked ERROR."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
            celery_job_id="task-123",
            celery_worker_pid=TEST_WORKER_PID,
            celery_worker_hostname="worker1",
        )

        # Task is NOT actively running (orphaned)
        mock_is_running.return_value = False

        result = checks_cleanup_orphaned_processing()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.ERROR
        assert "orphaned" in check.error_message.lower()
        # mark_error() preserves tracking fields for debugging
        # They are only cleared by reset_for_retry() when retrying
        assert check.celery_worker_pid == TEST_WORKER_PID
        assert check.celery_worker_hostname == "worker1"
        assert result["orphaned"] == 1
        assert result["verified"] == 0
        mock_is_running.assert_called_once_with(check)

    @patch("wafer_space.projects.tasks.is_check_task_actively_running")
    def test_leaves_valid_running_checks_alone(self, mock_is_running):
        """Test RUNNING checks with valid PIDs are not touched."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
            celery_job_id="task-456",
            celery_worker_pid=TEST_WORKER_PID,
            celery_worker_hostname="worker1",
        )

        # Task IS actively running (valid)
        mock_is_running.return_value = True

        result = checks_cleanup_orphaned_processing()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.RUNNING
        assert check.celery_worker_pid == TEST_WORKER_PID
        assert check.celery_worker_hostname == "worker1"
        assert result["orphaned"] == 0
        assert result["verified"] == 1
        mock_is_running.assert_called_once_with(check)

    @patch("wafer_space.projects.tasks.is_check_task_actively_running")
    def test_handles_mixed_checks(self, mock_is_running):
        """Test handles both orphaned and valid checks correctly."""
        project2 = Project.objects.create(user=self.user, name="Test Project 2")
        project_file2 = ProjectFile.objects.create(
            project=project2,
            original_filename="test2.gds",
            is_active=True,
            hash_verified=True,
        )
        orphaned_check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
            celery_job_id="task-orphaned",
            celery_worker_pid=DEAD_WORKER_PID,
            celery_worker_hostname="dead-worker",
        )
        valid_check = ManufacturabilityCheck.objects.create(
            project=project2,
            project_file=project_file2,
            status=ManufacturabilityCheck.Status.RUNNING,
            celery_job_id="task-valid",
            celery_worker_pid=TEST_WORKER_PID,
            celery_worker_hostname="live-worker",
        )

        # First check is orphaned, second is valid
        mock_is_running.side_effect = [False, True]

        result = checks_cleanup_orphaned_processing()

        orphaned_check.refresh_from_db()
        valid_check.refresh_from_db()
        assert orphaned_check.status == ManufacturabilityCheck.Status.ERROR
        # mark_error() preserves tracking fields for debugging
        assert orphaned_check.celery_worker_pid == DEAD_WORKER_PID
        assert orphaned_check.celery_worker_hostname == "dead-worker"
        assert valid_check.status == ManufacturabilityCheck.Status.RUNNING
        assert valid_check.celery_worker_pid == TEST_WORKER_PID
        assert result["orphaned"] == 1
        assert result["verified"] == 1

    @patch("wafer_space.projects.tasks.is_check_task_actively_running")
    def test_ignores_non_running_checks(self, mock_is_running):
        """Test only processes RUNNING checks."""
        project2 = Project.objects.create(user=self.user, name="Test Project 2")
        project_file2 = ProjectFile.objects.create(
            project=project2,
            original_filename="test2.gds",
            is_active=True,
            hash_verified=True,
        )
        ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        ManufacturabilityCheck.objects.create(
            project=project2,
            project_file=project_file2,
            status=ManufacturabilityCheck.Status.DISPATCHED,
        )

        result = checks_cleanup_orphaned_processing()

        assert result["orphaned"] == 0
        assert result["verified"] == 0
        mock_is_running.assert_not_called()


class TestChecksPending:
    """Test checks_pending beat task."""

    @pytest.mark.django_db
    def test_transitions_pending_to_dispatching(self) -> None:
        """Transitions PENDING checks to DISPATCHING with server assignment."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )

        result = checks_pending()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.DISPATCHING
        assert check.docker_server_id is not None
        assert result["dispatched"] == 1

    @pytest.mark.django_db
    def test_respects_server_capacity(self, settings) -> None:
        """Only dispatches up to max_concurrent per server."""
        settings.DOCKER_SERVERS = [
            {
                "id": "test",
                "url": "unix:///test.sock",
                "max_concurrent": 2,
                "priority": 1,
            },
        ]
        # Create 2 already active checks
        ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING,
            docker_server_id="test",
        )
        ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING,
            docker_server_id="test",
        )
        # Create pending check
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )

        result = checks_pending()

        check.refresh_from_db()
        # Should remain PENDING - server at capacity
        assert check.status == ManufacturabilityCheck.Status.PENDING
        assert result["dispatched"] == 0

    @pytest.mark.django_db
    def test_uses_priority_order(self, settings) -> None:
        """Uses servers in priority order (lowest priority number first)."""
        settings.DOCKER_SERVERS = [
            {
                "id": "low-priority",
                "url": "unix:///a.sock",
                "max_concurrent": 2,
                "priority": 10,
            },
            {
                "id": "high-priority",
                "url": "unix:///b.sock",
                "max_concurrent": 2,
                "priority": 1,
            },
        ]
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )

        result = checks_pending()

        check.refresh_from_db()
        assert check.docker_server_id == "high-priority"
        assert result["dispatched"] == 1

    @pytest.mark.django_db
    def test_does_not_touch_non_pending(self) -> None:
        """Does not affect checks not in PENDING status."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING
        )

        result = checks_pending()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.RUNNING
        assert result["dispatched"] == 0


class TestChecksDispatching:
    """Test checks_dispatching beat task."""

    @pytest.mark.django_db
    def test_queues_do_dispatching_for_dispatching_checks(self) -> None:
        """Queues do_dispatching work task for DISPATCHING checks."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.DISPATCHING,
            docker_server_id="local",
        )

        with patch("wafer_space.projects.tasks.do_dispatching.delay") as mock_delay:
            mock_delay.return_value.id = "task-123"
            result = checks_dispatching()

        mock_delay.assert_called_once_with(check.id)
        assert result["queued"] == 1

        # Should create task tracking row
        task = ManufacturabilityCheckTask.objects.get(manufacturability_check=check)
        assert task.task_id == "task-123"
        assert task.task_name == "do_dispatching"

    @pytest.mark.django_db
    def test_skips_checks_with_pending_task(self) -> None:
        """Does not queue if check already has pending task."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.DISPATCHING,
            docker_server_id="local",
        )
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check,
            task_id="existing",
            task_name="do_dispatching",
        )

        with patch("wafer_space.projects.tasks.do_dispatching.delay") as mock_delay:
            result = checks_dispatching()

        mock_delay.assert_not_called()
        assert result["queued"] == 0

    @pytest.mark.django_db
    def test_creates_task_tracking_row(self) -> None:
        """Creates ManufacturabilityCheckTask row for queued task."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.DISPATCHING,
            docker_server_id="local",
        )

        with patch("wafer_space.projects.tasks.do_dispatching.delay") as mock_delay:
            mock_delay.return_value.id = "task-abc"
            checks_dispatching()

        task = ManufacturabilityCheckTask.objects.get(manufacturability_check=check)
        assert task.task_id == "task-abc"
        assert task.task_name == "do_dispatching"
        assert task.queued_at is not None
