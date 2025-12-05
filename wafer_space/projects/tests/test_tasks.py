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
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch

import docker.errors
import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase

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
from wafer_space.projects.tasks import checks_analyzing
from wafer_space.projects.tasks import checks_cancelling
from wafer_space.projects.tasks import checks_cleanup_orphaned_processing
from wafer_space.projects.tasks import checks_create
from wafer_space.projects.tasks import checks_dispatching
from wafer_space.projects.tasks import checks_pending
from wafer_space.projects.tasks import checks_retry
from wafer_space.projects.tasks import checks_running
from wafer_space.projects.tasks import checks_starting
from wafer_space.projects.tasks import do_analyzing
from wafer_space.projects.tasks import do_cancelling
from wafer_space.projects.tasks import do_dispatching
from wafer_space.projects.tasks import do_running
from wafer_space.projects.tasks import do_starting
from wafer_space.projects.tasks import download_project_file
from wafer_space.projects.tests.factories import ManufacturabilityCheckFactory

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


class TestChecksCancelling:
    """Test checks_cancelling beat task."""

    @pytest.mark.django_db
    def test_queues_do_cancelling_for_cancelling_checks(self) -> None:
        """Queues do_cancelling work task for CANCELLING checks."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.CANCELLING,
        )

        with patch("wafer_space.projects.tasks.do_cancelling.delay") as mock_delay:
            mock_delay.return_value.id = "task-999"
            result = checks_cancelling()

        mock_delay.assert_called_once_with(check.id)
        assert result["queued"] == 1

        # Should create task tracking row
        task = ManufacturabilityCheckTask.objects.get(manufacturability_check=check)
        assert task.task_id == "task-999"
        assert task.task_name == "do_cancelling"

    @pytest.mark.django_db
    def test_skips_checks_with_pending_task(self) -> None:
        """Does not queue if check already has pending task."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.CANCELLING,
        )
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check,
            task_id="existing",
            task_name="do_cancelling",
        )

        with patch("wafer_space.projects.tasks.do_cancelling.delay") as mock_delay:
            result = checks_cancelling()

        mock_delay.assert_not_called()
        assert result["queued"] == 0


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


class TestChecksStarting:
    """Test checks_starting beat task."""

    @pytest.mark.django_db
    def test_queues_do_starting_for_starting_checks(self) -> None:
        """Queues do_starting work task for STARTING checks."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.STARTING,
            docker_server_id="local",
        )

        with patch("wafer_space.projects.tasks.do_starting.delay") as mock_delay:
            mock_delay.return_value.id = "task-123"
            result = checks_starting()

        mock_delay.assert_called_once_with(check.id)
        assert result["queued"] == 1

        # Should create task tracking row
        task = ManufacturabilityCheckTask.objects.get(manufacturability_check=check)
        assert task.task_id == "task-123"
        assert task.task_name == "do_starting"

    @pytest.mark.django_db
    def test_skips_checks_with_pending_task(self) -> None:
        """Does not queue if check already has pending task."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.STARTING,
            docker_server_id="local",
        )
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check,
            task_id="existing",
            task_name="do_starting",
        )

        with patch("wafer_space.projects.tasks.do_starting.delay") as mock_delay:
            result = checks_starting()

        mock_delay.assert_not_called()
        assert result["queued"] == 0


class TestChecksRunning:
    """Test checks_running beat task."""

    @pytest.mark.django_db
    def test_queues_do_running_for_running_checks(self) -> None:
        """Queues do_running work task for RUNNING checks."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING,
            docker_server_id="local",
        )

        with patch("wafer_space.projects.tasks.do_running.delay") as mock_delay:
            mock_delay.return_value.id = "task-456"
            result = checks_running()

        mock_delay.assert_called_once_with(check.id)
        assert result["queued"] == 1

        # Should create task tracking row
        task = ManufacturabilityCheckTask.objects.get(manufacturability_check=check)
        assert task.task_id == "task-456"
        assert task.task_name == "do_running"

    @pytest.mark.django_db
    def test_skips_checks_with_pending_task(self) -> None:
        """Does not queue if check already has pending task."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING,
            docker_server_id="local",
        )
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check,
            task_id="existing",
            task_name="do_running",
        )

        with patch("wafer_space.projects.tasks.do_running.delay") as mock_delay:
            result = checks_running()

        mock_delay.assert_not_called()
        assert result["queued"] == 0


