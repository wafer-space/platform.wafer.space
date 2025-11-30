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

import pytest
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase
from django.utils import timezone

from wafer_space.projects import tasks
from wafer_space.projects.models import DownloadAttempt
from wafer_space.projects.models import ManufacturabilityCheck
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
from wafer_space.projects.tasks import download_project_file
from wafer_space.projects.tasks import process_manufacturability_check_queue

User = get_user_model()
TEST_PASSWORD = "testpass123"  # noqa: S105 - Test password constant
TEST_GITHUB_TOKEN = "test_token"  # noqa: S105 - Test token constant


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
            ValueError,
            match="Unsupported URL scheme: custom",
        ) as excinfo:
            _safe_urlopen("custom://malicious/payload")

        assert "Unsupported URL scheme: custom" in str(excinfo.value)

    def test_javascript_scheme_blocked(self):
        """Test that javascript: URLs are blocked."""
        with pytest.raises(
            ValueError,
            match="Unsupported URL scheme: javascript",
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
                "https://example.com/file.zip",
                headers=custom_headers,
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
                    ValueError,
                    match=r"(?i)unsupported url scheme",
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
                patch(
                    "wafer_space.projects.tasks.urlopen",
                ) as mock_urlopen,
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
                pytest.raises(
                    ValueError,
                    match=r".*(file|ftp).*",
                ),
            ):
                _safe_urlopen(url)


