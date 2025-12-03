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
        """Test system error detection via traceback.

        Note: This is classified as system error because no DRC tool results
        are present (neither Magic nor KLayout reported errors or clear).
        The traceback pattern itself doesn't drive classification - the
        absence of DRC completion does.
        """
        logs = (
            "Error: The precheck failed with the following exception:\n"
            "Traceback (most recent call last):"
        )
        result = classify_failure(logs, exit_code=1)
        assert result == "system"

    def test_classify_system_error_memory(self):
        """Test system error detection via MemoryError.

        Note: This is classified as system error because no DRC tool results
        are present (neither Magic nor KLayout reported errors or clear).
        The MemoryError pattern itself doesn't drive classification - the
        absence of DRC completion does.
        """
        logs = "MemoryError: cannot allocate memory"
        result = classify_failure(logs, exit_code=1)
        assert result == "system"

    def test_classify_system_error_when_drc_incomplete(self):
        """Test that failures without DRC results are system errors.

        If neither DRC tool (Magic/KLayout) reported results, the precheck
        didn't complete properly, so it's a system error.
        """
        logs = "DRC violation at layer metal1"
        result = classify_failure(logs, exit_code=1)
        # No Magic or KLayout DRC result = system error (precheck incomplete)
        assert result == "system"

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
        # Note: Real precheck output may contain duplicate DRC lines (once during
        # execution and again in summary), but this test uses a simplified log
        # with exactly one line per tool to verify extraction logic.
        logs = """
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

        # Check DRC errors have DRC category - exactly one per tool (Magic + KLayout)
        drc_errors = [e for e in result["errors"] if e["category"] == "DRC"]
        expected_drc_errors = 2  # One per tool: Magic + KLayout
        assert len(drc_errors) == expected_drc_errors

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


class TestDRCCompletionDetection:
    """Test DRC completion detection for both Magic and KLayout.

    The precheck is only considered complete if BOTH tools report results.
    Each tool must have either errors found OR clear message.
    """

    def test_both_tools_clear_is_success(self):
        """Both Magic and KLayout clear = success (manufacturable)."""
        logs = """
Check for Magic DRC errors clear.
Check for KLayout DRC errors clear.
Precheck successfully completed.
"""
        result = classify_failure(logs, exit_code=0)
        assert result == "success"

    def test_both_tools_have_errors_is_design_error(self):
        """Both tools have errors = design error (not manufacturable)."""
        logs = """
18 Magic DRC errors found.
6 KLayout DRC errors found.
"""
        result = classify_failure(logs, exit_code=1)
        assert result == "design"

    def test_magic_errors_klayout_clear_is_design_error(self):
        """Magic has errors, KLayout clear = design error."""
        logs = """
5 Magic DRC errors found.
Check for KLayout DRC errors clear.
"""
        result = classify_failure(logs, exit_code=1)
        assert result == "design"

    def test_magic_clear_klayout_errors_is_design_error(self):
        """Magic clear, KLayout has errors = design error."""
        logs = """
Check for Magic DRC errors clear.
3 KLayout DRC errors found.
"""
        result = classify_failure(logs, exit_code=1)
        assert result == "design"

    def test_magic_missing_is_system_error(self):
        """Only KLayout result present = system error (Magic didn't run)."""
        logs = """
Check for KLayout DRC errors clear.
Some other output here.
"""
        result = classify_failure(logs, exit_code=1)
        assert result == "system"

    def test_klayout_missing_is_system_error(self):
        """Only Magic result present = system error (KLayout didn't run)."""
        logs = """
Check for Magic DRC errors clear.
Some other output here.
"""
        result = classify_failure(logs, exit_code=1)
        assert result == "system"

    def test_both_missing_is_system_error(self):
        """Neither tool has result = system error (DRC didn't run)."""
        logs = """
Some random precheck output.
No DRC results here.
"""
        result = classify_failure(logs, exit_code=1)
        assert result == "system"

    def test_metric_not_found_is_system_error(self):
        """Metric not found message indicates system error."""
        logs = """
The Magic DRC errors metric was not found. Are you sure the relevant step was run?
Check for KLayout DRC errors clear.
"""
        result = classify_failure(logs, exit_code=1)
        assert result == "system"

    def test_threshold_not_set_is_system_error(self):
        """Threshold not set (checker skipped) = system error."""
        logs = """
Threshold for Magic DRC errors is not set. The checker will be skipped.
Check for KLayout DRC errors clear.
"""
        result = classify_failure(logs, exit_code=1)
        assert result == "system"

    def test_deferred_errors_with_both_tools_is_design_error(self):
        """Deferred errors mechanism with both tools = design error.

        This is the exact pattern from GitHub issue #146.
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
        # Both tools reported (errors), so this is a design error, not system
        assert result == "design"
