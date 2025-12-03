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


# System error patterns (infrastructure failures that should retry)
SYSTEM_ERROR_PATTERNS = [
    r"Error: The precheck failed with the following exception:",
    r"Traceback \(most recent call last\):",
    r"MemoryError",
    r"TimeoutError",
    r"Docker.*error",
    r"Container.*failed",
]

# Pattern for deferred DRC errors (design errors, NOT system errors)
# Matches output like: One or more deferred errors were encountered...
DEFERRED_ERRORS_PATTERN = re.compile(
    r"One or more deferred errors were encountered:",
    re.IGNORECASE,
)

# Pattern to extract DRC error counts from deferred errors
DRC_ERROR_PATTERN = re.compile(
    r"(\d+)\s+(Magic|KLayout)\s+DRC\s+errors?\s+found",
    re.IGNORECASE,
)


def classify_failure(logs: str, exit_code: int) -> str:
    """Classify failure as 'system', 'design', or 'success'.

    Args:
        logs: Raw output from precheck
        exit_code: Process exit code

    Returns:
        'success' if exit code 0
        'system' if infrastructure failure (should retry)
        'design' if user's design has errors (no retry)
    """
    if exit_code == 0:
        return "success"

    # Check for deferred DRC errors FIRST - these look like system errors
    # but are actually design errors (DRC violations from Magic/KLayout tools)
    if DEFERRED_ERRORS_PATTERN.search(logs):
        return "design"

    # Check for system error patterns
    for pattern in SYSTEM_ERROR_PATTERNS:
        if re.search(pattern, logs, re.IGNORECASE):
            return "system"

    # Default to design error (user must fix)
    return "design"


class PrecheckLogParser:
    """Parse gf180mcu-precheck output into structured errors/warnings."""

    @classmethod
    def parse_logs(cls, logs: str, exit_code: int) -> ParseResult:
        """Parse precheck logs - conservative initial implementation.

        Args:
            logs: Raw output from precheck.py
            exit_code: Process exit code (0 = success, 1 = failure)

        Returns:
            dict with keys:
                - success: bool (based on exit code and output)
                - errors: list of error dicts
                - warnings: list of warning dicts
                - raw_output: original logs
                - detected_checks: list of detected check names (TODO)
        """
        errors: list[ErrorDict] = []
        warnings: list[dict] = []
        detected_checks: list[str] = []

        # Simple success detection
        if "Precheck successfully completed." in logs:
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

        # Simple error detection - find "Error:" lines (skip if we found DRC errors)
        if not errors:
            for line_num, line in enumerate(logs.split("\n"), 1):
                if line.strip().startswith("Error:"):
                    errors.append(
                        ErrorDict(
                            message=line.strip(),
                            line=line_num,
                            category="Unknown",
                        )
                    )

        # If exit code != 0 but no errors found, treat whole output as error
        if exit_code != 0 and not errors:
            errors.append(
                ErrorDict(
                    message="Precheck failed - see full logs for details",
                    line=0,
                    category="System",
                )
            )

        return ParseResult(
            success=exit_code == 0,
            errors=errors,
            warnings=warnings,
            raw_output=logs,
            detected_checks=detected_checks,
        )
