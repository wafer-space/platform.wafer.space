"""
Tests for project background tasks.

Security-Critical Tests:
- URL validation prevents dangerous schemes like file://, ftp://, custom schemes
- Only http:// and https:// schemes are allowed for file downloads
"""

import base64
import hashlib
import io
import logging
import tarfile
import zipfile
from datetime import timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from tempfile import mkdtemp
from typing import IO
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch

import docker
import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from wafer_space.projects.file_type_utils import GDS_SIGNATURE
from wafer_space.projects.models import DownloadAttempt
from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import ManufacturabilityCheckpoint
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
from wafer_space.projects.tasks import checks_create
from wafer_space.projects.tasks import checks_dispatching
from wafer_space.projects.tasks import checks_pending
from wafer_space.projects.tasks import checks_retry
from wafer_space.projects.tasks import checks_running
from wafer_space.projects.tasks import checks_starting
from wafer_space.projects.tasks import do_analyzing
from wafer_space.projects.tasks import do_dispatching
from wafer_space.projects.tasks import do_running
from wafer_space.projects.tasks import do_starting
from wafer_space.projects.tasks import download_project_file
from wafer_space.projects.tasks_checks import _save_output_gds
from wafer_space.projects.tasks_checks import checks_cleanup
from wafer_space.projects.tasks_checks import checks_cleanup_stale_pending_tasks
from wafer_space.projects.tasks_checks import checks_drc_update_requeue
from wafer_space.projects.tasks_download import _apply_post_download_processing
from wafer_space.projects.tasks_download import _initialize_hash_calculators
from wafer_space.projects.tests.factories import ManufacturabilityCheckFactory
from wafer_space.projects.tests.factories import ProjectFactory
from wafer_space.projects.tests.factories import ProjectFileFactory
from wafer_space.projects.tests.read_instrumentation import RecordingPath
from wafer_space.shuttles.tests.factories import ShuttleFactory

User = get_user_model()
TEST_PASSWORD = "testpass123"  # noqa: S105 - Test password constant
TEST_GITHUB_TOKEN = "test_token"  # noqa: S105 - Test token constant
TEST_WORKER_PID = 12345  # Test worker process ID constant
DEAD_WORKER_PID = 99999  # Test dead worker process ID constant

# Test constants for checkpoint stats
TEST_MEMORY_USAGE = 1048576  # 1 MB
TEST_MEMORY_LIMIT = 4294967296  # 4 GB
TEST_CPU_COUNT = 2
TEST_BLOCK_READ = 1024
TEST_BLOCK_WRITE = 2048
TEST_NETWORK_RX = 500
TEST_NETWORK_TX = 300
TEST_CHECKPOINT_COUNT = 2
TEST_CPU_PERCENT_TOLERANCE = 0.01
TEST_OUTDATED_CHECKS_COUNT = 2  # Number of outdated checks for testing
TEST_PROJECT_COUNT_WITH_REFERENCE = 2  # self.project + reference project


class URLValidationSecurityTests(TestCase):
    """Security tests for URL validation in file download functionality."""

    def test_valid_http_url_allowed(self):
        """Test that http:// URLs are accepted."""
        with patch("wafer_space.projects.tasks_download.urlopen") as mock_urlopen:
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
        with patch("wafer_space.projects.tasks_download.urlopen") as mock_urlopen:
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
        with patch("wafer_space.projects.tasks_download.urlopen") as mock_urlopen:
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

        with patch("wafer_space.projects.tasks_download.urlopen") as mock_urlopen:
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
                patch("wafer_space.projects.tasks_download.urlopen") as mock_urlopen,
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
        self.project.submitted_file = self.project_file
        self.project.status = Project.Status.MANUFACTURABLE
        self.project.save()
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )

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
            "wafer_space.projects.tasks_download", level=logging.INFO
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

    @patch("wafer_space.projects.tasks_download._download_with_progress")
    @patch("wafer_space.projects.tasks_download._apply_content_pipeline")
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

        # Mock pipeline extracts a GDS file into the pipeline temp dir
        gds_content = b"\x00\x06\x00\x02test_gds_content"

        def fake_pipeline(pf, temp_path, pipeline_temp_dir):
            output_path = pipeline_temp_dir / "design.gds"
            output_path.write_bytes(gds_content)
            return (
                output_path,
                len(gds_content),
                "extracted_md5",
                "extracted_sha1",
                "extracted_sha256",
            )

        mock_pipeline.side_effect = fake_pipeline

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
                _process_and_save_content(project_file, attempt, temp_path)

                # Verify pipeline was called
                assert mock_pipeline.called
            finally:
                temp_path.unlink(missing_ok=True)

    @patch("wafer_space.projects.tasks_download._apply_content_pipeline")
    def test_download_with_nested_compression(self, mock_pipeline):
        """Test download with nested compression (e.g., design.gds.gz inside .zip)."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_filename="design.tar.gz",
            source_url="https://example.com/design.tar.gz",
            is_active=True,
        )

        # Mock pipeline handles nested compression
        gds_content = b"\x00\x06\x00\x02gds_content"

        def fake_pipeline(pf, temp_path, pipeline_temp_dir):
            output_path = pipeline_temp_dir / "design.gds"
            output_path.write_bytes(gds_content)
            return (
                output_path,
                len(gds_content),
                "final_md5",
                "final_sha1",
                "final_sha256",
            )

        mock_pipeline.side_effect = fake_pipeline

        # Create a download attempt for the test
        attempt = DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.DOWNLOADING,
        )

        with NamedTemporaryFile(delete=False) as temp_file:
            temp_path = Path(temp_file.name)
            try:
                _process_and_save_content(project_file, attempt, temp_path)

                # Verify pipeline was called
                assert mock_pipeline.called

                # Verify hashes were updated
                call_args = mock_pipeline.call_args
                assert call_args is not None
            finally:
                temp_path.unlink(missing_ok=True)

    @patch("wafer_space.projects.tasks_download.get_temp_dir_for_file")
    @patch("wafer_space.projects.tasks_download._apply_content_pipeline")
    def test_download_with_format_validation(self, mock_pipeline, mock_get_temp_dir):
        """Test that format validation is enforced after extraction."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_filename="invalid.zip",
            source_url="https://example.com/invalid.zip",
            is_active=True,
        )

        # Mock pipeline raises ValueError for invalid format
        mock_pipeline.side_effect = ValueError("File is not a valid GDS or OASIS file")

        # Use a known pipeline temp dir so its cleanup can be asserted
        pipeline_temp_dir = Path(mkdtemp(prefix="pipeline_temp_test_"))
        mock_get_temp_dir.return_value = pipeline_temp_dir

        # Create a download attempt for the test
        attempt = DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.DOWNLOADING,
        )

        with NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(b"fake_invalid_content")
            temp_path = Path(temp_file.name)
        try:
            with pytest.raises(ValueError, match="not a valid GDS or OASIS"):
                _process_and_save_content(project_file, attempt, temp_path)

            # Verify file was marked as failed
            project_file.refresh_from_db()
            assert project_file.download_status == ProjectFile.DownloadStatus.FAILED
            assert "not a valid GDS or OASIS" in project_file.download_error

            # Pipeline temp dir must be cleaned up even on failure
            assert not pipeline_temp_dir.exists()
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

    @patch("wafer_space.projects.tasks_download.requests.get")
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
            mock_func = "wafer_space.projects.tasks_download._download_github_artifact"
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

    @patch("wafer_space.projects.tasks_download.requests.get")
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
        # Leading bytes must carry an accepted signature (early content check)
        payload = GDS_SIGNATURE + b"t" * (expected_file_size - len(GDS_SIGNATURE))
        mock_response.iter_content = lambda chunk_size: [payload]
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

    @patch("wafer_space.projects.tasks_download.extract_top_cell")
    @patch("wafer_space.projects.tasks_download._apply_content_pipeline")
    @patch("wafer_space.projects.tasks_download.detect_file_type_from_data")
    @patch("wafer_space.projects.tasks_download._download_with_progress")
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

        # Mock the pipeline to extract GDS into the pipeline temp dir
        def fake_pipeline(pf, temp_path, pipeline_temp_dir):
            output_path = pipeline_temp_dir / "design.gds"
            output_path.write_bytes(gds_content)
            return (
                output_path,
                len(gds_content),
                expected_md5,
                expected_sha1,
                expected_sha256,
            )

        mock_pipeline.side_effect = fake_pipeline

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
        """Test ERROR checks create a new retry check when under retry limit."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.ERROR,
        )

        result = checks_retry()

        # Old check stays in ERROR state
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.ERROR

        # New retry check was created
        assert result["retried"] == 1
        retry_check = ManufacturabilityCheck.objects.get(parent_check=check)
        assert retry_check.status == ManufacturabilityCheck.Status.PENDING
        assert retry_check.trigger_reason == ManufacturabilityCheck.TriggerReason.RETRY
        assert retry_check.project == check.project
        assert retry_check.project_file == check.project_file

    def test_does_not_retry_exhausted_checks(self):
        """Test ERROR checks at retry limit are not retried."""
        max_retries = 3
        # Create original check
        original = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,  # Original is done
        )
        # Create retry chain: original -> retry1 -> retry2 -> retry3 (all failed)
        ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,  # Retry 1 done
            trigger_reason=ManufacturabilityCheck.TriggerReason.RETRY,
            parent_check=original,
        )
        ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,  # Retry 2 done
            trigger_reason=ManufacturabilityCheck.TriggerReason.RETRY,
            parent_check=original,
        )
        retry3 = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.ERROR,  # Retry 3 failed (leaf)
            trigger_reason=ManufacturabilityCheck.TriggerReason.RETRY,
            parent_check=original,
        )

        result = checks_retry()

        # No new retry should be created (already at limit of 3)
        retry3.refresh_from_db()
        assert retry3.status == ManufacturabilityCheck.Status.ERROR
        assert result["exhausted"] == 1
        assert original.retry_checks.count() == max_retries  # Still 3, no new ones


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
        assert project_file.manufacturability_checks.count() == 0

        result = checks_create()

        assert result["created"] == 1
        project_file.refresh_from_db()
        assert project_file.manufacturability_checks.count() == 1
        check = project_file.latest_manufacturability_check
        assert check is not None
        assert check.status == ManufacturabilityCheck.Status.PENDING

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
    def test_marks_cancelling_checks_as_cancelled(self) -> None:
        """Directly marks CANCELLING checks as CANCELLED without queuing tasks."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.CANCELLING,
        )

        result = checks_cancelling()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLED
        assert result["cancelled"] == 1

    @pytest.mark.django_db
    def test_handles_multiple_cancelling_checks(self) -> None:
        """Processes multiple CANCELLING checks in one call."""
        check1 = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.CANCELLING,
        )
        check2 = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.CANCELLING,
        )

        result = checks_cancelling()

        check1.refresh_from_db()
        check2.refresh_from_db()
        assert check1.status == ManufacturabilityCheck.Status.CANCELLED
        assert check2.status == ManufacturabilityCheck.Status.CANCELLED
        expected_cancelled = 2
        assert result["cancelled"] == expected_cancelled


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

        mock_path = "wafer_space.projects.tasks_checks.docker.DockerClient"
        with patch(mock_path) as mock_docker_client:
            mock_client = MagicMock()
            mock_docker_client.return_value = mock_client
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

        mock_path = "wafer_space.projects.tasks_checks.docker.DockerClient"
        with patch(mock_path) as mock_docker_client:
            mock_client = MagicMock()
            mock_docker_client.return_value = mock_client
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

        mock_path = "wafer_space.projects.tasks_checks.docker.DockerClient"
        with patch(mock_path) as mock_docker_client:
            result = do_dispatching(check.id)

        # Should not interact with Docker
        mock_docker_client.assert_not_called()
        assert result["status"] == "skipped"
        assert result["reason"] == "status_changed"


