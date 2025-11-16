"""Tests for precheck log parser."""

from wafer_space.projects.precheck_parser import PrecheckLogParser


class TestPrecheckLogParser:
    """Test precheck log parsing."""

    def test_parse_success(self):
        """Test parsing successful precheck output."""
        logs = "Precheck successfully completed."
        result = PrecheckLogParser.parse_logs(logs, exit_code=0)

        assert result["success"] is True
        assert len(result["errors"]) == 0

    def test_parse_explicit_error(self):
        """Test parsing error line."""
        logs = "Error: Multiple top cells found: cell1, cell2"
        result = PrecheckLogParser.parse_logs(logs, exit_code=1)

        assert result["success"] is False
        assert len(result["errors"]) == 1
        assert "Multiple top cells" in result["errors"][0]["message"]

    def test_parse_failure_without_error_line(self):
        """Test handling exit code 1 without explicit error."""
        logs = "Some output\nMore output"
        result = PrecheckLogParser.parse_logs(logs, exit_code=1)

        assert result["success"] is False
        assert len(result["errors"]) == 1
        assert "full logs" in result["errors"][0]["message"]

    def test_raw_output_preserved(self):
        """Test that raw output is always preserved."""
        logs = "Line 1\nLine 2\nLine 3"
        result = PrecheckLogParser.parse_logs(logs, exit_code=0)

        assert result["raw_output"] == logs
