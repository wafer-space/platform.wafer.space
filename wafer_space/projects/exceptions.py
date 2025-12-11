"""Exceptions for the projects app."""

from __future__ import annotations


class MaxRetriesExceededError(Exception):
    """Raised when a check has exceeded its maximum retry limit.

    Attributes:
        retry_count: Current number of retries attempted
        max_retries: Maximum retries allowed
    """

    def __init__(self, retry_count: int, max_retries: int) -> None:
        self.retry_count = retry_count
        self.max_retries = max_retries
        msg = (
            f"Cannot retry: maximum retry limit ({max_retries}) reached "
            f"(current retry_count: {retry_count})"
        )
        super().__init__(msg)


class ConcurrentLimitError(Exception):
    """Raised when the concurrent check limit would be exceeded.

    Attributes:
        active_count: Current number of active checks
        max_concurrent: Maximum concurrent checks allowed
    """

    def __init__(self, active_count: int, max_concurrent: int) -> None:
        self.active_count = active_count
        self.max_concurrent = max_concurrent
        msg = (
            f"Cannot dispatch: concurrent limit ({max_concurrent}) "
            f"reached ({active_count} checks already active)"
        )
        super().__init__(msg)


class InvalidStateTransitionError(Exception):
    """Raised when an invalid state transition is attempted.

    Attributes:
        from_status: The current status
        to_status: The attempted new status
        model_name: Name of the model (for error messages)
    """

    def __init__(
        self,
        from_status: str,
        to_status: str,
        model_name: str = "ManufacturabilityCheck",
    ) -> None:
        self.from_status = from_status
        self.to_status = to_status
        self.model_name = model_name
        msg = (
            f"Invalid {model_name} state transition: "
            f"cannot transition from {from_status} to {to_status}"
        )
        super().__init__(msg)


class TaskExecutionError(Exception):
    """Raised when a task execution step fails.

    Used internally to signal errors during task processing,
    allowing centralized error handling with consistent return format.

    Attributes:
        reason: Short identifier for the error type (e.g., "unknown_server")
        message: Human-readable error message for logging
    """

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        self.message = message
        super().__init__(message)
