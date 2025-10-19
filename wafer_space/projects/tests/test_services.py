"""Tests for services layer."""

from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.test import TestCase

from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.projects.security import SecurityValidationError
from wafer_space.projects.services import ProjectFileService
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
        assert project_file.download_status == ProjectFile.DownloadStatus.PENDING

        # Verify metadata
        assert metadata["url_rewritten"] is True
        assert "GitHub blob URL" in metadata["rewrite_reason"]
        assert metadata["file_size"] == ONE_MB
        assert metadata["supports_range"] is True

        # Verify URL rewriting was called
        mock_rewrite.assert_called_once_with(original_url)

        # Verify validation was called
        mock_validate.assert_called_once_with(rewritten_url)

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
            download_status=ProjectFile.DownloadStatus.PENDING,
        )

        progress = ProjectFileService.get_download_progress(project_file)

        assert progress["status"] == ProjectFile.DownloadStatus.PENDING
        assert progress["progress"] == 0
        assert progress["current"] == 0
        assert progress["total"] == ONE_MB
        assert "not started" in progress["message"].lower()

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
            download_status=ProjectFile.DownloadStatus.PENDING,
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
            download_status=ProjectFile.DownloadStatus.DOWNLOADING,
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
        assert "4,718,592" in progress["message"]

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
            download_status=ProjectFile.DownloadStatus.COMPLETED,
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
        assert "completed" in progress["message"].lower()

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
            download_status=ProjectFile.DownloadStatus.FAILED,
        )

        # Mock task state with error
        mock_task = Mock()
        mock_task.state = "FAILURE"
        mock_task.info = Exception("Connection timeout")
        mock_async_result.return_value = mock_task

        progress = ProjectFileService.get_download_progress(project_file)

        assert progress["status"] == "failed"
        assert progress["progress"] == 0
        assert "Connection timeout" in progress["message"]

    @patch("wafer_space.projects.services.URLValidator.validate_url")
    @patch("wafer_space.projects.services.URLRewriter.rewrite_url")
    def test_submit_file_rejects_invalid_format_pdf(
        self,
        mock_rewrite,
        mock_validate,
    ):
        """Test that PDF files are rejected."""
        url = "https://example.com/design.pdf"

        mock_rewrite.return_value = (url, False, "")
        mock_validate.return_value = {
            "file_size": ONE_MB,
            "content_type": "application/pdf",
            "etag": None,
            "supports_range": True,
        }

        with pytest.raises(ValueError, match=r"Invalid file format.*pdf"):
            ProjectFileService.submit_file_from_url(
                project=self.project,
                url=url,
            )

        # Verify no file was created
        assert ProjectFile.objects.count() == 0

    @patch("wafer_space.projects.services.URLValidator.validate_url")
    @patch("wafer_space.projects.services.URLRewriter.rewrite_url")
    def test_submit_file_rejects_invalid_format_svg(
        self,
        mock_rewrite,
        mock_validate,
    ):
        """Test that SVG files are rejected."""
        url = "https://example.com/schematic.svg"

        mock_rewrite.return_value = (url, False, "")
        mock_validate.return_value = {
            "file_size": ONE_MB,
            "content_type": "image/svg+xml",
            "etag": None,
            "supports_range": True,
        }

        with pytest.raises(ValueError, match=r"Invalid file format.*svg"):
            ProjectFileService.submit_file_from_url(
                project=self.project,
                url=url,
            )

        # Verify no file was created
        assert ProjectFile.objects.count() == 0

    @patch("wafer_space.projects.services.URLValidator.validate_url")
    @patch("wafer_space.projects.services.URLRewriter.rewrite_url")
    def test_submit_file_rejects_invalid_format_cif(
        self,
        mock_rewrite,
        mock_validate,
    ):
        """Test that CIF files are rejected."""
        url = "https://example.com/layout.cif"

        mock_rewrite.return_value = (url, False, "")
        mock_validate.return_value = {
            "file_size": ONE_MB,
            "content_type": "application/octet-stream",
            "etag": None,
            "supports_range": True,
        }

        with pytest.raises(ValueError, match=r"Invalid file format.*cif"):
            ProjectFileService.submit_file_from_url(
                project=self.project,
                url=url,
            )

        # Verify no file was created
        assert ProjectFile.objects.count() == 0

    @patch("wafer_space.projects.tasks.download_project_file.delay")
    @patch("wafer_space.projects.services.URLValidator.validate_url")
    @patch("wafer_space.projects.services.URLRewriter.rewrite_url")
    def test_submit_file_accepts_gds_formats(
        self,
        mock_rewrite,
        mock_validate,
        mock_task,
    ):
        """Test that all GDS formats are accepted."""
        gds_formats = ["design.gds", "chip.gdsii", "layout.gds2"]

        for filename in gds_formats:
            url = f"https://example.com/{filename}"

            mock_rewrite.return_value = (url, False, "")
            mock_validate.return_value = {
                "file_size": ONE_MB,
                "content_type": "application/octet-stream",
                "etag": None,
                "supports_range": True,
            }
            mock_task.return_value = Mock(id=f"task-{filename}")

            project_file, _metadata = ProjectFileService.submit_file_from_url(
                project=self.project,
                url=url,
            )

            # Verify file was created with correct filename
            assert project_file.original_filename == filename

            # Clean up for next iteration
            project_file.delete()

    @patch("wafer_space.projects.tasks.download_project_file.delay")
    @patch("wafer_space.projects.services.URLValidator.validate_url")
    @patch("wafer_space.projects.services.URLRewriter.rewrite_url")
    def test_submit_file_accepts_oasis_formats(
        self,
        mock_rewrite,
        mock_validate,
        mock_task,
    ):
        """Test that all OASIS formats are accepted."""
        oasis_formats = ["design.oas", "chip.oasis"]

        for filename in oasis_formats:
            url = f"https://example.com/{filename}"

            mock_rewrite.return_value = (url, False, "")
            mock_validate.return_value = {
                "file_size": ONE_MB,
                "content_type": "application/octet-stream",
                "etag": None,
                "supports_range": True,
            }
            mock_task.return_value = Mock(id=f"task-{filename}")

            project_file, _metadata = ProjectFileService.submit_file_from_url(
                project=self.project,
                url=url,
            )

            # Verify file was created with correct filename
            assert project_file.original_filename == filename

            # Clean up for next iteration
            project_file.delete()

    @patch("wafer_space.projects.tasks.download_project_file.delay")
    @patch("wafer_space.projects.services.URLValidator.validate_url")
    @patch("wafer_space.projects.services.URLRewriter.rewrite_url")
    def test_submit_file_accepts_compressed_formats(
        self,
        mock_rewrite,
        mock_validate,
        mock_task,
    ):
        """Test that compressed GDS/OASIS files are accepted."""
        compressed_formats = [
            "design.gds.gz",
            "chip.gdsii.zip",
            "layout.oas.bz2",
            "test.oasis.xz",
        ]

        for filename in compressed_formats:
            url = f"https://example.com/{filename}"

            mock_rewrite.return_value = (url, False, "")
            mock_validate.return_value = {
                "file_size": ONE_MB,
                "content_type": "application/octet-stream",
                "etag": None,
                "supports_range": True,
            }
            mock_task.return_value = Mock(id=f"task-{filename}")

            project_file, _metadata = ProjectFileService.submit_file_from_url(
                project=self.project,
                url=url,
            )

            # Verify file was created with correct filename
            assert project_file.original_filename == filename

            # Clean up for next iteration
            project_file.delete()

    @patch("wafer_space.projects.services.URLValidator.validate_url")
    @patch("wafer_space.projects.services.URLRewriter.rewrite_url")
    def test_submit_file_rejects_compressed_without_gds_extension(
        self,
        mock_rewrite,
        mock_validate,
    ):
        """Test that compressed files without GDS/OASIS extension are rejected."""
        url = "https://example.com/file.zip"

        mock_rewrite.return_value = (url, False, "")
        mock_validate.return_value = {
            "file_size": ONE_MB,
            "content_type": "application/zip",
            "etag": None,
            "supports_range": True,
        }

        with pytest.raises(
            ValueError,
            match="Compressed files must have a GDS/OASIS extension",
        ):
            ProjectFileService.submit_file_from_url(
                project=self.project,
                url=url,
            )

        # Verify no file was created
        assert ProjectFile.objects.count() == 0
