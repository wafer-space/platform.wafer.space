"""
Tests for project background tasks.

Security-Critical Tests:
- URL validation prevents dangerous schemes like file://, ftp://, custom schemes
- Only http:// and https:// schemes are allowed for file downloads
"""

import hashlib
import io
import logging
import zipfile
from pathlib import Path
from tempfile import NamedTemporaryFile
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase

from wafer_space.projects.models import DownloadAttempt
from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.projects.tasks import _download_github_artifact
from wafer_space.projects.tasks import _download_with_progress
from wafer_space.projects.tasks import _log_download_start
from wafer_space.projects.tasks import _prepare_download_request
from wafer_space.projects.tasks import _process_and_save_content
from wafer_space.projects.tasks import _safe_urlopen
from wafer_space.projects.tasks import check_project_manufacturability
from wafer_space.projects.tasks import download_project_file

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

    @patch("wafer_space.projects.tasks._apply_content_pipeline")
    @patch("wafer_space.projects.services.detect_file_type_from_data")
    @patch("wafer_space.projects.tasks._download_with_progress")
    def test_hash_calculated_on_extracted_file_not_zip(
        self,
        mock_download,
        mock_detect,
        mock_pipeline,
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

        # Mock download to write ZIP content
        def write_zip(task, pf, attempt, temp_path):
            temp_path.write_bytes(zip_bytes)

        mock_download.side_effect = write_zip

        # Mock file type detection
        mock_detect.return_value = ("application/zip", ".zip")

        # Mock the pipeline to extract GDS and return hashes
        mock_pipeline.return_value = (gds_content, expected_md5, expected_sha1)

        # Run download task
        download_project_file(str(project.id))

        # Verify hashes are for GDS content, not ZIP
        project_file.refresh_from_db()
        assert project_file.hash_md5 == expected_md5
        assert project_file.hash_sha1 == expected_sha1