class TestDoStarting:
    """Test do_starting work task."""

    @pytest.mark.django_db
    def test_creates_and_starts_container(self, tmp_path, settings) -> None:
        """Creates container with put_archive for remote Docker support."""
        # Configure Docker server for the test
        settings.DOCKER_SERVERS = [
            {
                "id": "test-local",
                "url": "unix:///test.sock",
                "max_concurrent": 4,
                "priority": 1,
            },
        ]

        # Create a test file
        test_file = tmp_path / "design.gds"
        test_file.write_bytes(b"test gds content")

        # Create shuttle to enable full_id on the project
        shuttle = ShuttleFactory(name="G850")

        # Create check with project that has shuttle and project_id set
        # (core fields are immutable after creation)
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.STARTING,
            docker_server_id="test-local",
            docker_image="ghcr.io/test:latest",
            project__shuttle=shuttle,
            project__project_id="ABCD",
        )
        check.project_file.file.name = str(test_file)
        check.project_file.top_cell = "chip_top"
        check.project_file.save()

        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check, task_id="test", task_name="do_starting"
        )

        # Mock get_docker_client (imported from docker_utils)
        mock_docker_path = "wafer_space.projects.tasks_checks.get_docker_client"
        mock_tar_path = "wafer_space.projects.tasks_checks.create_tar_archive"
        with (
            patch(mock_docker_path) as mock_get_docker_client,
            patch(mock_tar_path) as mock_create_tar,
            patch("wafer_space.projects.tasks_checks.Path") as mock_path,
        ):
            mock_client = MagicMock()
            mock_get_docker_client.return_value = mock_client
            mock_container = MagicMock()
            mock_container.id = "container123"
            mock_container.status = "running"
            mock_client.containers.create.return_value = mock_container

            # Mock Path for file existence check
            mock_path_instance = MagicMock()
            mock_path_instance.exists.return_value = True
            mock_path.return_value = mock_path_instance

            # Mock create_tar_archive context manager to yield a mock stream
            mock_tar_stream = MagicMock()
            mock_create_tar.return_value.__enter__.return_value = mock_tar_stream

            result = do_starting(check.id)

        assert result["status"] == "success"
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.RUNNING
        assert check.docker_container_id == "container123"

        # Verify container was created WITHOUT volumes parameter
        create_call = mock_client.containers.create.call_args
        assert "volumes" not in create_call.kwargs

        # Memory policy: hard limit is always 2x the soft limit; memswap ==
        # mem_limit disables swap (PRECHECK_MEM_SOFT_LIMIT_GB = 32 in base.py)
        assert create_call.kwargs["mem_reservation"] == "32g"
        assert create_call.kwargs["mem_limit"] == "64g"
        assert create_call.kwargs["memswap_limit"] == "64g"

        # Verify command includes precheck.py with --slot and --id flags,
        # and outputs OAS instead of GDS (#272)
        assert create_call.kwargs["command"] == [
            "python3",
            "precheck.py",
            "--input",
            "/input/design.gds",
            "--output",
            "/output/design.oas",
            "--top",
            "chip_top",
            "--slot",
            "1x1",
            "--id",
            "G850ABCD",
        ]

        # Verify put_archive was called twice:
        # 1. For the input GDS file (arcname=input/design.gds)
        # 2. For the /output directory
        put_archive_calls = mock_container.put_archive.call_args_list
        assert len(put_archive_calls) == len(["input", "output"])  # 2 calls
        # First call uploads the GDS file
        first_call = put_archive_calls[0]
        assert first_call[0][0] == "/"
        assert first_call[0][1] == mock_tar_stream

        # Verify command is stored correctly
        expected_cmd = (
            "python3 precheck.py --input /input/design.gds "
            "--output /output/design.oas --top chip_top --slot 1x1 --id G850ABCD"
        )
        assert check.docker_command == expected_cmd

    @pytest.mark.django_db
    def test_command_includes_cob_flag_when_requested(self, tmp_path, settings) -> None:
        """--cob is appended after --id when project.chip_on_board is True."""
        settings.DOCKER_SERVERS = [
            {
                "id": "test-local",
                "url": "unix:///test.sock",
                "max_concurrent": 4,
                "priority": 1,
            },
        ]

        test_file = tmp_path / "design.gds"
        test_file.write_bytes(b"test gds content")

        shuttle = ShuttleFactory(name="G850")

        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.STARTING,
            docker_server_id="test-local",
            docker_image="ghcr.io/test:latest",
            project__shuttle=shuttle,
            project__project_id="ABCD",
            project__chip_on_board=True,
        )
        check.project_file.file.name = str(test_file)
        check.project_file.top_cell = "chip_top"
        check.project_file.save()

        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check, task_id="test", task_name="do_starting"
        )

        mock_docker_path = "wafer_space.projects.tasks_checks.get_docker_client"
        mock_tar_path = "wafer_space.projects.tasks_checks.create_tar_archive"
        with (
            patch(mock_docker_path) as mock_get_docker_client,
            patch(mock_tar_path) as mock_create_tar,
            patch("wafer_space.projects.tasks_checks.Path") as mock_path,
        ):
            mock_client = MagicMock()
            mock_get_docker_client.return_value = mock_client
            mock_container = MagicMock()
            mock_container.id = "container123"
            mock_container.status = "running"
            mock_client.containers.create.return_value = mock_container

            mock_path_instance = MagicMock()
            mock_path_instance.exists.return_value = True
            mock_path.return_value = mock_path_instance

            mock_tar_stream = MagicMock()
            mock_create_tar.return_value.__enter__.return_value = mock_tar_stream

            result = do_starting(check.id)

        assert result["status"] == "success"

        create_call = mock_client.containers.create.call_args
        command = create_call.kwargs["command"]
        assert command[-1] == "--cob"
        assert command[:-1] == [
            "python3",
            "precheck.py",
            "--input",
            "/input/design.gds",
            "--output",
            "/output/design.oas",
            "--top",
            "chip_top",
            "--slot",
            "1x1",
            "--id",
            "G850ABCD",
        ]

    @pytest.mark.django_db
    def test_command_includes_workers_and_threads_from_server_config(
        self, tmp_path, settings
    ) -> None:
        """--workers/--threads come from server config, before --cob."""
        settings.DOCKER_SERVERS = [
            {
                "id": "test-local",
                "url": "unix:///test.sock",
                "max_concurrent": 5,
                "priority": 1,
                "check_workers": 6,
                "check_threads": 1,
            },
        ]

        test_file = tmp_path / "design.gds"
        test_file.write_bytes(b"test gds content")

        shuttle = ShuttleFactory(name="G850")

        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.STARTING,
            docker_server_id="test-local",
            docker_image="ghcr.io/test:latest",
            project__shuttle=shuttle,
            project__project_id="ABCD",
            project__chip_on_board=True,
        )
        check.project_file.file.name = str(test_file)
        check.project_file.top_cell = "chip_top"
        check.project_file.save()

        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check, task_id="test", task_name="do_starting"
        )

        mock_docker_path = "wafer_space.projects.tasks_checks.get_docker_client"
        mock_tar_path = "wafer_space.projects.tasks_checks.create_tar_archive"
        with (
            patch(mock_docker_path) as mock_get_docker_client,
            patch(mock_tar_path) as mock_create_tar,
            patch("wafer_space.projects.tasks_checks.Path") as mock_path,
        ):
            mock_client = MagicMock()
            mock_get_docker_client.return_value = mock_client
            mock_container = MagicMock()
            mock_container.id = "container123"
            mock_container.status = "running"
            mock_client.containers.create.return_value = mock_container

            mock_path_instance = MagicMock()
            mock_path_instance.exists.return_value = True
            mock_path.return_value = mock_path_instance

            mock_tar_stream = MagicMock()
            mock_create_tar.return_value.__enter__.return_value = mock_tar_stream

            result = do_starting(check.id)

        assert result["status"] == "success"

        create_call = mock_client.containers.create.call_args
        assert create_call.kwargs["command"] == [
            "python3",
            "precheck.py",
            "--input",
            "/input/design.gds",
            "--output",
            "/output/design.oas",
            "--top",
            "chip_top",
            "--slot",
            "1x1",
            "--id",
            "G850ABCD",
            "--workers",
            "6",
            "--threads",
            "1",
            "--cob",
        ]

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

        mock_docker_path = "wafer_space.projects.tasks_checks.docker.DockerClient"
        mock_tar_path = "wafer_space.projects.tasks_checks.create_tar_archive"
        with (
            patch(mock_docker_path) as mock_docker_client,
            patch(mock_tar_path) as mock_create_tar,
            patch("wafer_space.projects.tasks_checks.Path") as mock_path,
        ):
            mock_client = MagicMock()
            mock_docker_client.return_value = mock_client
            mock_container = MagicMock()
            mock_container.id = "container123"
            mock_container.status = "running"
            mock_client.containers.create.return_value = mock_container
            mock_path_instance = MagicMock()
            mock_path_instance.exists.return_value = True
            mock_path.return_value = mock_path_instance
            mock_create_tar.return_value.__enter__.return_value = MagicMock()

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

        mock_path = "wafer_space.projects.tasks_checks.docker.DockerClient"
        with patch(mock_path) as mock_docker_client:
            result = do_starting(check.id)

        mock_docker_client.assert_not_called()
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
        mock_stats = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 1000000000},
                "system_cpu_usage": 2000000000,
                "online_cpus": 2,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 900000000},
                "system_cpu_usage": 1900000000,
            },
            "memory_stats": {"usage": 1048576, "limit": 4294967296},
            "blkio_stats": {},
            "networks": {},
        }

        mock_path = "wafer_space.projects.tasks_checks.docker.DockerClient"
        with patch(mock_path) as mock_docker_client:
            mock_client = MagicMock()
            mock_docker_client.return_value = mock_client
            mock_container = MagicMock()
            mock_container.id = "container123"
            mock_container.status = "running"
            mock_container.logs.return_value = mock_logs.encode("utf-8")
            mock_container.stats.return_value = mock_stats
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

        mock_stats = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 1000000000},
                "system_cpu_usage": 2000000000,
                "online_cpus": 2,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 900000000},
                "system_cpu_usage": 1900000000,
            },
            "memory_stats": {"usage": 1048576, "limit": 4294967296},
            "blkio_stats": {},
            "networks": {},
        }

        mock_path = "wafer_space.projects.tasks_checks.docker.DockerClient"
        with patch(mock_path) as mock_docker_client:
            mock_client = MagicMock()
            mock_docker_client.return_value = mock_client
            mock_container = MagicMock()
            mock_container.id = "container123"
            mock_container.status = "exited"
            mock_container.attrs = {"State": {"ExitCode": 0}}
            mock_container.logs.return_value = b""
            mock_container.stats.return_value = mock_stats
            mock_client.containers.get.return_value = mock_container

            result = do_running(check.id)

        assert result["status"] == "container_exited"
        assert result["exit_code"] == 0
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.ANALYZING

    @pytest.mark.django_db
    def test_creates_checkpoint_with_stats(self) -> None:
        """Creates ManufacturabilityCheckpoint with container stats."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING,
            docker_server_id="test-local",
            docker_container_id="container123",
        )
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check, task_id="test", task_name="do_running"
        )

        mock_stats = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 1000000000},
                "system_cpu_usage": 2000000000,
                "online_cpus": 2,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 900000000},
                "system_cpu_usage": 1900000000,
            },
            "memory_stats": {"usage": 1048576, "limit": 4294967296},
            "blkio_stats": {
                "io_service_bytes_recursive": [
                    {"op": "read", "value": 1024},
                    {"op": "write", "value": 2048},
                ]
            },
            "networks": {"eth0": {"rx_bytes": 500, "tx_bytes": 300}},
        }

        mock_path = "wafer_space.projects.tasks_checks.docker.DockerClient"
        with patch(mock_path) as mock_docker_client:
            mock_client = MagicMock()
            mock_docker_client.return_value = mock_client
            mock_container = MagicMock()
            mock_container.id = "container123"
            mock_container.status = "running"
            mock_container.logs.return_value = b""
            mock_container.stats.return_value = mock_stats
            mock_client.containers.get.return_value = mock_container

            result = do_running(check.id)

        # Verify checkpoint was created
        assert ManufacturabilityCheckpoint.objects.filter(
            manufacturability_check=check
        ).exists()
        checkpoint = ManufacturabilityCheckpoint.objects.get(
            manufacturability_check=check
        )

        # Verify stats were recorded
        assert checkpoint.checkpoint_number == 0
        assert checkpoint.memory_usage_bytes == TEST_MEMORY_USAGE
        assert checkpoint.memory_limit_bytes == TEST_MEMORY_LIMIT
        assert checkpoint.cpu_online_cpus == TEST_CPU_COUNT
        assert checkpoint.block_read_bytes == TEST_BLOCK_READ
        assert checkpoint.block_write_bytes == TEST_BLOCK_WRITE
        assert checkpoint.network_rx_bytes == TEST_NETWORK_RX
        assert checkpoint.network_tx_bytes == TEST_NETWORK_TX
        assert checkpoint.container_state == "running"

        # Verify result includes checkpoint info
        assert result["checkpoint_number"] == 0

    @pytest.mark.django_db
    def test_checkpoint_stores_raw_stats_json(self) -> None:
        """Stores raw Docker stats JSON for debugging."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING,
            docker_server_id="test-local",
            docker_container_id="container123",
        )
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check, task_id="test", task_name="do_running"
        )

        mock_stats = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 1000000000},
                "system_cpu_usage": 2000000000,
                "online_cpus": 2,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 900000000},
                "system_cpu_usage": 1900000000,
            },
            "memory_stats": {"usage": 1048576, "limit": 4294967296},
            "blkio_stats": {},
            "networks": {},
            "extra_field": "should_be_preserved",
        }

        mock_path = "wafer_space.projects.tasks_checks.docker.DockerClient"
        with patch(mock_path) as mock_docker_client:
            mock_client = MagicMock()
            mock_docker_client.return_value = mock_client
            mock_container = MagicMock()
            mock_container.id = "container123"
            mock_container.status = "running"
            mock_container.logs.return_value = b""
            mock_container.stats.return_value = mock_stats
            mock_client.containers.get.return_value = mock_container

            do_running(check.id)

        checkpoint = ManufacturabilityCheckpoint.objects.get(
            manufacturability_check=check
        )

        # Verify raw stats JSON is stored
        assert checkpoint.raw_stats_json is not None
        assert checkpoint.raw_stats_json["extra_field"] == "should_be_preserved"
        assert checkpoint.raw_stats_json["cpu_stats"]["online_cpus"] == TEST_CPU_COUNT

    @pytest.mark.django_db
    def test_checkpoint_calculates_cpu_percent(self) -> None:
        """Calculates CPU percentage from stats delta."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING,
            docker_server_id="test-local",
            docker_container_id="container123",
        )
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check, task_id="test", task_name="do_running"
        )

        # CPU delta: 100000000 (1000000000 - 900000000)
        # System delta: 100000000 (2000000000 - 1900000000)
        # Expected: (100000000 / 100000000) * 2 * 100 = 200.0%
        mock_stats = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 1000000000},
                "system_cpu_usage": 2000000000,
                "online_cpus": 2,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 900000000},
                "system_cpu_usage": 1900000000,
            },
            "memory_stats": {"usage": 1048576, "limit": 4294967296},
            "blkio_stats": {},
            "networks": {},
        }

        mock_path = "wafer_space.projects.tasks_checks.docker.DockerClient"
        with patch(mock_path) as mock_docker_client:
            mock_client = MagicMock()
            mock_docker_client.return_value = mock_client
            mock_container = MagicMock()
            mock_container.id = "container123"
            mock_container.status = "running"
            mock_container.logs.return_value = b""
            mock_container.stats.return_value = mock_stats
            mock_client.containers.get.return_value = mock_container

            do_running(check.id)

        checkpoint = ManufacturabilityCheckpoint.objects.get(
            manufacturability_check=check
        )

        # CPU percent: (cpu_delta / system_delta) * online_cpus * 100 = 200%
        assert checkpoint.cpu_percent is not None
        assert abs(checkpoint.cpu_percent - 200.0) < TEST_CPU_PERCENT_TOLERANCE

    @pytest.mark.django_db
    def test_checkpoint_increments_checkpoint_number(self) -> None:
        """Checkpoint number increments on each poll."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING,
            docker_server_id="test-local",
            docker_container_id="container123",
        )

        # Pre-create a checkpoint to verify incrementing
        ManufacturabilityCheckpoint.objects.create(
            manufacturability_check=check,
            checkpoint_number=0,
            container_state="running",
            elapsed_seconds=0.0,
        )

        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check, task_id="test", task_name="do_running"
        )

        mock_stats = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 1000000000},
                "system_cpu_usage": 2000000000,
                "online_cpus": 2,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 900000000},
                "system_cpu_usage": 1900000000,
            },
            "memory_stats": {"usage": 1048576, "limit": 4294967296},
            "blkio_stats": {},
            "networks": {},
        }

        mock_path = "wafer_space.projects.tasks_checks.docker.DockerClient"
        with patch(mock_path) as mock_docker_client:
            mock_client = MagicMock()
            mock_docker_client.return_value = mock_client
            mock_container = MagicMock()
            mock_container.id = "container123"
            mock_container.status = "running"
            mock_container.logs.return_value = b""
            mock_container.stats.return_value = mock_stats
            mock_client.containers.get.return_value = mock_container

            result = do_running(check.id)

        # Should now have 2 checkpoints (0 and 1)
        checkpoints = ManufacturabilityCheckpoint.objects.filter(
            manufacturability_check=check
        ).order_by("checkpoint_number")
        assert checkpoints.count() == TEST_CHECKPOINT_COUNT
        assert checkpoints[0].checkpoint_number == 0
        assert checkpoints[1].checkpoint_number == 1
        assert result["checkpoint_number"] == 1

    @pytest.mark.django_db
    def test_checkpoint_handles_stats_failure_gracefully(self) -> None:
        """Continues if container.stats() fails."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING,
            docker_server_id="test-local",
            docker_container_id="container123",
        )
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check, task_id="test", task_name="do_running"
        )

        mock_path = "wafer_space.projects.tasks_checks.docker.DockerClient"
        with patch(mock_path) as mock_docker_client:
            mock_client = MagicMock()
            mock_docker_client.return_value = mock_client
            mock_container = MagicMock()
            mock_container.id = "container123"
            mock_container.status = "running"
            mock_container.logs.return_value = b"Log output\n"
            # Stats call raises exception
            mock_container.stats.side_effect = docker.errors.DockerException(
                "Stats unavailable"
            )
            mock_client.containers.get.return_value = mock_container

            # Should not raise - should handle gracefully
            result = do_running(check.id)

        # Task should still complete successfully
        assert result["status"] == "still_running"

        # No checkpoint should be created
        assert not ManufacturabilityCheckpoint.objects.filter(
            manufacturability_check=check
        ).exists()

        # checkpoint_number should not be in result
        assert "checkpoint_number" not in result

    @pytest.mark.django_db
    def test_skips_if_status_changed(self) -> None:
        """Does nothing if status is no longer RUNNING."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.CANCELLED,
        )

        mock_path = "wafer_space.projects.tasks_checks.docker.DockerClient"
        with patch(mock_path) as mock_docker_client:
            result = do_running(check.id)

        mock_docker_client.assert_not_called()
        assert result["status"] == "skipped"