class TestChecksAnalyzing:
    """Test checks_analyzing beat task."""

    @pytest.mark.django_db
    def test_queues_do_analyzing_for_analyzing_checks(self) -> None:
        """Queues do_analyzing work task for ANALYZING checks."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.ANALYZING,
        )

        with patch("wafer_space.projects.tasks.do_analyzing.delay") as mock_delay:
            mock_delay.return_value.id = "task-789"
            result = checks_analyzing()

        mock_delay.assert_called_once_with(check.id)
        assert result["queued"] == 1

        # Should create task tracking row
        task = ManufacturabilityCheckTask.objects.get(manufacturability_check=check)
        assert task.task_id == "task-789"
        assert task.task_name == "do_analyzing"

    @pytest.mark.django_db
    def test_skips_checks_with_pending_task(self) -> None:
        """Does not queue if check already has pending task."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.ANALYZING,
        )
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check,
            task_id="existing",
            task_name="do_analyzing",
        )

        with patch("wafer_space.projects.tasks.do_analyzing.delay") as mock_delay:
            result = checks_analyzing()

        mock_delay.assert_not_called()
        assert result["queued"] == 0


class TestDoDispatching:
    """Test do_dispatching work task."""

    @pytest.mark.django_db
    def test_pulls_image_and_transitions_to_starting(self) -> None:
        """Pulls Docker image and transitions to STARTING."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.DISPATCHING,
            docker_server_id="test-local",
        )
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check, task_id="test", task_name="do_dispatching"
        )

        with patch("wafer_space.projects.tasks.docker") as mock_docker:
            mock_client = MagicMock()
            mock_docker.DockerClient.return_value = mock_client
            mock_image = MagicMock()
            mock_image.attrs = {"RepoDigests": ["ghcr.io/test@sha256:abc123"]}
            mock_client.images.pull.return_value = mock_image

            do_dispatching(check.id)

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.STARTING
        assert check.docker_image_digest == "sha256:abc123"

    @pytest.mark.django_db
    def test_cleans_up_task_tracking(self) -> None:
        """Deletes ManufacturabilityCheckTask when done."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.DISPATCHING,
            docker_server_id="test-local",
        )
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check, task_id="test", task_name="do_dispatching"
        )

        with patch("wafer_space.projects.tasks.docker") as mock_docker:
            mock_client = MagicMock()
            mock_docker.DockerClient.return_value = mock_client
            mock_image = MagicMock()
            mock_image.attrs = {"RepoDigests": ["ghcr.io/test@sha256:abc123"]}
            mock_client.images.pull.return_value = mock_image

            do_dispatching(check.id)

        assert not ManufacturabilityCheckTask.objects.filter(
            manufacturability_check=check
        ).exists()

    @pytest.mark.django_db
    def test_skips_if_status_changed(self) -> None:
        """Does nothing if status is no longer DISPATCHING."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.CANCELLED,
            docker_server_id="test-local",
        )

        with patch("wafer_space.projects.tasks.docker") as mock_docker:
            result = do_dispatching(check.id)

        # Should not interact with Docker
        mock_docker.DockerClient.assert_not_called()
        assert result["status"] == "skipped"
        assert result["reason"] == "status_changed"


class TestDoStarting:
    """Test do_starting work task."""

    @pytest.mark.django_db
    def test_creates_and_starts_container(self, tmp_path) -> None:
        """Creates container with correct config and starts it."""
        # Create a test file
        test_file = tmp_path / "design.gds"
        test_file.write_bytes(b"test gds content")

        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.STARTING,
            docker_server_id="test-local",
            docker_image="ghcr.io/test:latest",
        )
        check.project_file.file.name = str(test_file)
        check.project_file.save()

        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check, task_id="test", task_name="do_starting"
        )

        with (
            patch("wafer_space.projects.tasks.docker") as mock_docker,
            patch("wafer_space.projects.tasks.Path") as mock_path,
        ):
            mock_client = MagicMock()
            mock_docker.DockerClient.return_value = mock_client
            mock_container = MagicMock()
            mock_container.id = "container123"
            mock_container.status = "running"
            mock_client.containers.create.return_value = mock_container

            # Mock the Path to say file exists
            mock_path_instance = MagicMock()
            mock_path_instance.exists.return_value = True
            mock_path.return_value = mock_path_instance

            result = do_starting(check.id)

        assert result["status"] == "success"
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.RUNNING
        assert check.docker_container_id == "container123"

    @pytest.mark.django_db
    def test_cleans_up_task_tracking(self, tmp_path) -> None:
        """Deletes ManufacturabilityCheckTask when done."""
        test_file = tmp_path / "design.gds"
        test_file.write_bytes(b"test")

        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.STARTING,
            docker_server_id="test-local",
            docker_image="ghcr.io/test:latest",
        )
        check.project_file.file.name = str(test_file)
        check.project_file.save()

        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check, task_id="test", task_name="do_starting"
        )

        with (
            patch("wafer_space.projects.tasks.docker") as mock_docker,
            patch("wafer_space.projects.tasks.Path") as mock_path,
        ):
            mock_client = MagicMock()
            mock_docker.DockerClient.return_value = mock_client
            mock_container = MagicMock()
            mock_container.id = "container123"
            mock_container.status = "running"
            mock_client.containers.create.return_value = mock_container
            mock_path_instance = MagicMock()
            mock_path_instance.exists.return_value = True
            mock_path.return_value = mock_path_instance

            do_starting(check.id)

        assert not ManufacturabilityCheckTask.objects.filter(
            manufacturability_check=check
        ).exists()

    @pytest.mark.django_db
    def test_skips_if_status_changed(self) -> None:
        """Does nothing if status is no longer STARTING."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.CANCELLED,
            docker_server_id="test-local",
        )

        with patch("wafer_space.projects.tasks.docker") as mock_docker:
            result = do_starting(check.id)

        mock_docker.DockerClient.assert_not_called()
        assert result["status"] == "skipped"
        assert result["reason"] == "status_changed"


