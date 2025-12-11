"""Operations for creating and managing manufacturability checks.

This module provides functions for check lifecycle operations like
retry creation. It sits between models and services to avoid circular imports.

Import hierarchy:
- check_operations -> models, exceptions
- services -> models, tasks, check_operations
- tasks -> models, exceptions, check_operations
"""

from __future__ import annotations

from .exceptions import MaxRetriesExceededError
from .models import ManufacturabilityCheck

# Maximum retry attempts for manufacturability checks
MAX_MANUFACTURABILITY_CHECK_RETRIES = 3


def create_retry_check(
    failed_check: ManufacturabilityCheck,
) -> ManufacturabilityCheck:
    """Create a new check as a retry of a failed one.

    Args:
        failed_check: The check that failed (must be in ERROR status)

    Returns:
        New ManufacturabilityCheck in PENDING status

    Raises:
        ValueError: If failed_check is not in ERROR status
        MaxRetriesExceededError: If retry limit reached
    """
    if failed_check.status != ManufacturabilityCheck.Status.ERROR:
        msg = f"Can only retry ERROR checks, not {failed_check.status}"
        raise ValueError(msg)

    # Find original check (handles both first retry and subsequent)
    original = failed_check.parent_check or failed_check

    # Check retry limit
    retry_count = original.retry_checks.count()
    if retry_count >= MAX_MANUFACTURABILITY_CHECK_RETRIES:
        raise MaxRetriesExceededError(
            retry_count=retry_count,
            max_retries=MAX_MANUFACTURABILITY_CHECK_RETRIES,
        )

    return ManufacturabilityCheck.objects.create(
        project=original.project,
        project_file=original.project_file,
        trigger_reason=ManufacturabilityCheck.TriggerReason.RETRY,
        parent_check=original,
    )