class TestDoAnalyzing:
    """Test do_analyzing work task."""

    @pytest.mark.django_db
    def test_parses_logs_and_transitions_to_finished(self) -> None:
        """Parses logs successfully and transitions to FINISHED."""
        # Success requires all three: DRC clear messages + success message
        success_logs = """Check for Magic DRC errors clear.
Check for KLayout DRC errors clear.
Precheck successfully completed."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.ANALYZING,
            docker_exit_code=0,
            processing_logs=success_logs,
            docker_server_id="test-local",
            docker_container_id="test-container-id",
        )
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check, task_id="test", task_name="do_analyzing"
        )

        # Mock container that has no outputs
        mock_container = MagicMock()
        mock_container.status = "exited"
        mock_container.get_archive.side_effect = docker.errors.NotFound("no archive")
        mock_client = MagicMock()
        mock_client.containers.get.return_value = mock_container

        with patch(
            "wafer_space.projects.tasks_checks.get_docker_client",
            return_value=mock_client,
        ):
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
            docker_server_id="test-local",
            docker_container_id="test-container-id",
        )
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check, task_id="test", task_name="do_analyzing"
        )

        # Mock container that has no outputs
        mock_container = MagicMock()
        mock_container.status = "exited"
        mock_container.get_archive.side_effect = docker.errors.NotFound("no archive")
        mock_client = MagicMock()
        mock_client.containers.get.return_value = mock_container

        with patch(
            "wafer_space.projects.tasks_checks.get_docker_client",
            return_value=mock_client,
        ):
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

    @pytest.mark.django_db
    def test_saves_log_file_with_checksum(self) -> None:
        """Saves processing logs to log_file with SHA256 checksum."""
        # Success requires all evidence: DRC clear messages + success message
        success_logs = """Check for Magic DRC errors clear.