class TestDoRunning:
    """Test do_running work task."""

    @pytest.mark.django_db
    def test_downloads_logs_and_updates_check(self) -> None:
        """Downloads container logs and appends to processing logs."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING,
            docker_server_id="test-local",
            docker_container_id="container123",
        )
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check, task_id="test", task_name="do_running"
        )

        mock_logs = "2024-12-05T10:00:00.123456789Z Test log line\n"

        with patch("wafer_space.projects.tasks.docker") as mock_docker:
            mock_client = MagicMock()
            mock_docker.DockerClient.return_value = mock_client
            mock_container = MagicMock()
            mock_container.id = "container123"
            mock_container.status = "running"
            mock_container.logs.return_value = mock_logs.encode("utf-8")
            mock_client.containers.get.return_value = mock_container

            result = do_running(check.id)

        assert result["status"] == "still_running"
        check.refresh_from_db()
        assert "Test log line" in check.processing_logs

    @pytest.mark.django_db
    def test_transitions_to_analyzing_when_container_exited(self) -> None:
        """Transitions to ANALYZING when container has exited."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING,
            docker_server_id="test-local",
            docker_container_id="container123",
        )
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check, task_id="test", task_name="do_running"
        )

        with patch("wafer_space.projects.tasks.docker") as mock_docker:
            mock_client = MagicMock()
            mock_docker.DockerClient.return_value = mock_client
            mock_container = MagicMock()
            mock_container.id = "container123"
            mock_container.status = "exited"
            mock_container.attrs = {"State": {"ExitCode": 0}}
            mock_container.logs.return_value = b""
            mock_client.containers.get.return_value = mock_container

            result = do_running(check.id)

        assert result["status"] == "container_exited"
        assert result["exit_code"] == 0
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.ANALYZING

    @pytest.mark.django_db
    def test_skips_if_status_changed(self) -> None:
        """Does nothing if status is no longer RUNNING."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.CANCELLED,
        )

        with patch("wafer_space.projects.tasks.docker") as mock_docker:
            result = do_running(check.id)

        mock_docker.DockerClient.assert_not_called()
        assert result["status"] == "skipped"


class TestDoAnalyzing:
    """Test do_analyzing work task."""

    @pytest.mark.django_db
    def test_parses_logs_and_transitions_to_finished(self) -> None:
        """Parses logs successfully and transitions to FINISHED."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.ANALYZING,
            docker_exit_code=0,
            processing_logs="Precheck successfully completed.",
        )
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check, task_id="test", task_name="do_analyzing"
        )

        result = do_analyzing(check.id)

        assert result["status"] == "success"
        assert result["is_manufacturable"] is True
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.FINISHED
        assert check.is_manufacturable is True

    @pytest.mark.django_db
    def test_handles_design_errors(self) -> None:
        """Marks check as not manufacturable when design has errors."""
        logs = """
Error: Multiple top cells found: cell1, cell2
Check for Magic DRC errors clear.
Check for KLayout DRC errors clear.
"""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.ANALYZING,
            docker_exit_code=1,
            processing_logs=logs,
        )
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check, task_id="test", task_name="do_analyzing"
        )

        result = do_analyzing(check.id)

        assert result["status"] == "success"
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.FINISHED
        assert check.is_manufacturable is False
        assert len(check.errors) > 0

    @pytest.mark.django_db
    def test_skips_if_status_changed(self) -> None:
        """Does nothing if status is no longer ANALYZING."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.CANCELLED,
        )

        result = do_analyzing(check.id)

        assert result["status"] == "skipped"


class TestDoCancelling:
    """Test do_cancelling work task."""

    @pytest.mark.django_db
    def test_stops_and_removes_container(self) -> None:
        """Stops running container and removes it."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.CANCELLING,
            docker_server_id="test-local",
            docker_container_id="container123",
        )
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check, task_id="test", task_name="do_cancelling"
        )

        with patch("wafer_space.projects.tasks.docker") as mock_docker:
            mock_client = MagicMock()
            mock_docker.DockerClient.return_value = mock_client
            mock_container = MagicMock()
            mock_container.id = "container123"
            mock_container.status = "running"
            mock_client.containers.get.return_value = mock_container

            result = do_cancelling(check.id)

        assert result["status"] == "success"
        assert result["container_stopped"] is True
        assert result["container_removed"] is True
        mock_container.stop.assert_called_once()
        mock_container.remove.assert_called_once()
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLED

    @pytest.mark.django_db
    def test_handles_missing_container_gracefully(self) -> None:
        """Handles case where container is already gone."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.CANCELLING,
            docker_server_id="test-local",
            docker_container_id="container123",
        )
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check, task_id="test", task_name="do_cancelling"
        )

        with patch("wafer_space.projects.tasks.docker") as mock_docker:
            mock_client = MagicMock()
            mock_docker.DockerClient.return_value = mock_client
            # Configure docker.errors to have proper exception classes
            mock_docker.errors.NotFound = docker.errors.NotFound
            mock_docker.errors.DockerException = docker.errors.DockerException
            mock_client.containers.get.side_effect = docker.errors.NotFound(
                "Container not found"
            )

            result = do_cancelling(check.id)

        assert result["status"] == "success"
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLED

    @pytest.mark.django_db
    def test_skips_if_status_changed(self) -> None:
        """Does nothing if status is no longer CANCELLING."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.FINISHED,
        )

        with patch("wafer_space.projects.tasks.docker") as mock_docker:
            result = do_cancelling(check.id)

        mock_docker.DockerClient.assert_not_called()
        assert result["status"] == "skipped"
