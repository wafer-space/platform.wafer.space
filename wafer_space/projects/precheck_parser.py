"""Parser for gf180mcu-precheck log output.

This is a Phase 1 minimal implementation designed to evolve as we learn
the actual output format from real precheck runs.

TODO: Update patterns after running real precheck tests with sample GDS files.
"""

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

        # Simple error detection - find "Error:" lines
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
