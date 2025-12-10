"""Tests for Docker utility functions."""

from __future__ import annotations

import contextlib
import gzip
import hashlib
import logging
import tarfile
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import docker

from wafer_space.projects.docker_utils import create_tar_archive
from wafer_space.projects.docker_utils import parse_docker_timestamp_float
from wafer_space.projects.docker_utils import stream_archive_to_file
from wafer_space.projects.docker_utils import stream_container_diff_to_file
from wafer_space.projects.docker_utils import strip_docker_timestamps

if TYPE_CHECKING:
    from collections.abc import Iterator


class TestParseDockerTimestampFloat:
    """Test parse_docker_timestamp_float function."""

    def test_parses_standard_docker_timestamp(self) -> None:
        """Parses standard Docker timestamp to float."""
        line = "2024-12-05T14:30:45.123456789Z Some log message"
        result = parse_docker_timestamp_float(line)
        assert result is not None
        # 2024-12-05T14:30:45Z as Unix timestamp
        expected_base = 1733409045.0
        expected_max = 1733409046.0
        assert expected_base < result < expected_max

    def test_preserves_nanosecond_precision(self) -> None:
        """Float preserves sub-second precision at microsecond level."""
        # Nanosecond precision is limited by float64
        # Use microseconds for reliable comparison
        line1 = "2024-12-05T14:30:45.000001000Z First"
        line2 = "2024-12-05T14:30:45.000002000Z Second"
        result1 = parse_docker_timestamp_float(line1)
        result2 = parse_docker_timestamp_float(line2)
        assert result1 is not None
        assert result2 is not None
        assert result2 > result1

    def test_returns_none_for_invalid_line(self) -> None:
        """Returns None if line doesn't start with timestamp."""
        result = parse_docker_timestamp_float("No timestamp here")
        assert result is None

    def test_handles_varying_nanosecond_lengths(self) -> None:
        """Handles timestamps with different nanosecond digit counts."""
        # 3 digits
        result = parse_docker_timestamp_float("2024-12-05T14:30:45.123Z msg")
        assert result is not None
        # 9 digits
        result = parse_docker_timestamp_float("2024-12-05T14:30:45.123456789Z msg")
        assert result is not None


class TestStripDockerTimestamps:
    """Test strip_docker_timestamps function."""

    def test_strips_timestamps_from_log_lines(self) -> None:
        """Removes Docker timestamps from beginning of lines."""
        logs = (
            "2024-12-05T14:30:45.123456789Z Hello\n2024-12-05T14:30:46.000000000Z World"
        )
        result = strip_docker_timestamps(logs)
        assert result == "Hello\nWorld"

    def test_preserves_lines_without_timestamps(self) -> None:
        """Lines without timestamps are preserved as-is."""
        logs = "No timestamp here\nAlso no timestamp"
        result = strip_docker_timestamps(logs)
        assert result == "No timestamp here\nAlso no timestamp"

    def test_handles_empty_string(self) -> None:
        """Empty string returns empty string."""
        assert strip_docker_timestamps("") == ""


class TestCreateTarArchive:
    """Test create_tar_archive function (context manager returning temp file)."""

    def test_creates_valid_tar_archive(self, tmp_path: Path) -> None:
        """Creates a valid tar archive from a file."""
        # Create a test file
        test_file = tmp_path / "test.gds"
        test_content = b"test file content"
        test_file.write_bytes(test_content)

        # Create the archive using context manager
        with create_tar_archive(test_file) as tar_stream:
            # Verify it's a valid tar
            tar_stream.seek(0)
            with tarfile.open(fileobj=tar_stream, mode="r") as tar:
                members = tar.getnames()
                assert len(members) == 1
                assert members[0] == "design.gds"

    def test_uses_custom_arcname(self, tmp_path: Path) -> None:
        """Uses the specified arcname for the file in the archive."""
        test_file = tmp_path / "my_design.gds"
        test_file.write_bytes(b"content")

        with create_tar_archive(test_file, arcname="custom_name.gds") as tar_stream:
            tar_stream.seek(0)
            with tarfile.open(fileobj=tar_stream, mode="r") as tar:
                members = tar.getnames()
                assert members[0] == "custom_name.gds"

    def test_preserves_file_content(self, tmp_path: Path) -> None:
        """Archived file contains the correct content."""
        test_file = tmp_path / "test.gds"
        test_content = b"important design data"
        test_file.write_bytes(test_content)

        with create_tar_archive(test_file) as tar_stream:
            tar_stream.seek(0)
            with tarfile.open(fileobj=tar_stream, mode="r") as tar:
                extracted = tar.extractfile("design.gds")
                assert extracted is not None
                assert extracted.read() == test_content

    def test_accepts_string_path(self, tmp_path: Path) -> None:
        """Accepts a string path argument."""
        test_file = tmp_path / "test.gds"
        test_file.write_bytes(b"content")

        # Pass as string instead of Path
        with create_tar_archive(str(test_file)) as tar_stream:
            tar_stream.seek(0)
            with tarfile.open(fileobj=tar_stream, mode="r") as tar:
                assert len(tar.getnames()) == 1

    def test_stream_is_seeked_to_start(self, tmp_path: Path) -> None:
        """Returned stream is seeked to position 0."""
        test_file = tmp_path / "test.gds"
        test_file.write_bytes(b"content")

        with create_tar_archive(test_file) as tar_stream:
            # Should be able to read immediately without seeking
            assert tar_stream.tell() == 0
            assert tar_stream.read(5) != b""

    def test_cleans_up_temp_file(self, tmp_path: Path) -> None:
        """Temp file is cleaned up after context manager exits."""
        test_file = tmp_path / "test.gds"
        test_file.write_bytes(b"content")

        # Capture the temp file path
        temp_path = None
        with create_tar_archive(test_file) as tar_stream:
            temp_path = Path(tar_stream.name)
            assert temp_path.exists()

        # After context exit, temp file should be deleted
        assert temp_path is not None
        assert not temp_path.exists()


