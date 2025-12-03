"""Tests for precheck log parser."""

from wafer_space.projects.precheck_parser import PrecheckLogParser
from wafer_space.projects.precheck_parser import classify_failure


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


class TestClassifyFailure:
    """Test error classification."""

    def test_classify_success(self):
        """Test that exit code 0 is success."""
        result = classify_failure("Some output", exit_code=0)
        assert result == "success"

    def test_classify_system_error_traceback(self):
        """Test system error detection via traceback."""
        logs = (
            "Error: The precheck failed with the following exception:\n"
            "Traceback (most recent call last):"
        )
        result = classify_failure(logs, exit_code=1)
        assert result == "system"

    def test_classify_system_error_memory(self):
        """Test system error detection via MemoryError."""
        logs = "MemoryError: cannot allocate memory"
        result = classify_failure(logs, exit_code=1)
        assert result == "system"

    def test_classify_design_error_default(self):
        """Test design error as default for exit 1."""
        logs = "DRC violation at layer metal1"
        result = classify_failure(logs, exit_code=1)
        assert result == "design"

    def test_classify_deferred_drc_errors_as_design(self):
        """Test deferred DRC errors classified as design, not system.

        This is a critical fix: when precheck runs DRC checks and finds violations
        through the "deferred errors" mechanism, it outputs an exception pattern
        that looks like a system error but is actually a design error.
        See GitHub issue #146.
        """
        logs = """
[11:19:06] ERROR    6 KLayout DRC errors found. - deferred
PrecheckFlow - Stage 13 - Write the layout ━━━━━━━━━ 13/13 1:27:46
Error: The precheck failed with the following exception:
One or more deferred errors were encountered:
18 Magic DRC errors found.
6 KLayout DRC errors found.


=== SYSTEM ERROR - See error_message field ===
"""
        result = classify_failure(logs, exit_code=1)
        # Must be "design" not "system" - DRC errors are user-fixable
        assert result == "design"

    def test_classify_real_system_error_with_traceback(self):
        """Test that real system errors with tracebacks are still caught."""
        logs = """
Error: The precheck failed with the following exception:
Traceback (most recent call last):
  File "/app/precheck.py", line 100, in run
    raise RuntimeError("Docker container failed")
RuntimeError: Docker container failed
"""
        result = classify_failure(logs, exit_code=1)
        # Real exception with traceback should still be system error
        assert result == "system"


class TestParseDeferredDRCErrors:
    """Test parsing of deferred DRC errors."""

    def test_parse_deferred_drc_errors_extracts_counts(self):
        """Test that DRC error counts are extracted from deferred errors."""
        logs = """
[11:19:06] ERROR    6 KLayout DRC errors found. - deferred
PrecheckFlow - Stage 13 - Write the layout ━━━━━━━━━ 13/13 1:27:46
Error: The precheck failed with the following exception:
One or more deferred errors were encountered:
18 Magic DRC errors found.
6 KLayout DRC errors found.


=== SYSTEM ERROR - See error_message field ===
"""
        result = PrecheckLogParser.parse_logs(logs, exit_code=1)

        assert result["success"] is False

        # Check error messages contain the counts (should have Magic + KLayout)
        messages = [e["message"] for e in result["errors"]]
        has_magic = any("18" in m and "Magic" in m for m in messages)
        has_klayout = any("6" in m and "KLayout" in m for m in messages)
        assert has_magic, f"Missing Magic DRC error in: {messages}"
        assert has_klayout, f"Missing KLayout DRC error in: {messages}"

        # Check category is DRC
        categories = [e["category"] for e in result["errors"]]
        assert all(c == "DRC" for c in categories)

    def test_parse_single_drc_error_type(self):
        """Test parsing when only one type of DRC error is present."""
        logs = """
One or more deferred errors were encountered:
5 Magic DRC errors found.
"""
        result = PrecheckLogParser.parse_logs(logs, exit_code=1)

        assert result["success"] is False
        assert len(result["errors"]) == 1
        assert "5" in result["errors"][0]["message"]
        assert "Magic" in result["errors"][0]["message"]
        assert result["errors"][0]["category"] == "DRC"

    def test_parse_singular_drc_error(self):
        """Test parsing singular 'error' vs plural 'errors'."""
        logs = """
One or more deferred errors were encountered:
1 Magic DRC error found.
"""
        result = PrecheckLogParser.parse_logs(logs, exit_code=1)

        assert len(result["errors"]) == 1
        assert "1" in result["errors"][0]["message"]
