"""Tests for download checkpoint creation, logging, and display.

These tests verify that:
1. Database checkpoints are created at correct intervals (every 5MB or 5%)
2. Progress logs occur at correct intervals (every 10MB or 10%)
3. Checkpoints align to clean boundaries when resuming downloads
4. Template displays checkpoints correctly
"""

import logging
from datetime import datetime
from datetime import timezone as dt_timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase

from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.projects.models import ProjectFileChunk
from wafer_space.projects.tasks import _ChunkDownloadState
from wafer_space.projects.tasks import _download_chunks
from wafer_space.projects.tasks import _should_log_progress
from wafer_space.projects.tasks import _should_update_database

User = get_user_model()
TEST_PASSWORD = "testpass123"  # noqa: S105

# Test constants
MB = 1024 * 1024
CHUNK_SIZE = 1 * MB  # 1MB chunks


@pytest.mark.django_db
class DatabaseCheckpointFrequencyTests(TestCase):
    """Tests for database checkpoint creation frequency."""

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
            description="Test Description",
        )
        self.project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            original_filename="test.gds",
            download_status=ProjectFile.DownloadStatus.DOWNLOADING,
            is_active=True,
        )

    def test_checkpoint_every_5mb_unknown_size(self):
        """Test checkpoints created every 5MB for unknown-size files."""
        # Simulate download from 0 to 25MB (should create 5 checkpoints)
        total_size = 0  # Unknown size
        last_db_update_progress = 0
        last_db_update_bytes = 0

        checkpoints = []
        for downloaded in range(0, 26 * MB, MB):  # 0 to 25MB in 1MB increments
            should_update, new_progress, new_bytes = _should_update_database(
                total_size=total_size,
                downloaded=downloaded,
                last_db_update_progress=last_db_update_progress,
                last_db_update_bytes=last_db_update_bytes,
            )
            if should_update:
                checkpoints.append(downloaded)
                last_db_update_progress = new_progress
                last_db_update_bytes = new_bytes

        # Verify checkpoints at: 5MB, 10MB, 15MB, 20MB, 25MB
        assert len(checkpoints) == 5
        assert checkpoints == [5 * MB, 10 * MB, 15 * MB, 20 * MB, 25 * MB]

    def test_checkpoint_every_5_percent_known_size(self):
        """Test checkpoints created every 5% for known-size files."""
        total_size = 100 * MB  # Known size
        last_db_update_progress = 0
        last_db_update_bytes = 0

        checkpoints = []
        # Simulate download from 0 to 100MB
        for downloaded in range(0, 101 * MB, MB):
            should_update, new_progress, new_bytes = _should_update_database(
                total_size=total_size,
                downloaded=downloaded,
                last_db_update_progress=last_db_update_progress,
                last_db_update_bytes=last_db_update_bytes,
            )
            if should_update:
                checkpoints.append(downloaded)
                last_db_update_progress = new_progress
                last_db_update_bytes = new_bytes

        # Verify checkpoints at: 5%, 10%, 15%, ... 100%
        # 5% of 100MB = 5MB, 10% = 10MB, etc.
        expected = [5 * MB, 10 * MB, 15 * MB, 20 * MB, 25 * MB, 30 * MB,
                   35 * MB, 40 * MB, 45 * MB, 50 * MB, 55 * MB, 60 * MB,
                   65 * MB, 70 * MB, 75 * MB, 80 * MB, 85 * MB, 90 * MB,
                   95 * MB, 100 * MB]
        assert len(checkpoints) == 20
        assert checkpoints == expected

    def test_checkpoint_alignment_on_resume(self):
        """Test checkpoints align to 5MB boundaries when resuming."""
        # Resume from 42.31 MB (should align to 40MB, next checkpoint at 45MB)
        total_size = 0  # Unknown size
        resume_pos = int(42.31 * MB)

        # Calculate aligned position (same logic as in _download_chunks)
        mb_downloaded = resume_pos / MB
        last_db_update_mb = int(mb_downloaded / 5) * 5  # Round down to nearest 5MB
        last_db_update_bytes = last_db_update_mb * MB

        # Verify aligned to 40MB
        assert last_db_update_mb == 40
        assert last_db_update_bytes == 40 * MB

        # Verify next checkpoint triggers at 45MB
        last_db_update_progress = 0
        should_update_44mb, _, _ = _should_update_database(
            total_size=total_size,
            downloaded=int(44.9 * MB),
            last_db_update_progress=last_db_update_progress,
            last_db_update_bytes=last_db_update_bytes,
        )
        should_update_45mb, _, _ = _should_update_database(
            total_size=total_size,
            downloaded=int(45.1 * MB),
            last_db_update_progress=last_db_update_progress,
            last_db_update_bytes=last_db_update_bytes,
        )

        assert not should_update_44mb  # Before 45MB boundary
        assert should_update_45mb  # At/after 45MB boundary

    def test_checkpoint_count_for_large_file(self):
        """Test correct checkpoint count for large file (230MB)."""
        total_size = 0  # Unknown size
        last_db_update_progress = 0
        last_db_update_bytes = 0

        checkpoints = []
        # Simulate download from 0 to 230MB
        for downloaded in range(0, 231 * MB, MB):
            should_update, new_progress, new_bytes = _should_update_database(
                total_size=total_size,
                downloaded=downloaded,
                last_db_update_progress=last_db_update_progress,
                last_db_update_bytes=last_db_update_bytes,
            )
            if should_update:
                checkpoints.append(downloaded)
                last_db_update_progress = new_progress
                last_db_update_bytes = new_bytes

        # Verify 46 checkpoints (5, 10, 15, ... 230)
        assert len(checkpoints) == 46
        assert checkpoints[0] == 5 * MB  # First checkpoint
        assert checkpoints[-1] == 230 * MB  # Last checkpoint


