"""Tests for Docker utility functions."""

from __future__ import annotations

import tarfile
from typing import TYPE_CHECKING

from wafer_space.projects.docker_utils import create_tar_archive
from wafer_space.projects.docker_utils import parse_docker_timestamp_float
from wafer_space.projects.docker_utils import strip_docker_timestamps

if TYPE_CHECKING:
    from pathlib import Path


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
    """Test create_tar_archive function."""

    def test_creates_valid_tar_archive(self, tmp_path: Path) -> None:
        """Creates a valid tar archive from a file."""
        # Create a test file
        test_file = tmp_path / "test.gds"
        test_content = b"test file content"
        test_file.write_bytes(test_content)

        # Create the archive
        tar_stream = create_tar_archive(test_file)

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

        tar_stream = create_tar_archive(test_file, arcname="custom_name.gds")

        tar_stream.seek(0)
        with tarfile.open(fileobj=tar_stream, mode="r") as tar:
            members = tar.getnames()
            assert members[0] == "custom_name.gds"

    def test_preserves_file_content(self, tmp_path: Path) -> None:
        """Archived file contains the correct content."""
        test_file = tmp_path / "test.gds"
        test_content = b"important design data"
        test_file.write_bytes(test_content)

        tar_stream = create_tar_archive(test_file)

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
        tar_stream = create_tar_archive(str(test_file))

        tar_stream.seek(0)
        with tarfile.open(fileobj=tar_stream, mode="r") as tar:
            assert len(tar.getnames()) == 1

    def test_stream_is_seeked_to_start(self, tmp_path: Path) -> None:
        """Returned stream is seeked to position 0."""
        test_file = tmp_path / "test.gds"
        test_file.write_bytes(b"content")

        tar_stream = create_tar_archive(test_file)

        # Should be able to read immediately without seeking
        assert tar_stream.tell() == 0
        assert tar_stream.read(5) != b""