class TestStreamArchiveToFile:
    """Test stream_archive_to_file function."""

    def test_extracts_archive_from_container(self, tmp_path: Path) -> None:
        """Extracts archive from container and writes to file."""
        # Create mock container that returns tar data
        test_content = b"test file content"
        mock_container = MagicMock()
        mock_container.get_archive.return_value = (iter([test_content]), {})

        output_path = tmp_path / "output.tar"
        logger = logging.getLogger(__name__)

        result = stream_archive_to_file(
            mock_container, "/workspace/test.txt", output_path, logger
        )

        assert result is not None
        bytes_written, checksums = result
        assert bytes_written == len(test_content)
        assert "sha256" in checksums
        assert output_path.exists()
        assert output_path.read_bytes() == test_content

    def test_returns_checksum(self, tmp_path: Path) -> None:
        """Returns SHA256 checksum of extracted data."""
        test_content = b"checksum test content"
        expected_sha256 = hashlib.sha256(test_content).hexdigest()

        mock_container = MagicMock()
        mock_container.get_archive.return_value = (iter([test_content]), {})

        output_path = tmp_path / "output.tar"
        logger = logging.getLogger(__name__)

        result = stream_archive_to_file(
            mock_container, "/workspace/test.txt", output_path, logger
        )

        assert result is not None
        _bytes_written, checksums = result
        assert checksums["sha256"] == expected_sha256

    def test_compresses_when_requested(self, tmp_path: Path) -> None:
        """Compresses output with gzip when compress=True."""
        test_content = b"x" * 1000  # Compressible content
        mock_container = MagicMock()
        mock_container.get_archive.return_value = (iter([test_content]), {})

        output_path = tmp_path / "output.tar.gz"
        logger = logging.getLogger(__name__)

        result = stream_archive_to_file(
            mock_container,
            "/workspace/test.txt",
            output_path,
            logger,
            compress=True,
        )

        assert result is not None
        assert output_path.exists()
        # Verify it's gzip compressed
        with gzip.open(output_path, "rb") as f:
            decompressed = f.read()
        assert decompressed == test_content

    def test_returns_none_for_missing_path(self, tmp_path: Path) -> None:
        """Returns None if container path doesn't exist."""
        mock_container = MagicMock()
        mock_container.get_archive.side_effect = docker.errors.NotFound("not found")

        output_path = tmp_path / "output.tar"
        logger = logging.getLogger(__name__)

        result = stream_archive_to_file(
            mock_container, "/nonexistent/path", output_path, logger
        )

        assert result is None
        assert not output_path.exists()

    def test_cleans_up_temp_file_on_failure(self, tmp_path: Path) -> None:
        """Cleans up temp file if extraction fails mid-stream."""

        # Create a generator that fails mid-stream
        def failing_generator() -> Iterator[bytes]:
            yield b"partial data"
            msg = "connection lost"
            raise docker.errors.DockerException(msg)

        mock_container = MagicMock()
        mock_container.get_archive.return_value = (failing_generator(), {})

        output_path = tmp_path / "output.tar"
        logger = logging.getLogger(__name__)

        with contextlib.suppress(docker.errors.DockerException):
            stream_archive_to_file(
                mock_container, "/workspace/test.txt", output_path, logger
            )

        # Temp file should be cleaned up
        temp_path = output_path.with_suffix(".tar.tmp")
        assert not temp_path.exists()


class TestStreamContainerDiffToFile:
    """Test stream_container_diff_to_file function."""

    def test_exports_container_filesystem(self, tmp_path: Path) -> None:
        """Exports container filesystem to compressed tarball."""
        test_content = b"container filesystem data"
        mock_container = MagicMock()
        mock_container.export.return_value = iter([test_content])

        output_path = tmp_path / "layer.tar.gz"
        logger = logging.getLogger(__name__)

        result = stream_container_diff_to_file(mock_container, output_path, logger)

        assert result is not None
        bytes_written, checksums = result
        assert bytes_written > 0
        assert "sha256" in checksums
        assert output_path.exists()

        # Verify it's gzip compressed
        with gzip.open(output_path, "rb") as f:
            decompressed = f.read()
        assert decompressed == test_content

    def test_returns_none_on_export_failure(self, tmp_path: Path) -> None:
        """Returns None if container export fails."""
        mock_container = MagicMock()
        mock_container.export.side_effect = docker.errors.DockerException("failed")

        output_path = tmp_path / "layer.tar.gz"
        logger = logging.getLogger(__name__)

        result = stream_container_diff_to_file(mock_container, output_path, logger)

        assert result is None
        assert not output_path.exists()

    def test_calculates_checksum_of_compressed_file(self, tmp_path: Path) -> None:
        """Calculates checksum of the compressed output file."""
        test_content = b"test data for checksum"
        mock_container = MagicMock()
        mock_container.export.return_value = iter([test_content])

        output_path = tmp_path / "layer.tar.gz"
        logger = logging.getLogger(__name__)

        result = stream_container_diff_to_file(mock_container, output_path, logger)

        assert result is not None
        bytes_written, checksums = result

        # Verify checksum matches actual file
        actual_sha256 = hashlib.sha256(output_path.read_bytes()).hexdigest()
        assert checksums["sha256"] == actual_sha256
        assert bytes_written == output_path.stat().st_size