Check for KLayout DRC errors clear.
Precheck successfully completed."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.ANALYZING,
            docker_exit_code=0,
            processing_logs=success_logs,
            docker_server_id="test-local",
            docker_container_id="test-container-id",
        )
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check, task_id="test", task_name="do_analyzing"
        )

        # Mock container that has no outputs
        mock_container = MagicMock()
        mock_container.status = "exited"
        mock_container.get_archive.side_effect = docker.errors.NotFound("no archive")
        mock_client = MagicMock()
        mock_client.containers.get.return_value = mock_container

        with patch(
            "wafer_space.projects.tasks_checks.get_docker_client",
            return_value=mock_client,
        ):
            result = do_analyzing(check.id)

        assert result["status"] == "success"
        check.refresh_from_db()
        assert bool(check.log_file)
        assert check.log_file_sha256 != ""
        # Verify checksum matches content
        content = check.log_file.read()
        expected_sha256 = hashlib.sha256(content).hexdigest()
        assert check.log_file_sha256 == expected_sha256

    @pytest.mark.django_db
    def test_returns_outputs_saved_in_result(self) -> None:
        """Returns outputs_saved dict showing which outputs were saved."""
        # Success requires all evidence: DRC clear messages + success message
        success_logs = """Check for Magic DRC errors clear.
Check for KLayout DRC errors clear.
Precheck successfully completed."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.ANALYZING,
            docker_exit_code=0,
            processing_logs=success_logs,
            docker_server_id="test-local",
            docker_container_id="test-container-id",
        )
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check, task_id="test", task_name="do_analyzing"
        )

        # Mock container that has no outputs
        mock_container = MagicMock()
        mock_container.status = "exited"
        mock_container.get_archive.side_effect = docker.errors.NotFound("no archive")
        mock_client = MagicMock()
        mock_client.containers.get.return_value = mock_container

        with patch(
            "wafer_space.projects.tasks_checks.get_docker_client",
            return_value=mock_client,
        ):
            result = do_analyzing(check.id)

        assert "outputs_saved" in result
        assert "log_file" in result["outputs_saved"]
        # Container exists but has no extractable outputs
        assert result["outputs_saved"]["log_file"] is True
        assert result["outputs_saved"]["runs_archive"] is False
        assert result["outputs_saved"]["output_gds"] is False
        assert result["outputs_saved"]["docker_layer_export"] is False

    @pytest.mark.django_db
    def test_save_output_extracts_oas_layout(self) -> None:
        """Output layout is extracted from /output/design.oas and saved as .oas.

        Issue #272: precheck now writes the processed layout as OASIS (.oas)
        instead of GDS to save disk space.
        """
        oas_content = b"fake-oasis-layout-bytes"

        # Build the tar archive that container.get_archive() would return,
        # containing the OAS layout produced by precheck.
        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
            info = tarfile.TarInfo(name="design.oas")
            info.size = len(oas_content)
            tar.addfile(info, io.BytesIO(oas_content))
        tar_bytes = tar_buffer.getvalue()

        mock_container = MagicMock()
        mock_container.get_archive.return_value = (iter([tar_bytes]), {})

        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.ANALYZING,
            docker_server_id="test-local",
        )

        _save_output_gds(check, mock_container, logging.getLogger("test"))

        # Layout is requested from the OAS path inside the container
        mock_container.get_archive.assert_called_once_with("/output/design.oas")

        check.refresh_from_db()
        assert check.output_gds.name.endswith(".oas")
        with check.output_gds.open("rb") as f:
            assert f.read() == oas_content
        assert check.output_gds_sha256 == hashlib.sha256(oas_content).hexdigest()

    @pytest.mark.django_db
    def test_save_output_skips_non_file_members(self) -> None:
        """Directory members ending in .oas must not shadow the layout file.

        Issue #275: tar.extractfile() returns None for directories, so a
        directory entry matching *.oas used to hit the break and silently
        drop the real layout file behind it.
        """
        oas_content = b"real-oasis-layout-bytes"

        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
            dir_info = tarfile.TarInfo(name="design.oas")
            dir_info.type = tarfile.DIRTYPE
            tar.addfile(dir_info)
            info = tarfile.TarInfo(name="design.oas/design.oas")
            info.size = len(oas_content)
            tar.addfile(info, io.BytesIO(oas_content))
        tar_bytes = tar_buffer.getvalue()

        mock_container = MagicMock()
        mock_container.get_archive.return_value = (iter([tar_bytes]), {})

        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.ANALYZING,
            docker_server_id="test-local",
        )

        _save_output_gds(check, mock_container, logging.getLogger("test"))

        check.refresh_from_db()
        assert bool(check.output_gds), "layout file was not saved"
        with check.output_gds.open("rb") as f:
            assert f.read() == oas_content

    @pytest.mark.django_db
    def test_save_output_extracts_first_of_multiple_oas_members(self) -> None:
        """The first regular .oas member wins when several are present.

        The archive from container.get_archive("/output/design.oas")
        should only ever hold one layout, but if several .oas members
        are present the first one is saved and the rest are ignored.
        """
        first_content = b"first-oasis-layout"
        second_content = b"second-oasis-layout"

        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
            for name, content in [
                ("design.oas", first_content),
                ("design_backup.oas", second_content),
            ]:
                info = tarfile.TarInfo(name=name)
                info.size = len(content)
                tar.addfile(info, io.BytesIO(content))
        tar_bytes = tar_buffer.getvalue()

        mock_container = MagicMock()
        mock_container.get_archive.return_value = (iter([tar_bytes]), {})

        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.ANALYZING,
            docker_server_id="test-local",
        )

        _save_output_gds(check, mock_container, logging.getLogger("test"))

        check.refresh_from_db()
        assert bool(check.output_gds), "layout file was not saved"
        with check.output_gds.open("rb") as f:
            assert f.read() == first_content

    @pytest.mark.django_db
    def test_save_output_ignores_non_oas_members(self) -> None:
        """Non-.oas members must be skipped, even when they come first.

        Log files or GDS artifacts sharing the archive must never be
        saved as the output layout; only the .oas member is extracted.
        """
        oas_content = b"the-oasis-layout"

        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
            for name, content in [
                ("report.txt", b"precheck report text"),
                ("design.gds", b"legacy-gds-layout"),
                ("design.oas", oas_content),
            ]:
                info = tarfile.TarInfo(name=name)
                info.size = len(content)
                tar.addfile(info, io.BytesIO(content))
        tar_bytes = tar_buffer.getvalue()

        mock_container = MagicMock()
        mock_container.get_archive.return_value = (iter([tar_bytes]), {})

        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.ANALYZING,
            docker_server_id="test-local",
        )

        _save_output_gds(check, mock_container, logging.getLogger("test"))

        check.refresh_from_db()
        assert bool(check.output_gds), "layout file was not saved"
        with check.output_gds.open("rb") as f:
            assert f.read() == oas_content

    @pytest.mark.django_db
    def test_save_output_streams_layout_in_chunks(self) -> None:
        """The extracted layout is streamed to disk in bounded chunks.

        Issue #275: reading the whole extracted member into memory via
        read() can spike worker RAM on large layouts. Every read of the
        extracted member must be bounded, and a layout larger than the
        chunk size must survive extraction byte-for-byte.
        """
        chunk_limit = 4 * 1024 * 1024
        # 2.5 MiB layout: forces several 1 MiB chunks during extraction.
        oas_content = bytes(range(256)) * (10 * 1024)
        read_sizes: list[int] = []

        class ReadSizeRecorder:
            """Records the size argument of every read() call."""

            def __init__(self, inner: IO[bytes]) -> None:
                self._inner = inner

            def read(self, size: int = -1) -> bytes:
                read_sizes.append(size)
                return self._inner.read(size)

            def close(self) -> None:
                self._inner.close()

            def __enter__(self) -> "ReadSizeRecorder":
                return self

            def __exit__(self, *exc_info: object) -> None:
                self._inner.close()

        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
            info = tarfile.TarInfo(name="design.oas")
            info.size = len(oas_content)
            tar.addfile(info, io.BytesIO(oas_content))
        tar_bytes = tar_buffer.getvalue()

        mock_container = MagicMock()
        mock_container.get_archive.return_value = (iter([tar_bytes]), {})

        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.ANALYZING,
            docker_server_id="test-local",
        )

        real_extractfile = tarfile.TarFile.extractfile

        def recording_extractfile(
            tar: tarfile.TarFile, member: tarfile.TarInfo
        ) -> ReadSizeRecorder | None:
            inner = real_extractfile(tar, member)
            if inner is None:
                return None
            return ReadSizeRecorder(inner)

        with patch.object(tarfile.TarFile, "extractfile", recording_extractfile):
            _save_output_gds(check, mock_container, logging.getLogger("test"))

        check.refresh_from_db()
        with check.output_gds.open("rb") as f:
            assert f.read() == oas_content
        assert read_sizes, "extracted layout was never read"
        for size in read_sizes:
            assert 0 < size <= chunk_limit, f"unbounded read (size={size})"

    @pytest.mark.django_db
    def test_errors_when_container_not_found(self) -> None:
        """Returns error when container has been deleted/cleaned up.

        When the container has been removed before analyzing completes,
        the task returns an error result. A missing container during
        analysis is an error condition, not something to gracefully handle.
        """
        # Mock docker client to raise NotFound when getting container
        mock_client = MagicMock()
        mock_client.containers.get.side_effect = docker.errors.NotFound(
            "container gone"
        )

        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.ANALYZING,
            docker_exit_code=0,
            processing_logs="Precheck successfully completed.",
            docker_server_id="test-local",
            docker_container_id="nonexistent-container-id",
        )
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check, task_id="test", task_name="do_analyzing"
        )

        with patch(
            "wafer_space.projects.tasks_checks.get_docker_client",
            return_value=mock_client,
        ):
            result = do_analyzing(check.id)

        assert result["status"] == "error"
        assert "container_not_found" in result.get("reason", "")

    @pytest.mark.django_db
    def test_errors_when_container_info_missing(self) -> None:
        """Returns error when container info is not set on the check.

        If a check reaches ANALYZING state without docker_server_id or
        docker_container_id, that's an error - the container should exist.
        """
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.ANALYZING,
            docker_exit_code=0,
            processing_logs="Precheck successfully completed.",
            docker_server_id="",
            docker_container_id="",
        )
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check, task_id="test", task_name="do_analyzing"
        )

        result = do_analyzing(check.id)

        assert result["status"] == "error"
        assert "missing_container_info" in result.get("reason", "")


class TestChecksCleanupStalePendingTasks:
    """Tests for checks_cleanup_stale_pending_tasks task."""

    @pytest.mark.django_db
    @patch(
        "wafer_space.projects.tasks_checks.is_check_task_actively_running",
        return_value=False,
    )
    def test_deletes_orphaned_tasks_not_in_queue_or_results(
        self, mock_is_active: Mock
    ) -> None:
        """Deletes ManufacturabilityCheckTask records when task is orphaned.

        A task is orphaned if it's not in the broker queue AND not in
        TaskResult with an unfinished status.
        """
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.ANALYZING,
        )
        task = ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check,
            task_id="orphaned-task-id",
            task_name="do_analyzing",
        )

        # Set queued_at to 1 minute ago (older than 30 second threshold)
        task.queued_at = timezone.now() - timedelta(minutes=1)
        task.save(update_fields=["queued_at"])

        result = checks_cleanup_stale_pending_tasks()

        assert result["deleted"] == 1
        assert result["still_active"] == 0
        assert not ManufacturabilityCheckTask.objects.filter(id=task.id).exists()
        mock_is_active.assert_called_once_with("orphaned-task-id")

    @pytest.mark.django_db
    @patch(
        "wafer_space.projects.tasks_checks.is_check_task_actively_running",
        return_value=True,
    )
    def test_keeps_tasks_still_in_queue(self, mock_is_active: Mock) -> None:
        """Does not delete tasks that are still in the broker queue."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.ANALYZING,
        )
        task = ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check,
            task_id="queued-task-id",
            task_name="do_analyzing",
        )

        # Set queued_at to 1 minute ago (older than 30 second threshold)
        task.queued_at = timezone.now() - timedelta(minutes=1)
        task.save(update_fields=["queued_at"])

        result = checks_cleanup_stale_pending_tasks()

        assert result["deleted"] == 0
        assert result["still_active"] == 1
        assert ManufacturabilityCheckTask.objects.filter(id=task.id).exists()
        mock_is_active.assert_called_once_with("queued-task-id")

    @pytest.mark.django_db
    @patch(
        "wafer_space.projects.tasks_checks.is_check_task_actively_running",
        return_value=False,
    )
    def test_keeps_very_recent_tasks_without_checking(
        self, mock_is_active: Mock
    ) -> None:
        """Does not check tasks queued within last 30 seconds.

        Very recent tasks might still be in transit between queue and worker,
        so we skip checking them to avoid false positives.
        """
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.ANALYZING,
        )
        task = ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check,
            task_id="fresh-task-id",
            task_name="do_analyzing",
        )

        # Set queued_at to 10 seconds ago - under the 30 second threshold
        task.queued_at = timezone.now() - timedelta(seconds=10)
        task.save(update_fields=["queued_at"])

        result = checks_cleanup_stale_pending_tasks()

        # Task should be kept because it's too recent to check
        assert result["deleted"] == 0
        assert result["still_active"] == 0
        assert ManufacturabilityCheckTask.objects.filter(id=task.id).exists()
        # Verify the mock was never called
        mock_is_active.assert_not_called()

    @pytest.mark.django_db
    def test_returns_zero_when_no_pending_tasks(self) -> None:
        """Returns zero when no pending tasks exist."""
        result = checks_cleanup_stale_pending_tasks()

        assert result["deleted"] == 0
        assert result["still_active"] == 0


