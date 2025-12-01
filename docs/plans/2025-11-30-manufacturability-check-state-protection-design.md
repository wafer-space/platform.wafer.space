# Manufacturability Check State Protection Design

**Issue:** [#121 - Cancelled manufacturability checks get restarted when failure state overrides cancellation](https://github.com/wafer-space/platform.wafer.space/issues/121)

**Date:** 2025-11-30

**Status:** Approved

## Problem Statement

Cancelled manufacturability checks are being restarted because the cancelled state gets overridden. The current `queue_check()` method unconditionally resets checks to QUEUED, ignoring terminal states like CANCELLED and COMPLETED.

### Root Causes

1. **Mixed responsibilities**: `queue_check()` does creation, re-queueing, retrying, and Celery dispatch all in one method
2. **No state transition validation**: Nothing prevents invalid transitions (e.g., CANCELLED → QUEUED)
3. **Confusing naming**: "check", "task", "run" are used interchangeably for both the database record and the Celery job
4. **Broken retry tracking**: `retry_count` is reset to 0 on every re-queue, so retries aren't actually limited

## Solution Overview

### 1. Clear Terminology

| Term | Meaning |
|------|---------|
| **Check** | The `ManufacturabilityCheck` database record |
| **Job** | The Celery background execution |
| **Analysis** | The actual manufacturability analysis work |

**Rule**: Never use "task", "run", or "check" to refer to the Celery job.

### 2. State Definitions

| State | Meaning |
|-------|---------|
| `PENDING` | Check created, waiting for capacity to dispatch to Celery |
| `DISPATCHED` | Job sent to Celery queue, waiting for worker to pick it up |
| `RUNNING` | Celery worker is executing the analysis |
| `FINISHED` | Analysis completed successfully (design may or may not be manufacturable) |
| `ERROR` | Celery job failed (crashed, timed out, orphaned) |
| `CANCELLED` | User cancelled (terminal, cannot be re-queued) |

### 3. State Machine

```python
ALLOWED_TRANSITIONS: ClassVar[dict[Status, set[Status]]] = {
    Status.PENDING:    {Status.DISPATCHED, Status.ERROR, Status.CANCELLED},
    Status.DISPATCHED: {Status.RUNNING, Status.ERROR, Status.CANCELLED},
    Status.RUNNING:    {Status.FINISHED, Status.ERROR, Status.CANCELLED},
    Status.FINISHED:   set(),  # Terminal
    Status.ERROR:      {Status.PENDING},  # Can retry (with limit of 3)
    Status.CANCELLED:  set(),  # Terminal
}
```

```text
                              ┌─────────────┐
                              │   PENDING   │◄────────────────┐
                              └──────┬──────┘                 │
                                     │ (2. Scheduler)         │
                                     ▼                        │
                              ┌─────────────┐                 │
                              │ DISPATCHED  │                 │
                              └──────┬──────┘                 │
                                     │ (3. Job Start)         │ (7. Retry)
                                     ▼                        │
                              ┌─────────────┐                 │
                              │   RUNNING   │                 │
                              └──────┬──────┘                 │
                       ┌─────────────┼─────────────┐          │
                       │             │             │          │
                (4. Success)   (5. Error)    (6. Watchdog)    │
                       │             │             │          │
                       ▼             ▼             ▼          │
                ┌───────────┐ ┌─────────────┐                 │
                │ FINISHED  │ │    ERROR    │─────────────────┘
                └───────────┘ └─────────────┘

From PENDING/DISPATCHED/RUNNING:
    └──────────────────────────────────► CANCELLED (8. User Cancel)
```

## The 8 Pathways

Each pathway has exactly ONE responsibility and is the ONLY place that performs its specific state transition.

### Pathway 1: Creation

| Aspect | Detail |
|--------|--------|
| **Trigger** | File download completes and passes verification |
| **Where** | `_create_manufacturability_check()` in tasks.py |
| **Transition** | None → PENDING |
| **Data Set** | `status=PENDING`, `project`, `project_file` |

### Pathway 2: Scheduler

| Aspect | Detail |
|--------|--------|
| **Trigger** | Periodic Celery beat task |
| **Where** | `_handle_pending_checks()` in tasks.py |
| **Transition** | PENDING → DISPATCHED |
| **Data Set** | `status`, `celery_job_id`, `celery_job_dispatched_at` |
| **Preconditions** | Concurrent limit not exceeded |

### Pathway 3: Job Start

| Aspect | Detail |
|--------|--------|
| **Trigger** | Celery worker picks up job |
| **Where** | `celery_job_run()` in tasks.py |
| **Transition** | DISPATCHED → RUNNING |
| **Data Set** | `status`, `celery_worker_pid`, `celery_worker_hostname`, `docker_container_id`, `docker_container_started_at`, `celery_job_started_at` |

### Pathway 4: Success

| Aspect | Detail |
|--------|--------|
| **Trigger** | Analysis completes without system errors |
| **Where** | `celery_job_run()` success path |
| **Transition** | RUNNING → FINISHED |
| **Data Set** | `status`, `is_manufacturable`, `errors`, `warnings`, `processing_logs`, `celery_job_finished_at` |

### Pathway 5: Error (Job Failure)

| Aspect | Detail |
|--------|--------|
| **Trigger** | System/processing failure |
| **Where** | `celery_job_run()` exception handler |
| **Transition** | PENDING/DISPATCHED/RUNNING → ERROR |
| **Data Set** | `status`, `error_message`, `processing_logs`, `celery_job_finished_at` |

### Pathway 6: Watchdog

| Aspect | Detail |
|--------|--------|
| **Trigger** | Periodic task detects orphaned checks |
| **Where** | `_handle_dispatched_checks()`, `_handle_running_checks()` |
| **Transition** | DISPATCHED/RUNNING → ERROR |
| **Conditions** | Job not in Celery queue, worker dead, container dead, timeout |
| **Data Set** | `status`, `error_message`, `celery_job_finished_at` |

### Pathway 7: Retry

| Aspect | Detail |
|--------|--------|
| **Trigger** | Periodic task finds retryable ERROR checks |
| **Where** | `_handle_error_checks()` in tasks.py |
| **Transition** | ERROR → PENDING |
| **Preconditions** | `retry_count < 3` |
| **Data Set** | `status=PENDING`, `retry_count++`, clears job/worker/docker fields |

### Pathway 8: Cancellation

| Aspect | Detail |
|--------|--------|
| **Trigger** | User clicks cancel button |
| **Where** | `ManufacturabilityService.cancel_check()` |
| **Transition** | PENDING/DISPATCHED/RUNNING → CANCELLED |
| **Data Set** | `status`, `celery_job_finished_at`, reason in logs |
| **Action** | Revoke Celery job if exists |

## Model Changes

### Field Renames

| Old Name | New Name |
|----------|----------|
| `task_id` | `celery_job_id` |
| `queued_at` | `celery_job_dispatched_at` |
| `started_at` | `celery_job_started_at` |
| `completed_at` | `celery_job_finished_at` |
| `worker_pid` | `celery_worker_pid` |
| `worker_hostname` | `celery_worker_hostname` |

### New Fields

```python
# Docker container tracking
docker_container_id = models.CharField(
    max_length=64,
    blank=True,
    default="",
    help_text="ID of Docker container running the analysis",
)
docker_container_started_at = models.DateTimeField(
    null=True,
    blank=True,
    help_text="When Docker container started",
)
```

### State Enum Changes

| Old | New |
|-----|-----|
| `QUEUED` | `PENDING` |
| `STARTING` | `DISPATCHED` |
| `PROCESSING` | `RUNNING` |
| `COMPLETED` | `FINISHED` |
| `FAILED` | `ERROR` |
| `CANCELLED` | `CANCELLED` (unchanged) |

### New Model Methods

```python
class ManufacturabilityCheck(models.Model):

    ALLOWED_TRANSITIONS: ClassVar[dict[Status, set[Status]]] = {
        Status.PENDING:    {Status.DISPATCHED, Status.ERROR, Status.CANCELLED},
        Status.DISPATCHED: {Status.RUNNING, Status.ERROR, Status.CANCELLED},
        Status.RUNNING:    {Status.FINISHED, Status.ERROR, Status.CANCELLED},
        Status.FINISHED:   set(),
        Status.ERROR:      {Status.PENDING},
        Status.CANCELLED:  set(),
    }

    def can_transition_to(self, new_status: Status) -> bool:
        """Check if transition from current status to new_status is valid."""
        return new_status in self.ALLOWED_TRANSITIONS.get(self.status, set())

    def mark_dispatched(self, *, celery_job_id: str) -> None:
        """Pathway 2: PENDING → DISPATCHED"""
        # Validates transition, sets status, celery_job_id, celery_job_dispatched_at

    def mark_running(
        self,
        *,
        celery_worker_pid: int,
        celery_worker_hostname: str,
        docker_container_id: str,
    ) -> None:
        """Pathway 3: DISPATCHED → RUNNING"""
        # Validates transition, sets status, worker info, docker info, celery_job_started_at

    def mark_finished(
        self,
        *,
        is_manufacturable: bool,
        errors: list[dict],
        warnings: list[dict],
        processing_logs: str,
    ) -> None:
        """Pathway 4: RUNNING → FINISHED"""
        # Validates transition, sets results, celery_job_finished_at

    def mark_error(self, *, error_message: str, processing_logs: str = "") -> None:
        """Pathway 5/6: → ERROR"""
        # Validates transition, sets error info, celery_job_finished_at

    def mark_cancelled(self, *, reason: str) -> str | None:
        """Pathway 8: → CANCELLED"""
        # Validates transition, sets celery_job_finished_at
        # Returns celery_job_id to revoke (if any)

    def reset_for_retry(self) -> None:
        """Pathway 7: ERROR → PENDING"""
        # Validates transition, sets status=PENDING, retry_count++
        # Clears: celery_job_*, celery_worker_*, docker_container_*, error_message
```

### Method Renames

| Old | New |
|-----|-----|
| `start_processing()` | `mark_running()` |
| `complete()` | `mark_finished()` |
| `fail()` | `mark_error()` |
| `cancel()` | `mark_cancelled()` |

## Task Changes

### Function Renames

| Old | New |
|-----|-----|
| `check_project_manufacturability()` | `celery_job_run()` |
| `_queue_manufacturability_check()` | `_create_manufacturability_check()` |
| `_handle_starting_checks()` | `_handle_dispatched_checks()` |
| `_handle_processing_checks()` | `_handle_running_checks()` |
| `_handle_failed_checks()` | `_handle_error_checks()` |
| `_handle_queued_checks()` | `_handle_pending_checks()` |

## Service Changes

### `ManufacturabilityService.queue_check()` Refactoring

The current `queue_check()` method conflates multiple pathways. It should be refactored:

**Remove:**
- Celery task dispatch (pathway 2 handles this)
- `retry_count = 0` reset (breaks retry tracking)

**Keep for admin re-run only:**
- Should only be used for explicit admin re-run requests
- Should validate state transitions
- Should NOT dispatch to Celery directly

## Files Requiring Updates

| File | Changes Required |
|------|------------------|
| `wafer_space/projects/models.py` | State enum, field renames, new methods, `ALLOWED_TRANSITIONS` |
| `wafer_space/projects/services.py` | Refactor `queue_check()`, update state references |
| `wafer_space/projects/tasks.py` | Function renames, state references, use new model methods |
| `wafer_space/projects/views.py` | Update state references |
| `wafer_space/projects/admin.py` | Update field references |
| `wafer_space/projects/tests/test_models.py` | Update for all changes |
| `wafer_space/projects/tests/test_services.py` | Update for all changes |
| `wafer_space/projects/tests/test_tasks.py` | Update for all changes |
| `wafer_space/projects/tests/test_views.py` | Update state references |
| `wafer_space/projects/tests/test_verification.py` | Update state references |
| `wafer_space/projects/tests/test_services_concurrency.py` | Update state references |
| New migration | Rename fields, migrate state values |

## Migration Strategy

1. Create migration to rename fields
2. Create data migration to update status values in existing records
3. Update all code references
4. Update tests

## Testing Requirements

- Test all valid state transitions succeed
- Test all invalid state transitions raise `InvalidStateTransitionError`
- Test CANCELLED checks cannot be re-queued
- Test FINISHED checks cannot be re-queued
- Test ERROR checks can only be retried if `retry_count < 3`
- Test retry_count increments on each retry
- Test watchdog detects orphaned checks (dead worker, dead container)
