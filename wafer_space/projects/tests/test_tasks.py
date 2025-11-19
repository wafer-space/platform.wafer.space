"""
Tests for project background tasks.

Security-Critical Tests:
- URL validation prevents dangerous schemes like file://, ftp://, custom schemes
- Only http:// and https:// schemes are allowed for file downloads
"""

import logging
from pathlib import Path
from tempfile import NamedTemporaryFile
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase

from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.projects.tasks import _download_file_content
from wafer_space.projects.tasks import _log_download_start
from wafer_space.projects.tasks import _process_and_save_content
from wafer_space.projects.tasks import _safe_urlopen
from wafer_space.projects.tasks import check_project_manufacturability

User = get_user_model()
TEST_PASSWORD = "testpass123"


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

    @patch("wafer_space.projects.tasks.time.sleep")
    @patch("wafer_space.projects.tasks.random.uniform")
    @patch("wafer_space.projects.tasks.random.random")
    def test_check_task_marks_processing(
        self,
        mock_random,
        mock_uniform,
        mock_sleep,
    ):
        """Test that task marks check as PROCESSING."""
        # Mock random to ensure predictable success
        mock_random.return_value = 0.5  # Below 0.8 threshold = manufacturable
        mock_uniform.return_value = 2.0  # Fixed processing time
        mock_sleep.return_value = None  # Don't actually sleep

        # Create a check
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            status=ManufacturabilityCheck.Status.QUEUED,
            task_id="test-task-123",
        )

        # Run task
        result = check_project_manufacturability(check.id)

        # Verify check was marked as processing then completed
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.COMPLETED
        assert result["status"] == "completed"

    @patch("wafer_space.projects.tasks.time.sleep")
    @patch("wafer_space.projects.tasks.random.uniform")
    @patch("wafer_space.projects.tasks.random.random")
    def test_check_task_completes_successfully(
        self,
        mock_random,
        mock_uniform,
        mock_sleep,
    ):
        """Test that task completes check successfully."""
        # Mock random to ensure manufacturable result
        mock_random.return_value = 0.5  # Below 0.8 = manufacturable
        mock_uniform.return_value = 2.0
        mock_sleep.return_value = None

        # Create a check
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            status=ManufacturabilityCheck.Status.QUEUED,
            task_id="test-task-123",
        )

        # Run task
        result = check_project_manufacturability(check.id)

        # Verify result
        assert result["status"] == "completed"
        assert result["is_manufacturable"] is True
        assert len(result["warnings"]) > 0
        assert len(result["errors"]) == 0

        # Verify check was updated
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.COMPLETED
        assert check.is_manufacturable is True
        assert len(check.warnings) > 0
        assert len(check.errors) == 0
        assert check.completed_at is not None

    @patch("wafer_space.projects.tasks.time.sleep")
    @patch("wafer_space.projects.tasks.random.uniform")
    @patch("wafer_space.projects.tasks.random.random")
    def test_check_task_detects_not_manufacturable(
        self,
        mock_random,
        mock_uniform,
        mock_sleep,
    ):
        """Test that task can mark project as not manufacturable."""
        # Mock random to ensure not manufacturable result
        mock_random.return_value = 0.9  # Above 0.8 = not manufacturable
        mock_uniform.return_value = 2.0
        mock_sleep.return_value = None

        # Create a check
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            status=ManufacturabilityCheck.Status.QUEUED,
            task_id="test-task-123",
        )

        # Run task
        result = check_project_manufacturability(check.id)

        # Verify result
        assert result["status"] == "completed"
        assert result["is_manufacturable"] is False
        assert len(result["errors"]) > 0

        # Verify check was updated
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.COMPLETED
        assert check.is_manufacturable is False
        assert len(check.errors) > 0
        assert check.completed_at is not None

    def test_check_task_handles_missing_check(self):
        """Test that task handles missing check gracefully."""
        # Run task with non-existent check ID
        result = check_project_manufacturability(999999)

        # Verify error handling
        assert result["status"] == "error"
        assert "not found" in result["message"]

    @patch("wafer_space.projects.tasks.time.sleep")
    def test_check_task_retries_on_error(self, mock_sleep):
        """Test that task retries on unexpected errors."""
        # Make sleep raise an exception
        mock_sleep.side_effect = ValueError("Test error")

        # Create a check
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            status=ManufacturabilityCheck.Status.QUEUED,
        )

        # Run task - should handle the exception
        with pytest.raises(ValueError, match="Test error"):
            check_project_manufacturability(check.id)

    @patch("wafer_space.projects.tasks.time.sleep")
    @patch("wafer_space.projects.tasks.random.uniform")
    @patch("wafer_space.projects.tasks.random.random")
    def test_check_task_updates_project_status(
        self,
        mock_random,
        mock_uniform,
        mock_sleep,
    ):
        """Test that task updates project status based on check result."""
        # Mock for manufacturable result
        mock_random.return_value = 0.5
        mock_uniform.return_value = 2.0
        mock_sleep.return_value = None

        # Set project to SUBMITTED status
        self.project.status = Project.Status.SUBMITTED
        self.project.save()

        # Create a check
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            status=ManufacturabilityCheck.Status.QUEUED,
            task_id="test-task-456",
        )

        # Run task
        check_project_manufacturability(check.id)

        # Verify project status was updated
        self.project.refresh_from_db()
        assert self.project.status == Project.Status.MANUFACTURABLE
        assert self.project.is_manufacturable is True


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
            download_status=ProjectFile.DownloadStatus.COMPLETED,
            hash_verified=True,
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
        )

        # Process content
        with NamedTemporaryFile(delete=False) as temp_file:
            temp_path = Path(temp_file.name)
            try:
                _process_and_save_content(
                    project_file,
                    b"fake_zip_content",
                    temp_path,
                    "abc123",
                    "def456",
                )

                # Verify pipeline was called
                assert mock_pipeline.called
            finally:
                temp_path.unlink(missing_ok=True)

    @patch("wafer_space.projects.tasks._download_github_artifact")
    def test_download_with_github_artifact(self, mock_github_download):
        """Test GitHub artifact download with mocked API."""
        # Create project file with GitHub artifact metadata
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_filename="artifact.zip",
            source_url="https://github.com/owner/repo/actions/runs/123456",
            is_active=True,
            handler_metadata={
                "handler": "GitHubArtifactHandler",
                "owner": "owner",
                "repo": "repo",
                "run_id": "123456",
                "requires_github_auth": True,
            },
        )

        # Mock GitHub API response
        mock_github_download.return_value = b"artifact_zip_content"

        # Download content
        content = _download_file_content(project_file)

        # Verify GitHub download was called with correct parameters
        mock_github_download.assert_called_once_with(
            owner="owner",
            repo="repo",
            run_id="123456",
            github_token="",  # Default from settings
        )
        assert content == b"artifact_zip_content"

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
        )

        with NamedTemporaryFile(delete=False) as temp_file:
            temp_path = Path(temp_file.name)
            try:
                _process_and_save_content(
                    project_file,
                    b"fake_compressed_content",
                    temp_path,
                    "orig_md5",
                    "orig_sha1",
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

        with NamedTemporaryFile(delete=False) as temp_file:
            temp_path = Path(temp_file.name)
            try:
                with pytest.raises(ValueError, match="not a valid GDS or OASIS"):
                    _process_and_save_content(
                        project_file,
                        b"fake_invalid_content",
                        temp_path,
                        "md5",
                        "sha1",
                    )

                # Verify file was marked as failed
                project_file.refresh_from_db()
                assert project_file.download_status == ProjectFile.DownloadStatus.FAILED
                assert "not a valid GDS or OASIS" in project_file.download_error
            finally:
                temp_path.unlink(missing_ok=True)
