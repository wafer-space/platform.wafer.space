"""Parser for gf180mcu-precheck log output.

This is a Phase 1 minimal implementation designed to evolve as we learn
the actual output format from real precheck runs.

TODO: Update patterns after running real precheck tests with sample GDS files.
"""

import re
from typing import TypedDict


class ErrorDict(TypedDict):
    """Error information dictionary."""

    message: str
    line: int
    category: str


class ParseResult(TypedDict):
    """Result of parsing precheck logs."""

    success: bool
    errors: list[ErrorDict]
    warnings: list[dict]
    raw_output: str
    detected_checks: list[str]


# Pattern for deferred DRC errors (design errors, NOT system errors)
# Matches output like: One or more deferred errors were encountered...
DEFERRED_ERRORS_PATTERN = re.compile(
    r"One or more deferred errors were encountered:",
    re.IGNORECASE,
)

# Pattern to extract DRC error counts from deferred errors.
# NOTE: This pattern uses capture groups to EXTRACT count and tool name.
# The tool-specific patterns below are for DETECTION only (no capture needed).
# They're intentionally separate - consolidating would add complexity without benefit.
DRC_ERROR_PATTERN = re.compile(
    r"(\d+)\s+(Magic|KLayout)\s+DRC\s+errors?\s+found",
    re.IGNORECASE,
)

# DRC completion patterns - each tool must have ONE of these to be "complete"
# Matches error counts like "18 Magic DRC errors found."
# NOTE: Precheck never outputs "0 errors found" - it uses "clear" message instead.
MAGIC_DRC_ERRORS_PATTERN = re.compile(
    r"\d+\s+Magic\s+DRC\s+errors?\s+found",
    re.IGNORECASE,
)
KLAYOUT_DRC_ERRORS_PATTERN = re.compile(
    r"\d+\s+KLayout\s+DRC\s+errors?\s+found",
    re.IGNORECASE,
)

# Matches success messages like "Check for Magic DRC errors clear."
MAGIC_DRC_CLEAR_PATTERN = re.compile(
    r"Check\s+for\s+Magic\s+DRC\s+errors\s+clear",
    re.IGNORECASE,
)
KLAYOUT_DRC_CLEAR_PATTERN = re.compile(
    r"Check\s+for\s+KLayout\s+DRC\s+errors\s+clear",
    re.IGNORECASE,
)

# DRC incomplete patterns - these indicate a tool didn't run properly
MAGIC_DRC_INCOMPLETE_PATTERNS = [
    re.compile(r"Magic\s+DRC\s+errors\s+metric\s+was\s+not\s+found", re.IGNORECASE),
    re.compile(
        r"Threshold\s+for\s+Magic\s+DRC\s+errors\s+is\s+not\s+set", re.IGNORECASE
    ),
]
KLAYOUT_DRC_INCOMPLETE_PATTERNS = [
    re.compile(r"KLayout\s+DRC\s+errors\s+metric\s+was\s+not\s+found", re.IGNORECASE),
    re.compile(
        r"Threshold\s+for\s+KLayout\s+DRC\s+errors\s+is\s+not\s+set", re.IGNORECASE
    ),
]


def has_drc_result(logs: str, tool: str) -> bool:
    """Check if a DRC tool has reported a result (errors or clear).

    Args:
        logs: Raw output from precheck
        tool: Either "magic" or "klayout"

    Returns:
        True if the tool reported either errors or clear, False otherwise.
    """
    if tool.lower() == "magic":
        errors_pattern = MAGIC_DRC_ERRORS_PATTERN
        clear_pattern = MAGIC_DRC_CLEAR_PATTERN
        incomplete_patterns = MAGIC_DRC_INCOMPLETE_PATTERNS
    elif tool.lower() == "klayout":
        errors_pattern = KLAYOUT_DRC_ERRORS_PATTERN
        clear_pattern = KLAYOUT_DRC_CLEAR_PATTERN
        incomplete_patterns = KLAYOUT_DRC_INCOMPLETE_PATTERNS
    else:
        msg = f"Invalid tool name: {tool}. Must be 'magic' or 'klayout'"
        raise ValueError(msg)

    # Check for incomplete indicators first - these mean the tool didn't run
    for pattern in incomplete_patterns:
        if pattern.search(logs):
            return False

    # Check for either errors or clear
    return bool(errors_pattern.search(logs) or clear_pattern.search(logs))


def both_drc_tools_completed(logs: str) -> bool:
    """Check if both Magic and KLayout DRC tools reported results.

    Args:
        logs: Raw output from precheck

    Returns:
        True if both tools reported either errors or clear, False otherwise.
    """
    return has_drc_result(logs, "magic") and has_drc_result(logs, "klayout")