class TestCancelSupersededChecks:
    """Tests for cancel_superseded_checks functionality."""

    @pytest.mark.django_db
    def test_cancels_older_in_progress_check_when_newer_exists(self) -> None:
        """Older in-progress check is cancelled when newer check exists."""
        project_file = ProjectFileFactory()
        old_check = ManufacturabilityCheckFactory(
            project=project_file.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
        )
        ManufacturabilityCheckFactory(
            project=project_file.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        checks_cleanup()

        old_check.refresh_from_db()
        assert old_check.status == ManufacturabilityCheck.Status.CANCELLING

    @pytest.mark.django_db
    def test_does_not_cancel_if_no_newer_check(self) -> None:
        """In-progress check is not cancelled if no newer check exists."""
        project_file = ProjectFileFactory()
        check = ManufacturabilityCheckFactory(
            project=project_file.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
        )

        checks_cleanup()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.RUNNING

    @pytest.mark.django_db
    def test_does_not_cancel_finished_checks(self) -> None:
        """Finished checks are not cancelled even if newer exists."""
        project_file = ProjectFileFactory()
        old_check = ManufacturabilityCheckFactory(
            project=project_file.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
        )
        ManufacturabilityCheckFactory(
            project=project_file.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        checks_cleanup()

        old_check.refresh_from_db()
        assert old_check.status == ManufacturabilityCheck.Status.FINISHED


@pytest.mark.django_db
class TestChecksDrcUpdateRequeue:
    """Tests for checks_drc_update_requeue task."""

    def setup_method(self):
        """Clear cache and set up test data."""
        cache.clear()
        self.project = ProjectFactory()
        self.project_file = ProjectFileFactory(project=self.project, is_active=True)

    def test_skips_when_no_latest_digest(self):
        """Task returns early when no checks exist to determine latest digest."""
        result = checks_drc_update_requeue()
        assert result == {"skipped": "no_latest_digest"}

    def test_creates_check_for_outdated_finished_check(self):
        """Task creates new check when latest check is FINISHED with outdated digest."""
        # Create finished check with old digest
        old_check = ManufacturabilityCheckFactory(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:old123456789012345678901234567890123456789012345678901234567",
            container_started_at=timezone.now() - timedelta(hours=2),
        )
        # Create different project with newer digest (establishes latest)
        other_project = ProjectFactory()
        other_file = ProjectFileFactory(project=other_project)
        ManufacturabilityCheckFactory(
            project=other_project,
            project_file=other_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:new456789012345678901234567890123456789012345678901234567890",
            container_started_at=timezone.now(),
        )
        cache.clear()

        result = checks_drc_update_requeue()

        assert result["created"] == 1
        assert result["outdated_count"] == 1

        # Verify new check was created
        new_check = ManufacturabilityCheck.objects.filter(
            project_file=self.project_file,
            trigger_reason=ManufacturabilityCheck.TriggerReason.DRC_UPDATE,
        ).first()
        assert new_check is not None
        assert new_check.parent_check == old_check

    def test_skips_in_progress_checks(self):
        """Task only considers FINISHED checks for automatic requeue."""
        # Create running check with old digest
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
            docker_image_digest="sha256:old123456789012345678901234567890123456789012345678901234567",
            container_started_at=timezone.now() - timedelta(hours=2),
        )
        # Establish latest digest
        other_file = ProjectFileFactory()
        ManufacturabilityCheckFactory(
            project_file=other_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:new456789012345678901234567890123456789012345678901234567890",
            container_started_at=timezone.now(),
        )
        cache.clear()

        result = checks_drc_update_requeue()

        assert result["created"] == 0
        assert result["stats"]["in_progress"] == 1

    def test_skips_current_version_checks(self):
        """Task skips checks already using latest version."""
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:latest123456789012345678901234567890123456789012345678901234",
            container_started_at=timezone.now(),
        )
        cache.clear()

        result = checks_drc_update_requeue()

        assert result["created"] == 0
        assert result["outdated_count"] == 0

    def test_creates_only_one_per_run(self):
        """Task creates at most one check per run."""
        # Create two projects with outdated checks
        for i in range(TEST_OUTDATED_CHECKS_COUNT):
            proj = ProjectFactory()
            pf = ProjectFileFactory(project=proj, is_active=True)
            ManufacturabilityCheckFactory(
                project=proj,
                project_file=pf,
                status=ManufacturabilityCheck.Status.FINISHED,
                docker_image_digest=f"sha256:old{i}23456789012345678901234567890123456789012345678901234567",
                container_started_at=timezone.now() - timedelta(hours=i + 1),
            )
        # Establish latest digest
        ManufacturabilityCheckFactory(
            docker_image_digest="sha256:new456789012345678901234567890123456789012345678901234567890",
            container_started_at=timezone.now(),
        )
        cache.clear()

        result = checks_drc_update_requeue()

        assert result["created"] == 1
        assert result["outdated_count"] == TEST_OUTDATED_CHECKS_COUNT

    def test_orders_by_oldest_first(self):
        """Task processes oldest outdated checks first."""
        # Create older check
        old_proj = ProjectFactory()
        old_file = ProjectFileFactory(project=old_proj, is_active=True)
        old_check = ManufacturabilityCheckFactory(
            project=old_proj,
            project_file=old_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:old123456789012345678901234567890123456789012345678901234567",
            container_started_at=timezone.now() - timedelta(hours=10),
        )
        # Force creation time to be older
        ManufacturabilityCheck.objects.filter(pk=old_check.pk).update(
            created_at=timezone.now() - timedelta(hours=10)
        )
        old_check.refresh_from_db()

        # Create newer check
        new_proj = ProjectFactory()
        new_file = ProjectFileFactory(project=new_proj, is_active=True)
        ManufacturabilityCheckFactory(
            project=new_proj,
            project_file=new_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:old223456789012345678901234567890123456789012345678901234567",
            container_started_at=timezone.now() - timedelta(hours=5),
        )
        # Establish latest digest
        ManufacturabilityCheckFactory(
            docker_image_digest="sha256:new456789012345678901234567890123456789012345678901234567890",
            container_started_at=timezone.now(),
        )
        cache.clear()

        checks_drc_update_requeue()

        # Should have created check for older project
        new_check = ManufacturabilityCheck.objects.filter(
            trigger_reason=ManufacturabilityCheck.TriggerReason.DRC_UPDATE,
        ).first()
        assert new_check is not None
        assert new_check.parent_check == old_check

    def test_respects_capacity_limit(self):
        """Task respects 25% DRC_UPDATE capacity limit."""
        # Create outdated check
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:old123456789012345678901234567890123456789012345678901234567",
            container_started_at=timezone.now() - timedelta(hours=2),
        )
        # Establish latest digest
        ManufacturabilityCheckFactory(
            docker_image_digest="sha256:new456789012345678901234567890123456789012345678901234567890",
            container_started_at=timezone.now(),
        )
        cache.clear()

        result = checks_drc_update_requeue()

        # Verify capacity fields are present in result
        assert "drc_update_limit" in result
        assert "drc_update_active" in result
        assert "drc_update_available" in result

    def test_returns_stats(self):
        """Task returns comprehensive stats dictionary."""
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:latest123456789012345678901234567890123456789012345678901234",
            container_started_at=timezone.now(),
        )
        cache.clear()

        result = checks_drc_update_requeue()

        assert "stats" in result
        assert "total" in result["stats"]
        assert "finished" in result["stats"]
        assert "in_progress" in result["stats"]
        assert "error" in result["stats"]
        assert "drc_update_limit" in result
        assert "drc_update_active" in result
        assert "drc_update_available" in result
        assert "outdated_count" in result
        assert "created" in result

    def test_only_considers_latest_project_file_per_project(self):
        """Task only looks at the latest project_file per project, not all files.

        If a project has multiple files, only the latest file's latest check
        is considered. Outdated checks on older files are ignored.
        """
        # Use setup's project_file as older file with outdated check
        old_file = self.project_file
        old_file.is_active = False
        old_file.save()
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=old_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:old123456789012345678901234567890123456789012345678901234567",
            container_started_at=timezone.now() - timedelta(hours=2),
        )

        # Create newer project_file (higher ID) with current version check
        new_file = ProjectFileFactory(project=self.project, is_active=True)
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=new_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:new456789012345678901234567890123456789012345678901234567890",
            container_started_at=timezone.now(),
        )
        cache.clear()

        result = checks_drc_update_requeue()

        # Should NOT requeue because the latest file's check is current
        assert result["created"] == 0
        assert result["outdated_count"] == 0
        # Should only see 1 project (the latest file's check), not 2
        assert result["stats"]["total"] == 1

    def test_one_check_per_project_not_per_file(self):
        """Task returns exactly one check per project, not per project_file.

        Even if a project has multiple files each with checks, only the
        latest check on the latest file is considered.
        """
        # Deactivate setup's project_file so we can create multiple
        self.project_file.is_active = False
        self.project_file.save()

        # Create 3 files - "latest" is determined by ID, not is_active
        files = [
            ProjectFileFactory(project=self.project, is_active=False),
            ProjectFileFactory(project=self.project, is_active=True),  # Not latest
            ProjectFileFactory(project=self.project, is_active=False),  # Latest
        ]

        # Add checks to each file (with older digests)
        for i, pf in enumerate(files):
            for j in range(2):
                ManufacturabilityCheckFactory(
                    project=self.project,
                    project_file=pf,
                    status=ManufacturabilityCheck.Status.FINISHED,
                    docker_image_digest=f"sha256:old{i}{j}3456789012345678901234567890123456789012345678901234567",
                    container_started_at=timezone.now() - timedelta(hours=10 - i - j),
                )

        # Establish latest digest via different project
        other_project = ProjectFactory()
        other_file = ProjectFileFactory(project=other_project)
        ManufacturabilityCheckFactory(
            project=other_project,
            project_file=other_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:latest123456789012345678901234567890123456789012345678901234",
            container_started_at=timezone.now(),
        )
        cache.clear()

        result = checks_drc_update_requeue()

        # Should see exactly 2 projects total (self.project + other_project)
        # NOT 3 files * 2 checks = 6, and NOT 1 + 3 = 4
        assert result["stats"]["total"] == TEST_PROJECT_COUNT_WITH_REFERENCE
        # Only self.project's latest file's latest check is outdated
        assert result["outdated_count"] == 1