@pytest.mark.django_db
class ProgressLoggingFrequencyTests(TestCase):
    """Tests for progress logging frequency."""

    def test_log_every_10mb_unknown_size(self):
        """Test progress logs every 10MB for unknown-size files."""
        total_size = 0  # Unknown size
        last_log_progress = 0
        last_log_bytes = 0

        logs = []
        for downloaded in range(0, 51 * MB, MB):  # 0 to 50MB
            should_log, new_progress, new_bytes = _should_log_progress(
                total_size=total_size,
                downloaded=downloaded,
                last_log_progress=last_log_progress,
                last_log_bytes=last_log_bytes,
            )
            if should_log:
                logs.append(downloaded)
                last_log_progress = new_progress
                last_log_bytes = new_bytes

        # Verify logs at: 10MB, 20MB, 30MB, 40MB, 50MB
        assert len(logs) == 5
        assert logs == [10 * MB, 20 * MB, 30 * MB, 40 * MB, 50 * MB]

    def test_log_every_10_percent_known_size(self):
        """Test progress logs every 10% for known-size files."""
        total_size = 100 * MB  # Known size
        last_log_progress = 0
        last_log_bytes = 0

        logs = []
        for downloaded in range(0, 101 * MB, MB):
            should_log, new_progress, new_bytes = _should_log_progress(
                total_size=total_size,
                downloaded=downloaded,
                last_log_progress=last_log_progress,
                last_log_bytes=last_log_bytes,
            )
            if should_log:
                logs.append(downloaded)
                last_log_progress = new_progress
                last_log_bytes = new_bytes

        # Verify logs at: 10%, 20%, 30%, ... 100%
        expected = [10 * MB, 20 * MB, 30 * MB, 40 * MB, 50 * MB,
                   60 * MB, 70 * MB, 80 * MB, 90 * MB, 100 * MB]
        assert len(logs) == 10
        assert logs == expected

    def test_log_alignment_on_resume(self):
        """Test progress logs align to 10MB boundaries when resuming."""
        # Resume from 42.31 MB (should align to 40MB, next log at 50MB)
        total_size = 0  # Unknown size
        resume_pos = int(42.31 * MB)

        # Calculate aligned position
        mb_downloaded = resume_pos / MB
        last_log_mb = int(mb_downloaded / 10) * 10  # Round down to nearest 10MB
        last_log_bytes = last_log_mb * MB

        # Verify aligned to 40MB
        assert last_log_mb == 40
        assert last_log_bytes == 40 * MB

        # Verify next log triggers at 50MB
        last_log_progress = 0
        should_log_49mb, _, _ = _should_log_progress(
            total_size=total_size,
            downloaded=int(49.9 * MB),
            last_log_progress=last_log_progress,
            last_log_bytes=last_log_bytes,
        )
        should_log_50mb, _, _ = _should_log_progress(
            total_size=total_size,
            downloaded=int(50.1 * MB),
            last_log_progress=last_log_progress,
            last_log_bytes=last_log_bytes,
        )

        assert not should_log_49mb  # Before 50MB boundary
        assert should_log_50mb  # At/after 50MB boundary