def classify_failure(logs: str, exit_code: int) -> str:
    """Classify failure as 'system', 'design', or 'success'.

    The precheck is only considered successfully completed if ALL of:
    1. exit_code == 0
    2. "Precheck successfully completed." message in logs
    3. BOTH Magic AND KLayout DRC tools reported results

    If any of these are missing, it's either a system error (precheck didn't
    complete) or a design error (DRC found issues).

    Args:
        logs: Raw output from precheck
        exit_code: Process exit code

    Returns:
        'success' if all evidence present
        'system' if infrastructure failure (should retry) or precheck incomplete
        'design' if user's design has errors (no retry)
    """
    has_success_message = "Precheck successfully completed." in logs
    drc_tools_complete = both_drc_tools_completed(logs)

    # Success requires ALL: exit_code == 0 AND success message AND both DRC tools
    if exit_code == 0 and has_success_message and drc_tools_complete:
        return "success"

    # Check if both DRC tools completed - if not, it's a system error
    # Both Magic AND KLayout must report either "errors found" or "clear"
    if not drc_tools_complete:
        return "system"

    # exit_code == 0 but missing success message means incomplete - system error
    if exit_code == 0 and not has_success_message:
        return "system"

    # Both DRC tools reported results with exit_code != 0
    # → at least one tool has errors → design error
    return "design"


class PrecheckLogParser:
    """Parse gf180mcu-precheck output into structured errors/warnings."""

    @classmethod
    def parse_logs(cls, logs: str, exit_code: int) -> ParseResult:
        """Parse precheck logs - requires positive evidence of success.

        Success requires ALL of the following:
        1. exit_code == 0
        2. "Precheck successfully completed." message in logs
        3. Both Magic AND KLayout DRC tools reported results (errors or clear)

        This prevents false positives when:
        - Container never ran (exit_code defaults to 0)
        - Container exited cleanly but didn't complete checks
        - Logs are empty or missing
        - Only partial checks ran

        Args:
            logs: Raw output from precheck.py
            exit_code: Process exit code (0 = success, 1 = failure)

        Returns:
            dict with keys:
                - success: bool (based on exit code AND positive evidence)
                - errors: list of error dicts
                - warnings: list of warning dicts
                - raw_output: original logs
                - detected_checks: list of detected check names (TODO)
        """
        errors: list[ErrorDict] = []
        warnings: list[dict] = []
        detected_checks: list[str] = []

        # Check for explicit success message
        has_success_message = "Precheck successfully completed." in logs

        # Check for DRC tool completion - both tools must report results
        drc_tools_complete = both_drc_tools_completed(logs)

        # Success requires ALL: exit_code == 0 AND success message AND both DRC tools
        is_success = exit_code == 0 and has_success_message and drc_tools_complete

        if is_success:
            return ParseResult(
                success=True,
                errors=errors,
                warnings=warnings,
                raw_output=logs,
                detected_checks=detected_checks,
            )

        # Check for deferred DRC errors first - extract individual DRC counts
        if DEFERRED_ERRORS_PATTERN.search(logs):
            drc_matches = DRC_ERROR_PATTERN.findall(logs)
            for count, tool in drc_matches:
                errors.append(
                    ErrorDict(
                        message=f"{count} {tool} DRC errors found",
                        line=0,
                        category="DRC",
                    )
                )

        # Also collect generic "Error:" lines (in addition to any DRC errors found)
        for line_num, line in enumerate(logs.split("\n"), 1):
            if line.strip().startswith("Error:"):
                errors.append(
                    ErrorDict(
                        message=line.strip(),
                        line=line_num,
                        category="Unknown",
                    )
                )

        # If not successful and no errors found, add appropriate error message
        if not is_success and not errors:
            if exit_code != 0:
                errors.append(
                    ErrorDict(
                        message="Precheck failed - see full logs for details",
                        line=0,
                        category="System",
                    )
                )
            else:
                # exit_code == 0 but missing required evidence - build specific message
                missing = []
                if not has_success_message:
                    missing.append("no success message")
                if not drc_tools_complete:
                    missing.append("DRC tools did not report results")
                errors.append(
                    ErrorDict(
                        message=f"Precheck did not complete - {' and '.join(missing)}",
                        line=0,
                        category="System",
                    )
                )

        return ParseResult(
            success=is_success,
            errors=errors,
            warnings=warnings,
            raw_output=logs,
            detected_checks=detected_checks,
        )