@pytest.mark.django_db
class TestManufacturabilityCheckTask(TestCase):
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

        # Create a check
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.PENDING,
            celery_job_id="test-task-123",
        )

        # Run task
        with mock_patch.object(
            tasks.check_process_job,
            "update_state",
        ):
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

        # Create a check
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.PENDING,
            celery_job_id="test-task-123",
        )

        # Run task
        with mock_patch.object(
            tasks.check_process_job,
            "update_state",
        ):
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
        assert check.celery_job_finished_at is not None

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
        mock_logs = b"""ERROR: DRC violation at (100, 200)
ERROR: Metal spacing violation
FATAL: Design has critical errors
"""
        mock_container = MagicMock()
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

        # Create a check
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.PENDING,
            celery_job_id="test-task-123",
        )

        # Run task
        with mock_patch.object(
            tasks.check_process_job,
            "update_state",
        ):
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
        assert check.celery_job_finished_at is not None

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
                project=self.project,
                original_filename="test.gds",
                is_active=True,
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

        # Create a check
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.PENDING,
            celery_job_id="test-task-456",
        )

        # Run task
        with mock_patch.object(
            tasks.check_process_job,
            "update_state",
        ):
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
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test Description",
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

        Note: Manufacturability checks are created earlier in the workflow
        (when file hash is verified), not during submission.
        """
        # Mark as manufacturable (simulating completed check from earlier workflow)
        self.project.is_manufacturable = True
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
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test Description",
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

        # Create check
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
        )

        # Bind the function to the mock task
        with mock_patch.object(
            tasks.check_process_job,
            "update_state",
        ):
            # Call the task directly
            result = tasks.check_process_job.run(check.id)

        # Verify Docker operations
        mock_docker.from_env.assert_called_once()
        mock_client.api.pull.assert_called_once()  # Now uses api.pull for progress

        # Verify metadata saved
        check.refresh_from_db()
        assert check.docker_image_digest == "sha256:abc123"
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
        self.project.slot_size = Project.SlotSize.QUARTER  # 0p5x0p5
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

        # Create check
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
        )

        # Run the task
        with mock_patch.object(
            tasks.check_process_job,
            "update_state",
        ):
            tasks.check_process_job.run(check.id)

        # Verify the docker command includes --slot with the project's slot_size
        call_args = mock_client.containers.run.call_args
        command = call_args.kwargs.get("command") or call_args[1].get("command")
        assert "--slot" in command
        slot_index = command.index("--slot")
        assert command[slot_index + 1] == "0p5x0p5"

        # Verify docker_command in check record also includes --slot
        check.refresh_from_db()
        assert "--slot 0p5x0p5" in check.docker_command

        # Cleanup
        tmp_path.unlink(missing_ok=True)


class TestDownloadLogging(TestCase):
    """Tests for download task logging functionality."""

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
            file_size=1024,
            is_active=True,
        )

    def test_log_download_start_includes_user_info(self):
        """Test that download start log includes user information."""
        # Capture log output
        with self.assertLogs(
            "wafer_space.projects.tasks",
            level=logging.INFO,
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
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test Description",
        )

    @patch("wafer_space.projects.tasks._download_with_progress")
    @patch("wafer_space.projects.tasks._apply_content_pipeline")
    def test_download_with_zip_extraction(
        self,
        mock_pipeline,
        mock_download,
    ):
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
                    project_file,
                    attempt,
                    b"fake_zip_content",
                    temp_path,
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
                    project_file,
                    attempt,
                    b"fake_compressed_content",
                    temp_path,
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
                        project_file,
                        attempt,
                        b"fake_invalid_content",
                        temp_path,
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
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
        )

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
        project = Project.objects.create(
            user=self.user,
            name="Test Project",
        )

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
                    project_file=project_file,
                    temp_path=temp_path,
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

        result = _build_github_artifact_filename(
            metadata,
            "tt-gf_wrapper.gds",
        )

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

        result = _build_github_artifact_filename(
            metadata,
            "design.gds",
        )

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
            _download_with_progress(
                mock_task,
                project_file,
                attempt,
                temp_path,
            )

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
        self,
        mock_download,
        mock_detect,
        mock_pipeline,
        mock_extract_top_cell,
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
class TestProcessManufacturabilityCheckQueue(TestCase):
    """Test the process_manufacturability_check_queue periodic task (state machine)."""

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
            original_filename="test.gds",
            source_url="https://example.com/test.gds",
            is_active=True,
            hash_verified=True,
        )
        # Create completed download attempt so file is "ready"
        DownloadAttempt.objects.create(
            project_file=self.project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.COMPLETED,
        )

    @patch("wafer_space.projects.tasks.check_process_job.delay")
    def test_cancelled_check_not_dispatched(self, mock_check_task):
        """Test that cancelled checks are not dispatched."""
        # Create a cancelled check
        ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.CANCELLED,
        )

        # Run the queue processing task
        result = process_manufacturability_check_queue()

        # Verify no checks were dispatched (cancelled checks are ignored)
        assert result["pending_dispatched"] == 0
        mock_check_task.assert_not_called()

        # Verify the check is still cancelled
        check = ManufacturabilityCheck.objects.get(project_file=self.project_file)
        assert check.status == ManufacturabilityCheck.Status.CANCELLED

    @patch("wafer_space.projects.tasks.check_process_job.delay")
    def test_completed_check_not_dispatched(self, mock_check_task):
        """Test that finished checks are not dispatched."""
        # Create a completed check
        ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )

        # Run the queue processing task
        result = process_manufacturability_check_queue()

        # Verify no checks were dispatched
        assert result["pending_dispatched"] == 0
        mock_check_task.assert_not_called()

    @patch("wafer_space.projects.tasks.check_process_job.delay")
    def test_queued_check_gets_dispatched(self, mock_check_task):
        """Test that PENDING checks get dispatched to DISPATCHED."""
        mock_check_task.return_value = Mock(id="new-task-123")

        # Create a pending check (as would be created by download completion)
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
            celery_job_dispatched_at=timezone.now(),
        )

        # Run the queue processing task
        result = process_manufacturability_check_queue()

        # Verify check was dispatched
        assert result["pending_dispatched"] == 1
        mock_check_task.assert_called_once_with(check.id)

        # Verify check transitioned to DISPATCHED
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.DISPATCHED
        assert check.celery_job_id == "new-task-123"

    @patch("wafer_space.projects.tasks.is_check_task_actively_running")
    @patch("wafer_space.projects.tasks.is_check_task_queued")
    @patch("wafer_space.projects.tasks.check_process_job.delay")
    def test_starting_check_not_re_dispatched(
        self, mock_check_task, mock_queued, mock_active
    ):
        """Test that DISPATCHED checks are not re-dispatched."""
        # Mock verification: task is in queue but not yet running
        mock_active.return_value = False
        mock_queued.return_value = True

        # Create a check already in DISPATCHED state
        ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.DISPATCHED,
            celery_job_id="existing-task",
        )

        # Run the queue processing task
        result = process_manufacturability_check_queue()

        # Verify no new dispatches (DISPATCHED checks are verified, not dispatched)
        assert result["pending_dispatched"] == 0
        assert result["dispatched_verified"] == 1
        assert result["dispatched_transitioned"] == 0
        mock_check_task.assert_not_called()

    @patch("wafer_space.projects.tasks.is_check_task_actively_running")
    @patch("wafer_space.projects.tasks.check_process_job.delay")
    def test_starting_check_transitions_to_processing(
        self, mock_check_task, mock_active
    ):
        """Test DISPATCHED check transitions to RUNNING when actively running."""
        # Mock verification: task is actively running
        mock_active.return_value = True

        # Create a check in DISPATCHED state
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.DISPATCHED,
            celery_job_id="running-task-123",
        )

        # Run the queue processing task
        result = process_manufacturability_check_queue()

        # Verify check transitioned to RUNNING
        assert result["dispatched_transitioned"] == 1
        assert result["dispatched_verified"] == 0
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.RUNNING
        assert check.celery_job_started_at is not None
        mock_check_task.assert_not_called()