class TestDownloadStreaming:
    """Memory-usage contracts for the download pipeline.

    Large downloads must be processed in bounded chunks, never read
    fully into worker RAM (same class of issue as #275).
    """

    CHUNK_LIMIT = 4 * 1024 * 1024

    def test_resume_hash_seeding_reads_partial_file_in_chunks(
        self, tmp_path: Path
    ) -> None:
        """Seeding hashers from a partial download must use bounded reads.

        When a download resumes, the existing partial file is hashed
        before new chunks arrive. A 2.5 MiB partial file must be read
        in bounded chunks and still produce the correct digests.
        """
        partial_content = bytes(range(256)) * (10 * 1024)  # 2.5 MiB
        partial_file = tmp_path / "partial.download"
        partial_file.write_bytes(partial_content)

        read_sizes: list[int] = []
        recording_path = RecordingPath(partial_file)
        recording_path.read_sizes = read_sizes

        md5_hasher, sha1_hasher, sha256_hasher = _initialize_hash_calculators(
            recording_path, len(partial_content)
        )

        expected_md5 = hashlib.md5(partial_content, usedforsecurity=False).hexdigest()
        expected_sha1 = hashlib.sha1(partial_content, usedforsecurity=False).hexdigest()
        assert md5_hasher.hexdigest() == expected_md5
        assert sha1_hasher.hexdigest() == expected_sha1
        assert sha256_hasher.hexdigest() == hashlib.sha256(partial_content).hexdigest()
        assert read_sizes, "partial file was never read"
        for size in read_sizes:
            assert 0 < size <= self.CHUNK_LIMIT, f"unbounded read (size={size})"

    @pytest.mark.django_db
    def test_process_and_save_content_processes_archive_from_disk(
        self, tmp_path: Path
    ) -> None:
        """Content processing works file-to-file from the downloaded archive.

        The downloaded archive stays on disk: the pipeline extracts it
        file-to-file and the result is saved to storage from disk. A
        2.5 MiB GDS inside a ZIP must survive with correct content,
        hashes, size, and processed filename.
        """
        gds_content = b"\x00\x06\x00\x02" + bytes(range(256)) * (10 * 1024)
        archive_path = tmp_path / "design.zip"
        with zipfile.ZipFile(archive_path, "w") as zf:
            zf.writestr("design.gds", gds_content)

        project_file = ProjectFileFactory(
            original_filename="design.zip",
            source_url="https://example.com/design.zip",
        )
        attempt = DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.DOWNLOADING,
        )

        final_md5, final_sha1, final_sha256 = _process_and_save_content(
            project_file, attempt, archive_path
        )

        assert final_md5 == hashlib.md5(gds_content, usedforsecurity=False).hexdigest()
        assert (
            final_sha1 == hashlib.sha1(gds_content, usedforsecurity=False).hexdigest()
        )
        assert final_sha256 == hashlib.sha256(gds_content).hexdigest()

        project_file.refresh_from_db()
        assert project_file.processed_filename == "design.gds"
        assert project_file.file_size == len(gds_content)
        assert project_file.hash_sha256 == final_sha256
        with project_file.file.open("rb") as f:
            assert f.read() == gds_content

    @pytest.mark.django_db
    def test_cleanup_failure_does_not_mask_successful_save(
        self, tmp_path: Path
    ) -> None:
        """A pipeline temp dir cleanup error must not fail a good save.

        cleanup_temp_dir runs in a finally block after the extracted
        file is saved; if rmtree fails, the download must still
        complete and persist its hashes.
        """
        gds_content = b"\x00\x06\x00\x02" + bytes(range(256)) * 1024
        archive_path = tmp_path / "design.zip"
        with zipfile.ZipFile(archive_path, "w") as zf:
            zf.writestr("design.gds", gds_content)

        project_file = ProjectFileFactory(
            original_filename="design.zip",
            source_url="https://example.com/design.zip",
        )
        attempt = DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.DOWNLOADING,
        )

        with patch(
            "wafer_space.projects.tasks_download.cleanup_temp_dir",
            side_effect=OSError("disk error during rmtree"),
        ):
            _, _, final_sha256 = _process_and_save_content(
                project_file, attempt, archive_path
            )

        assert final_sha256 == hashlib.sha256(gds_content).hexdigest()
        project_file.refresh_from_db()
        assert project_file.hash_sha256 == final_sha256
        with project_file.file.open("rb") as f:
            assert f.read() == gds_content

    @pytest.mark.django_db
    def test_post_download_processing_decodes_google_source_in_place(
        self, tmp_path: Path
    ) -> None:
        """GoogleSource base64 payloads are decoded on disk, in place."""
        content = b"\x00\x06\x00\x02layout-bytes"
        encoded_file = tmp_path / "download.b64"
        encoded_file.write_bytes(base64.b64encode(content))

        project_file = ProjectFileFactory(
            handler_metadata={
                "handler": "GoogleSourceHandler",
                "base64_encoded": True,
            }
        )

        _apply_post_download_processing(project_file, encoded_file)

        assert encoded_file.read_bytes() == content

    @pytest.mark.django_db
    def test_download_task_reads_bounded_chunks_only(self, tmp_path: Path) -> None:
        """download_project_file must never read the artifact unbounded.

        Once the download lands on disk, type detection needs only the
        first 1 MiB and all further processing is file-based, so every
        read of the temp file must be bounded even for an artifact
        larger than the chunk size.
        """
        gds_content = b"\x00\x06\x00\x02" + bytes(range(256)) * (10 * 1024)
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("design.gds", gds_content)
        zip_bytes = zip_buffer.getvalue()

        project = ProjectFactory()
        project_file = ProjectFile.objects.create(
            project=project,
            source_url="https://example.com/design.zip",
            original_filename="design.zip",
            is_active=True,
        )

        read_sizes: list[int] = []
        recording_path = RecordingPath(tmp_path / "design.zip")
        recording_path.read_sizes = read_sizes

        def write_zip(
            task: object,
            pf: ProjectFile,
            attempt: DownloadAttempt,
            temp_path: Path,
        ) -> tuple[str, str, str]:
            temp_path.write_bytes(zip_bytes)
            return ("zip-md5", "zip-sha1", "zip-sha256")

        with (
            patch(
                "wafer_space.projects.tasks_download._setup_download_temp_path",
                return_value=recording_path,
            ),
            patch(
                "wafer_space.projects.tasks_download._download_with_progress",
                side_effect=write_zip,
            ),
            patch(
                "wafer_space.projects.tasks_download.detect_file_type_from_data",
                return_value=("application/zip", ".zip"),
            ),
            patch(
                "wafer_space.projects.tasks_download.extract_top_cell",
                return_value="TOP",
            ),
        ):
            result = download_project_file(str(project.id))

        assert result["status"] == "completed"
        project_file.refresh_from_db()
        assert project_file.hash_sha256 == hashlib.sha256(gds_content).hexdigest()
        with project_file.file.open("rb") as f:
            assert f.read() == gds_content
        assert read_sizes, "temp file was never read"
        for size in read_sizes:
            assert 0 < size <= self.CHUNK_LIMIT, f"unbounded read (size={size})"