@pytest.mark.django_db
class DownloadChunksIntegrationTests(TestCase):
    """Integration tests for _download_chunks() function."""

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
            description="Test Description",
        )
        self.project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            original_filename="test.gds",
            download_status=ProjectFile.DownloadStatus.DOWNLOADING,
            is_active=True,
        )

    @patch("wafer_space.projects.tasks.timezone")
    def test_creates_database_checkpoints_during_download(self, mock_timezone):
        """Test that database checkpoints are created during download."""
        # Mock time to avoid test flakiness
        mock_timezone.now.return_value = datetime(2025, 1, 1, 0, 0, 0, tzinfo=dt_timezone.utc)

        # Create mock response with 25MB of data (should create 5 checkpoints)
        file_size = 25 * MB
        mock_response = Mock()
        # Simulate streaming 1MB chunks
        chunks = [b"x" * MB for _ in range(25)]
        mock_response.iter_content.return_value = iter(chunks)

        # Create mock task
        mock_task = Mock()
        mock_task.update_state = Mock()

        # Create temp file path
        temp_path = Path("/tmp/test_download.gds")
        temp_path.unlink(missing_ok=True)

        try:
            # Create download state
            state = _ChunkDownloadState(
                response=mock_response,
                temp_path=temp_path,
                task=mock_task,
                project_file=self.project_file,
                total_size=0,  # Unknown size
                resume_byte_pos=0,
                md5_hasher=Mock(update=Mock()),
                sha1_hasher=Mock(update=Mock()),
                chunk_size=CHUNK_SIZE,
                start_time=0.0,
            )

            # Run download
            chunk_count = _download_chunks(state)

            # Verify chunks downloaded
            assert chunk_count == 25

            # Verify database checkpoints created
            checkpoints = ProjectFileChunk.objects.filter(
                project_file=self.project_file
            ).order_by("bytes_downloaded")

            # Should have 5 checkpoints: 5MB, 10MB, 15MB, 20MB, 25MB
            assert checkpoints.count() == 5
            assert checkpoints[0].bytes_downloaded == 5 * MB
            assert checkpoints[1].bytes_downloaded == 10 * MB
            assert checkpoints[2].bytes_downloaded == 15 * MB
            assert checkpoints[3].bytes_downloaded == 20 * MB
            assert checkpoints[4].bytes_downloaded == 25 * MB

        finally:
            # Cleanup
            temp_path.unlink(missing_ok=True)

    @patch("wafer_space.projects.tasks.timezone")
    def test_checkpoints_with_resume(self, mock_timezone):
        """Test checkpoints align correctly when resuming download."""
        mock_timezone.now.return_value = datetime(2025, 1, 1, 0, 0, 0, tzinfo=dt_timezone.utc)

        # Resume from 42MB, download to 60MB (18MB more)
        resume_pos = 42 * MB
        additional_data = 18 * MB

        # Create mock response
        mock_response = Mock()
        chunks = [b"x" * MB for _ in range(18)]  # 18 more MB
        mock_response.iter_content.return_value = iter(chunks)

        # Create mock task
        mock_task = Mock()
        mock_task.update_state = Mock()

        # Create temp file with existing data
        temp_path = Path("/tmp/test_resume_download.gds")
        temp_path.write_bytes(b"x" * resume_pos)

        try:
            # Create download state (resuming from 42MB)
            state = _ChunkDownloadState(
                response=mock_response,
                temp_path=temp_path,
                task=mock_task,
                project_file=self.project_file,
                total_size=0,  # Unknown size
                resume_byte_pos=resume_pos,
                md5_hasher=Mock(update=Mock()),
                sha1_hasher=Mock(update=Mock()),
                chunk_size=CHUNK_SIZE,
                start_time=0.0,
            )

            # Run download
            chunk_count = _download_chunks(state)

            # Verify chunks downloaded
            assert chunk_count == 18

            # Verify database checkpoints align to clean boundaries
            checkpoints = ProjectFileChunk.objects.filter(
                project_file=self.project_file
            ).order_by("bytes_downloaded")

            # Resume from 42MB, aligned to 40MB
            # Next checkpoints: 45MB, 50MB, 55MB, 60MB (4 checkpoints)
            assert checkpoints.count() == 4
            assert checkpoints[0].bytes_downloaded == 45 * MB
            assert checkpoints[1].bytes_downloaded == 50 * MB
            assert checkpoints[2].bytes_downloaded == 55 * MB
            assert checkpoints[3].bytes_downloaded == 60 * MB

        finally:
            # Cleanup
            temp_path.unlink(missing_ok=True)

    @patch("wafer_space.projects.tasks.timezone")
    def test_checkpoint_data_accuracy(self, mock_timezone):
        """Test checkpoint stores accurate data (bytes, chunk number)."""
        mock_timezone.now.return_value = datetime(2025, 1, 1, 0, 0, 0, tzinfo=dt_timezone.utc)

        # Download 10MB (should create 2 checkpoints: 5MB, 10MB)
        file_size = 10 * MB
        mock_response = Mock()
        chunks = [b"x" * MB for _ in range(10)]
        mock_response.iter_content.return_value = iter(chunks)

        mock_task = Mock()
        mock_task.update_state = Mock()

        temp_path = Path("/tmp/test_checkpoint_data.gds")
        temp_path.unlink(missing_ok=True)

        try:
            state = _ChunkDownloadState(
                response=mock_response,
                temp_path=temp_path,
                task=mock_task,
                project_file=self.project_file,
                total_size=0,
                resume_byte_pos=0,
                md5_hasher=Mock(update=Mock()),
                sha1_hasher=Mock(update=Mock()),
                chunk_size=CHUNK_SIZE,
                start_time=0.0,
            )

            _download_chunks(state)

            # Verify checkpoint data
            checkpoints = ProjectFileChunk.objects.filter(
                project_file=self.project_file
            ).order_by("bytes_downloaded")

            assert checkpoints.count() == 2

            # First checkpoint: 5MB downloaded, chunk #5
            assert checkpoints[0].bytes_downloaded == 5 * MB
            assert checkpoints[0].chunk_number == 5

            # Second checkpoint: 10MB downloaded, chunk #10
            assert checkpoints[1].bytes_downloaded == 10 * MB
            assert checkpoints[1].chunk_number == 10

        finally:
            temp_path.unlink(missing_ok=True)


