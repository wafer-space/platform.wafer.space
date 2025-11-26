"""Tests for services layer."""

from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.test import TestCase

from wafer_space.projects.models import DownloadAttempt
from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.projects.security import SecurityValidationError
from wafer_space.projects.services import ManufacturabilityService
from wafer_space.projects.services import ProjectFileService
from wafer_space.projects.services import detect_file_type_from_data
from wafer_space.users.models import User

from .constants import FIVE_MB
from .constants import ONE_MB
from .constants import PROGRESS_COMPLETE
from .constants import PROGRESS_HALF
from .constants import TEN_MB
from .constants import TEST_PASSWORD


@pytest.mark.django_db
class TestProjectFileService(TestCase):
    """Test ProjectFileService class."""

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
            description="Test project for services",
        )

    @patch("wafer_space.projects.tasks.download_project_file.delay")
    @patch("wafer_space.projects.services.URLValidator.validate_url")
    @patch("wafer_space.projects.services.URLRewriter.rewrite_url")
    def test_submit_file_from_url_success(
        self,
        mock_rewrite,
        mock_validate,
        mock_task,
    ):
        """Test successful file submission from URL."""
        # Mock URL rewriting
        original_url = "https://github.com/user/repo/blob/main/file.gds"
        rewritten_url = "https://raw.githubusercontent.com/user/repo/main/file.gds"
        mock_rewrite.return_value = (
            rewritten_url,
            True,
            "Converted GitHub blob URL to raw content URL",
        )

        # Mock validation
        mock_validate.return_value = {
            "file_size": ONE_MB,
            "content_type": "application/octet-stream",
            "etag": '"abc123"',
            "supports_range": True,
        }

        # Mock task
        mock_task.return_value = Mock(id="task-123")

        # Submit file
        project_file, metadata = ProjectFileService.submit_file_from_url(
            project=self.project,
            url=original_url,
            expected_hash_md5="abc123",
            expected_hash_sha1="def456",
        )

        # Verify project file was created
        assert project_file is not None
        assert project_file.project == self.project
        assert project_file.original_url == original_url
        assert project_file.source_url == rewritten_url
        assert project_file.expected_hash_md5 == "abc123"
        assert project_file.expected_hash_sha1 == "def456"
        assert project_file.file_size == ONE_MB
        assert project_file.content_type == "application/octet-stream"
        assert project_file.is_active is True
        # Status is QUEUED because download task is started
        assert project_file.download_status == ProjectFile.DownloadStatus.QUEUED

        # Verify metadata
        assert metadata["url_rewritten"] is True
        # Type assertion for string field
        rewrite_reason = metadata["rewrite_reason"]
        assert isinstance(rewrite_reason, str)
        assert "GitHub blob URL" in rewrite_reason
        assert metadata["file_size"] == ONE_MB
        assert metadata["supports_range"] is True

        # Verify URL rewriting was called
        mock_rewrite.assert_called_once_with(original_url)

        # Verify validation was called (without URL handler, so allow_missing=False)
        mock_validate.assert_called_once_with(
            rewritten_url,
            allow_missing_content_length=False,
        )

        # Verify download task was started
        mock_task.assert_called_once_with(str(self.project.id))

    @patch("wafer_space.projects.tasks.download_project_file.delay")
    @patch("wafer_space.projects.services.URLValidator.validate_url")
    @patch("wafer_space.projects.services.URLRewriter.rewrite_url")
    def test_submit_file_from_url_no_rewrite(
        self,
        mock_rewrite,
        mock_validate,
        mock_task,
    ):
        """Test file submission when URL doesn't need rewriting."""
        url = "https://example.com/file.gds"

        # Mock no rewriting
        mock_rewrite.return_value = (url, False, "")

        # Mock validation
        mock_validate.return_value = {
            "file_size": 2097152,
            "content_type": "application/octet-stream",
            "etag": None,
            "supports_range": False,
        }

        # Mock task
        mock_task.return_value = Mock(id="task-def")

        project_file, metadata = ProjectFileService.submit_file_from_url(
            project=self.project,
            url=url,
        )

        # Verify URLs are the same
        assert project_file.original_url == url
        assert project_file.source_url == url

        # Verify metadata
        assert metadata["url_rewritten"] is False
        assert metadata["rewrite_reason"] == ""
        assert metadata["supports_range"] is False

    @patch("wafer_space.projects.services.URLValidator.validate_url")
    @patch("wafer_space.projects.services.URLRewriter.rewrite_url")
    def test_submit_file_from_url_validation_fails(
        self,
        mock_rewrite,
        mock_validate,
    ):
        """Test file submission when validation fails."""
        url = "http://localhost/file.gds"

        # Mock no rewriting
        mock_rewrite.return_value = (url, False, "")

        # Mock validation failure
        mock_validate.side_effect = SecurityValidationError(
            "Cannot download from localhost",
        )

        # Should raise SecurityValidationError
        with pytest.raises(SecurityValidationError, match="validation failed"):
            ProjectFileService.submit_file_from_url(
                project=self.project,
                url=url,
            )

        # Verify no file was created
        assert ProjectFile.objects.count() == 0

    def test_submit_file_from_url_empty_url(self):
        """Test that empty URL raises ValueError."""
        with pytest.raises(ValueError, match="URL is required"):
            ProjectFileService.submit_file_from_url(
                project=self.project,
                url="",
            )

        with pytest.raises(ValueError, match="URL is required"):
            ProjectFileService.submit_file_from_url(
                project=self.project,
                url="   ",
            )

    @patch("wafer_space.projects.tasks.download_project_file.delay")
    @patch("wafer_space.projects.services.URLValidator.validate_url")
    @patch("wafer_space.projects.services.URLRewriter.rewrite_url")
    def test_submit_file_replaces_existing_active_file(
        self,
        mock_rewrite,
        mock_validate,
        mock_task,
    ):
        """Test that submitting new file marks old file as inactive."""
        # Create existing active file
        old_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/old.gds",
            source_url="https://example.com/old.gds",
            original_filename="old.gds",
            is_active=True,
        )

        url = "https://example.com/new.gds"

        # Mock no rewriting
        mock_rewrite.return_value = (url, False, "")

        # Mock validation
        mock_validate.return_value = {
            "file_size": ONE_MB,
            "content_type": "application/octet-stream",
            "etag": None,
            "supports_range": True,
        }

        # Mock task
        mock_task.return_value = Mock(id="task-456")

        # Submit new file
        new_file, _metadata = ProjectFileService.submit_file_from_url(
            project=self.project,
            url=url,
        )

        # Refresh old file from database
        old_file.refresh_from_db()

        # Verify old file is now inactive
        assert old_file.is_active is False

        # Verify new file is active
        assert new_file.is_active is True

        # Verify only one active file exists
        active_files = ProjectFile.objects.filter(
            project=self.project,
            is_active=True,
        )
        assert active_files.count() == 1
        assert active_files.first() == new_file

    @patch("wafer_space.projects.tasks.download_project_file.delay")
    @patch("wafer_space.projects.services.URLValidator.validate_url")
    @patch("wafer_space.projects.services.URLRewriter.rewrite_url")
    def test_submit_file_extracts_filename_from_url(
        self,
        mock_rewrite,
        mock_validate,
        mock_task,
    ):
        """Test that filename is extracted from URL."""
        url = "https://example.com/path/to/design_file.gds"

        mock_rewrite.return_value = (url, False, "")
        mock_validate.return_value = {
            "file_size": ONE_MB,
            "content_type": "application/octet-stream",
            "etag": None,
            "supports_range": True,
        }
        mock_task.return_value = Mock(id="task-789")

        project_file, _metadata = ProjectFileService.submit_file_from_url(
            project=self.project,
            url=url,
        )

        # Verify filename was extracted
        assert project_file.original_filename == "design_file.gds"

    @patch("wafer_space.projects.tasks.download_project_file.delay")
    @patch("wafer_space.projects.services.URLValidator.validate_url")
    @patch("wafer_space.projects.services.URLRewriter.rewrite_url")
    def test_submit_file_url_decoded_filename(
        self,
        mock_rewrite,
        mock_validate,
        mock_task,
    ):
        """Test that URL-encoded filename is decoded."""
        url = "https://example.com/My%20Design%20File.gds"

        mock_rewrite.return_value = (url, False, "")
        mock_validate.return_value = {
            "file_size": ONE_MB,
            "content_type": "application/octet-stream",
            "etag": None,
            "supports_range": True,
        }
        mock_task.return_value = Mock(id="task-abc")

        project_file, _metadata = ProjectFileService.submit_file_from_url(
            project=self.project,
            url=url,
        )

        # Verify filename was decoded
        assert project_file.original_filename == "My Design File.gds"

    @patch("wafer_space.projects.tasks.download_project_file.delay")
    @patch("wafer_space.projects.services.URLValidator.validate_url")
    @patch("wafer_space.projects.services.URLRewriter.rewrite_url")
    def test_submit_file_stores_task_id(
        self,
        mock_rewrite,
        mock_validate,
        mock_task,
    ):
        """Test that Celery task ID is stored."""
        url = "https://example.com/file.gds"

        mock_rewrite.return_value = (url, False, "")
        mock_validate.return_value = {
            "file_size": ONE_MB,
            "content_type": "application/octet-stream",
            "etag": None,
            "supports_range": True,
        }
        mock_task.return_value = Mock(id="task-xyz-123")

        project_file, _metadata = ProjectFileService.submit_file_from_url(
            project=self.project,
            url=url,
        )

        # Verify task ID was stored
        assert project_file.download_task_id == "task-xyz-123"

    def test_get_download_progress_no_task(self):
        """Test getting progress when no task ID is set."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            file_size=ONE_MB,
        )

        progress = ProjectFileService.get_download_progress(project_file)

        assert progress["status"] == ProjectFile.DownloadStatus.PENDING
        assert progress["progress"] == 0
        assert progress["current"] == 0
        assert progress["total"] == ONE_MB
        # Type assertion for string field
        message = progress["message"]
        assert isinstance(message, str)
        assert "not started" in message.lower()

    @patch("wafer_space.projects.services.AsyncResult")
    def test_get_download_progress_pending(self, mock_async_result):
        """Test getting progress when task is pending."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            file_size=ONE_MB,
            download_task_id="task-123",
        )

        # Mock task state
        mock_task = Mock()
        mock_task.state = "PENDING"
        mock_async_result.return_value = mock_task

        progress = ProjectFileService.get_download_progress(project_file)

        assert progress["status"] == "pending"
        assert progress["progress"] == 0
        assert progress["message"] == "Download pending"

    @patch("wafer_space.projects.services.AsyncResult")
    def test_get_download_progress_in_progress(self, mock_async_result):
        """Test getting progress when task is downloading."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            file_size=TEN_MB,
            download_task_id="task-123",
        )
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.DOWNLOADING,
        )

        # Mock task state with progress
        mock_task = Mock()
        mock_task.state = "PROGRESS"
        mock_task.info = {
            "progress": PROGRESS_HALF,
            "current": FIVE_MB,
            "total": TEN_MB,
            "message": "Downloaded 4,718,592 of 10,485,760 bytes",
        }
        mock_async_result.return_value = mock_task

        progress = ProjectFileService.get_download_progress(project_file)

        assert progress["status"] == "downloading"
        assert progress["progress"] == PROGRESS_HALF
        assert progress["current"] == FIVE_MB
        assert progress["total"] == TEN_MB
        # Type assertion for string field
        message = progress["message"]
        assert isinstance(message, str)
        assert "4,718,592" in message

    @patch("wafer_space.projects.services.AsyncResult")
    def test_get_download_progress_completed(self, mock_async_result):
        """Test getting progress when task is completed."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            file_size=ONE_MB,
            download_task_id="task-123",
        )
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.COMPLETED,
        )

        # Mock task state
        mock_task = Mock()
        mock_task.state = "SUCCESS"
        mock_async_result.return_value = mock_task

        progress = ProjectFileService.get_download_progress(project_file)

        assert progress["status"] == "completed"
        assert progress["progress"] == PROGRESS_COMPLETE
        assert progress["current"] == ONE_MB
        assert progress["total"] == ONE_MB
        # Type assertion for string field
        message = progress["message"]
        assert isinstance(message, str)
        assert "completed" in message.lower()

    @patch("wafer_space.projects.services.AsyncResult")
    def test_get_download_progress_failed(self, mock_async_result):
        """Test getting progress when task failed."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            file_size=ONE_MB,
            download_task_id="task-123",
        )
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.FAILED,
        )

        # Mock task state with error
        mock_task = Mock()
        mock_task.state = "FAILURE"
        mock_task.info = Exception("Connection timeout")
        mock_async_result.return_value = mock_task

        progress = ProjectFileService.get_download_progress(project_file)

        assert progress["status"] == "failed"
        assert progress["progress"] == 0
        # Type assertion for string field
        message = progress["message"]
        assert isinstance(message, str)
        assert "Connection timeout" in message

    @patch("wafer_space.projects.tasks.download_project_file.delay")
    @patch("wafer_space.projects.services.URLValidator.validate_url")
    @patch("wafer_space.projects.services.URLRewriter.rewrite_url")
    def test_submit_file_extracts_filename_from_content_disposition(
        self,
        mock_rewrite,
        mock_validate,
        mock_task,
    ):
        """Test filename extraction from Content-Disposition header."""
        url = "https://api.example.com/download?id=123"

        mock_rewrite.return_value = (url, False, "")
        mock_validate.return_value = {
            "file_size": TEN_MB,
            "content_type": "application/octet-stream",
            "content_disposition": 'attachment; filename="chip_design.gds.gz"',
            "etag": "abc123",
            "supports_range": True,
        }
        mock_task.return_value = Mock(id="task-content-disp")

        project_file, metadata = ProjectFileService.submit_file_from_url(
            project=self.project,
            url=url,
        )

        # Verify filename was extracted from Content-Disposition
        assert project_file.original_filename == "chip_design.gds.gz"
        assert metadata["file_size"] == TEN_MB

    @patch("wafer_space.projects.tasks.download_project_file.delay")
    @patch("wafer_space.projects.services.URLValidator.validate_url")
    @patch("wafer_space.projects.services.URLRewriter.rewrite_url")
    def test_submit_file_extracts_filename_from_utf8_content_disposition(
        self,
        mock_rewrite,
        mock_validate,
        mock_task,
    ):
        """Test filename extraction from UTF-8 Content-Disposition (RFC 5987)."""
        url = "https://api.example.com/download?id=456"

        mock_rewrite.return_value = (url, False, "")
        mock_validate.return_value = {
            "file_size": FIVE_MB,
            "content_type": "application/octet-stream",
            "content_disposition": "attachment; filename*=UTF-8''my%20design.oas",
            "etag": "def456",
            "supports_range": True,
        }
        mock_task.return_value = Mock(id="task-utf8")

        project_file, metadata = ProjectFileService.submit_file_from_url(
            project=self.project,
            url=url,
        )

        # Verify filename was extracted and URL-decoded
        assert project_file.original_filename == "my design.oas"
        assert metadata["file_size"] == FIVE_MB


class TestDetectFileType(TestCase):
    """Test MIME type detection for file validation."""

    def test_detect_gzip_file(self):
        """Test detection of gzip compressed file."""
        # Gzip magic bytes
        gzip_data = b"\x1f\x8b\x08\x00" + b"\x00" * 100
        mime_type, extension = detect_file_type_from_data(gzip_data)
        assert mime_type == "application/gzip"
        assert extension == ".gds.gz"

    def test_detect_zip_file(self):
        """Test detection of zip compressed file."""
        # ZIP magic bytes (PK header)
        zip_data = b"PK\x03\x04" + b"\x00" * 100
        mime_type, extension = detect_file_type_from_data(zip_data)
        assert mime_type in ["application/zip", "application/x-zip-compressed"]
        assert extension == ".gds.zip"

    def test_detect_bzip2_file(self):
        """Test detection of bzip2 compressed file."""
        # Bzip2 magic bytes
        bz2_data = b"BZh9" + b"\x00" * 100
        mime_type, extension = detect_file_type_from_data(bz2_data)
        assert mime_type == "application/x-bzip2"
        assert extension == ".gds.bz2"

    def test_detect_xz_file(self):
        """Test detection of xz compressed file."""
        # XZ magic bytes
        xz_data = b"\xfd7zXZ\x00" + b"\x00" * 100
        mime_type, extension = detect_file_type_from_data(xz_data)
        assert mime_type == "application/x-xz"
        assert extension == ".gds.xz"

    def test_detect_binary_file_as_gds(self):
        """Test detection of generic binary file (assumed to be GDS)."""
        # Generic binary data
        binary_data = b"\x00\x01\x02\x03" + b"\x00" * 100
        mime_type, extension = detect_file_type_from_data(binary_data)
        assert mime_type == "application/octet-stream"
        assert extension == ".gds"

    def test_reject_text_file(self):
        """Test that text files are rejected."""
        text_data = b"This is a text file, not a GDS file"
        with pytest.raises(ValueError, match="Unsupported file type"):
            detect_file_type_from_data(text_data)

    def test_reject_html_file(self):
        """Test that HTML files are rejected."""
        html_data = b"<!DOCTYPE html><html><body>Not a GDS file</body></html>"
        with pytest.raises(ValueError, match="Unsupported file type"):
            detect_file_type_from_data(html_data)

    def test_reject_pdf_file(self):
        """Test that PDF files are rejected."""
        # PDF magic bytes
        pdf_data = b"%PDF-1.4" + b"\x00" * 100
        with pytest.raises(ValueError, match="Unsupported file type"):
            detect_file_type_from_data(pdf_data)


@pytest.mark.django_db
class TestManufacturabilityService(TestCase):
    """Test ManufacturabilityService class."""

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
            description="Test project for manufacturability checks",
        )
        self.project_file = ProjectFile.objects.create(
            project=self.project,
            original_filename="test.gds",
            source_url="https://example.com/test.gds",
            is_active=True,
        )

    @patch("wafer_space.projects.tasks.check_project_manufacturability.delay")
    def test_queue_check_creates_new_check(self, mock_task):
        """Test that queue_check creates a new check and triggers task."""
        # Mock the Celery task
        mock_task.return_value = Mock(id="task-123")

        # Queue the check
        check = ManufacturabilityService.queue_check(self.project, self.project_file)

        # Verify check was created
        assert check is not None
        assert check.project == self.project
        assert check.project_file == self.project_file
        assert check.status == ManufacturabilityCheck.Status.QUEUED
        assert check.task_id == "task-123"

        # Verify task was called
        mock_task.assert_called_once_with(check.id)

        # Verify check exists in database
        check_count = ManufacturabilityCheck.objects.filter(
            project_file=self.project_file
        ).count()
        assert check_count == 1

    @patch("wafer_space.projects.tasks.check_project_manufacturability.delay")
    def test_queue_check_resets_existing_check(self, mock_task):
        """Test that queue_check resets an existing completed check."""
        # Create an existing completed check
        existing_check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.COMPLETED,
            is_manufacturable=True,
            errors=["Old error"],
            warnings=["Old warning"],
            processing_logs="Old logs",
            retry_count=2,
        )

        # Mock the Celery task
        mock_task.return_value = Mock(id="task-456")

        # Queue the check again
        check = ManufacturabilityService.queue_check(self.project, self.project_file)

        # Verify it's the same check instance, but reset
        assert check.id == existing_check.id
        assert check.status == ManufacturabilityCheck.Status.QUEUED
        assert check.is_manufacturable is None
        assert check.errors == []
        assert check.warnings == []
        assert check.processing_logs == ""
        assert check.retry_count == 0
        assert check.task_id == "task-456"

        # Verify task was called
        mock_task.assert_called_once_with(check.id)

        # Verify only one check exists
        check_count = ManufacturabilityCheck.objects.filter(
            project_file=self.project_file
        ).count()
        assert check_count == 1

    @patch("wafer_space.projects.tasks.check_project_manufacturability.delay")
    def test_queue_check_does_not_reset_queued_check(self, mock_task):
        """Test that queue_check doesn't reset/re-queue a check already QUEUED."""
        # Create an existing queued check
        existing_check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.QUEUED,
            task_id="existing-task-id",
        )

        # Mock the Celery task
        mock_task.return_value = Mock(id="task-789")

        # Queue the check again
        check = ManufacturabilityService.queue_check(self.project, self.project_file)

        # Verify it's the same check instance and unchanged
        assert check.id == existing_check.id
        assert check.status == ManufacturabilityCheck.Status.QUEUED

        # Task should NOT be called again (already queued)
        mock_task.assert_not_called()

        # task_id should remain unchanged
        assert check.task_id == "existing-task-id"

    def test_get_check_status_returns_correct_data(self):
        """Test that get_check_status returns correct status information."""
        # Create a completed check
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.COMPLETED,
            is_manufacturable=False,
            errors=["Error 1", "Error 2"],
            warnings=["Warning 1"],
        )
        check.start_processing()
        check.complete(
            is_manufacturable=False,
            errors=["Error 1", "Error 2"],
            warnings=["Warning 1"],
        )

        # Get status
        status = ManufacturabilityService.get_check_status(self.project)

        # Verify status data
        assert status is not None
        assert status["status"] == ManufacturabilityCheck.Status.COMPLETED
        assert status["is_manufacturable"] is False
        assert status["errors"] == ["Error 1", "Error 2"]
        assert status["warnings"] == ["Warning 1"]
        assert status["started_at"] is not None
        assert status["completed_at"] is not None

    def test_get_check_status_returns_none_when_no_check(self):
        """Test that get_check_status returns None when no check exists."""
        # Get status for project with no check
        status = ManufacturabilityService.get_check_status(self.project)

        # Verify None is returned
        assert status is None

    def test_get_check_status_for_queued_check(self):
        """Test get_check_status for a queued check."""
        # Create a queued check
        ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.QUEUED,
        )

        # Get status
        status = ManufacturabilityService.get_check_status(self.project)

        # Verify status data
        assert status is not None
        assert status["status"] == ManufacturabilityCheck.Status.QUEUED
        assert status["is_manufacturable"] is None
        assert status["errors"] == []
        assert status["warnings"] == []
        assert status["started_at"] is None
        assert status["completed_at"] is None

    def test_get_check_status_for_processing_check(self):
        """Test get_check_status for a processing check."""
        # Create and start processing a check
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.QUEUED,
        )
        check.start_processing()

        # Get status
        status = ManufacturabilityService.get_check_status(self.project)

        # Verify status data
        assert status is not None
        assert status["status"] == ManufacturabilityCheck.Status.PROCESSING
        assert status["is_manufacturable"] is None
        assert status["started_at"] is not None
        assert status["completed_at"] is None

    def test_get_check_status_for_failed_check(self):
        """Test get_check_status for a failed check."""
        # Create a failed check
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.QUEUED,
        )
        check.start_processing()
        check.fail("Test error message")

        # Get status
        status = ManufacturabilityService.get_check_status(self.project)

        # Verify status data
        assert status is not None
        assert status["status"] == ManufacturabilityCheck.Status.FAILED
        assert status["is_manufacturable"] is None
        assert status["started_at"] is not None
        assert status["completed_at"] is not None
