"""Tests for Docker utility functions."""

from __future__ import annotations

import pytest

from wafer_space.projects.docker_utils import parse_docker_timestamp_float
from wafer_space.projects.docker_utils import strip_docker_timestamps
from wafer_space.projects.docker_utils import track_task
from wafer_space.projects.models import ManufacturabilityCheckTask
from wafer_space.projects.tests.factories import ManufacturabilityCheckFactory


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


class TestTrackTask:
    """Test track_task context manager."""

    @pytest.mark.django_db
    def test_deletes_task_on_success(self) -> None:
        """Task tracking row is deleted when context exits normally."""
        check = ManufacturabilityCheckFactory()
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check,
            task_id="abc123",
            task_name="do_running",
        )
        assert ManufacturabilityCheckTask.objects.filter(
            manufacturability_check=check
        ).exists()

        with track_task(check.id):
            pass  # Simulated work

        assert not ManufacturabilityCheckTask.objects.filter(
            manufacturability_check=check
        ).exists()

    @pytest.mark.django_db
    def test_deletes_task_on_exception(self) -> None:
        """Task tracking row is deleted even when exception occurs."""
        check = ManufacturabilityCheckFactory()
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check,
            task_id="abc123",
            task_name="do_running",
        )

        msg = "test error"
        with pytest.raises(ValueError, match="test error"), track_task(check.id):
            raise ValueError(msg)

        assert not ManufacturabilityCheckTask.objects.filter(
            manufacturability_check=check
        ).exists()

    @pytest.mark.django_db
    def test_handles_missing_task_gracefully(self) -> None:
        """No error if task row doesn't exist."""
        check = ManufacturabilityCheckFactory()
        # No ManufacturabilityCheckTask created

        with track_task(check.id):
            pass  # Should not raise