@pytest.mark.django_db
class ProgressLoggingIntegrationTests(TestCase):
    """Integration tests for progress logging during downloads."""

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
            description="Test Description",
        )
        self.project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            original_filename="test.gds",
            download_status=ProjectFile.DownloadStatus.DOWNLOADING,
            is_active=True,
        )

    @patch("wafer_space.projects.tasks.timezone")
    def test_progress_logs_at_correct_intervals(self, mock_timezone):
        """Test progress logs occur at 10MB intervals."""
        mock_timezone.now.return_value = datetime(2025, 1, 1, 0, 0, 0, tzinfo=dt_timezone.utc)

        # Download 50MB (should log at: 10, 20, 30, 40, 50 MB)
        file_size = 50 * MB
        mock_response = Mock()
        chunks = [b"x" * MB for _ in range(50)]
        mock_response.iter_content.return_value = iter(chunks)

        mock_task = Mock()
        mock_task.update_state = Mock()

        temp_path = Path("/tmp/test_progress_logs.gds")
        temp_path.unlink(missing_ok=True)

        try:
            state = _ChunkDownloadState(
                response=mock_response,
                temp_path=temp_path,
                task=mock_task,
                project_file=self.project_file,
                total_size=0,  # Unknown size
                resume_byte_pos=0,
                md5_hasher=Mock(update=Mock()),
                sha1_hasher=Mock(update=Mock()),
                chunk_size=CHUNK_SIZE,
                start_time=0.0,
            )

            # Capture log output
            with self.assertLogs("wafer_space.projects.tasks", level=logging.INFO) as log_context:
                _download_chunks(state)

            # Verify progress logs appear in output
            log_output = "\n".join(log_context.output)

            # Should contain progress logs with file path
            assert "Progress [/tmp/test_progress_logs.gds]" in log_output

            # Count progress log entries (not including "Starting chunked download" or "Download complete")
            progress_logs = [
                line for line in log_context.output
                if "Progress [" in line and "chunks" in line
            ]

            # Should have 5 progress logs: 10, 20, 30, 40, 50 MB
            assert len(progress_logs) >= 5

        finally:
            temp_path.unlink(missing_ok=True)
