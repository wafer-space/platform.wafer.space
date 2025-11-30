# Manufacturability Check State Protection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prevent cancelled/completed manufacturability checks from being restarted by adding state machine validation and clear separation of concerns.

**Architecture:** Add `ALLOWED_TRANSITIONS` state machine to the model with `can_transition_to()` validation. Rename states and fields for clarity. Refactor pathways so each state transition happens in exactly one place.

**Tech Stack:** Django 5.2+, PostgreSQL, Celery, pytest

**Design Doc:** `docs/plans/2025-11-30-manufacturability-check-state-protection-design.md`

**IMPORTANT - NO BACKWARDS COMPATIBILITY:**
- Do NOT create aliases for old function/method names
- Do NOT keep old field names alongside new ones
- Delete old methods completely after adding new ones
- This ensures all code locations are found and updated
- Any missed references will cause immediate failures (good - fail fast)

---

## Phase 1: Model State Enum and Exception

### Task 1.1: Add InvalidStateTransitionError Exception

**Files:**
- Create: `wafer_space/projects/exceptions.py`
- Test: `wafer_space/projects/tests/test_exceptions.py`

**Step 1: Create exception module**

```python
# wafer_space/projects/exceptions.py
"""Exceptions for the projects app."""

from __future__ import annotations


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
```

**Step 2: Run linting**

```bash
make lint-fix && make lint && make type-check
```

**Step 3: Commit**

```bash
git add wafer_space/projects/exceptions.py
git commit -m "feat: add InvalidStateTransitionError exception"
```

---

### Task 1.2: Update Status Enum with New Names

**Files:**
- Modify: `wafer_space/projects/models.py` (lines 1030-1036)

**Step 1: Update the Status enum**

Change from:
```python
class Status(models.TextChoices):
    QUEUED = "queued", "Queued"
    STARTING = "starting", "Starting"
    PROCESSING = "processing", "Processing"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"
```

To:
```python
class Status(models.TextChoices):
    PENDING = "pending", "Pending"  # Waiting for capacity
    DISPATCHED = "dispatched", "Dispatched"  # Job sent to Celery
    RUNNING = "running", "Running"  # Celery worker executing
    FINISHED = "finished", "Finished"  # Analysis complete
    ERROR = "error", "Error"  # System/processing failure
    CANCELLED = "cancelled", "Cancelled"  # User cancelled
```

**Step 2: Update default status (line ~1054)**

Change from:
```python
default=Status.QUEUED,
```

To:
```python
default=Status.PENDING,
```

**Step 3: Run linting (will show many errors - expected)**

```bash
make lint-fix
```

Expected: Many references to old status names will cause errors. We'll fix these in subsequent tasks.

**Step 4: Commit the enum change only**

```bash
git add wafer_space/projects/models.py
git commit -m "refactor: rename ManufacturabilityCheck status enum values

QUEUED → PENDING (waiting for capacity)
STARTING → DISPATCHED (job sent to Celery)
PROCESSING → RUNNING (Celery executing)
COMPLETED → FINISHED (analysis complete)
FAILED → ERROR (system failure)
CANCELLED unchanged"
```

---

### Task 1.3: Add ALLOWED_TRANSITIONS and can_transition_to()

**Files:**
- Modify: `wafer_space/projects/models.py` (after Status enum, around line 1038)
- Test: `wafer_space/projects/tests/test_models.py`

**Step 1: Write failing tests for state transitions**

Add to `wafer_space/projects/tests/test_models.py`:

```python
class TestManufacturabilityCheckStateTransitions:
    """Tests for state machine transitions."""

    def test_can_transition_pending_to_dispatched(self):
        """PENDING can transition to DISPATCHED."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )
        assert check.can_transition_to(ManufacturabilityCheck.Status.DISPATCHED) is True

    def test_can_transition_pending_to_error(self):
        """PENDING can transition to ERROR."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )
        assert check.can_transition_to(ManufacturabilityCheck.Status.ERROR) is True

    def test_can_transition_pending_to_cancelled(self):
        """PENDING can transition to CANCELLED."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )
        assert check.can_transition_to(ManufacturabilityCheck.Status.CANCELLED) is True

    def test_cannot_transition_pending_to_running(self):
        """PENDING cannot transition directly to RUNNING."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )
        assert check.can_transition_to(ManufacturabilityCheck.Status.RUNNING) is False

    def test_cannot_transition_pending_to_finished(self):
        """PENDING cannot transition to FINISHED."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )
        assert check.can_transition_to(ManufacturabilityCheck.Status.FINISHED) is False

    def test_can_transition_dispatched_to_running(self):
        """DISPATCHED can transition to RUNNING."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.DISPATCHED
        )
        assert check.can_transition_to(ManufacturabilityCheck.Status.RUNNING) is True

    def test_can_transition_running_to_finished(self):
        """RUNNING can transition to FINISHED."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING
        )
        assert check.can_transition_to(ManufacturabilityCheck.Status.FINISHED) is True

    def test_can_transition_running_to_error(self):
        """RUNNING can transition to ERROR."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING
        )
        assert check.can_transition_to(ManufacturabilityCheck.Status.ERROR) is True

    def test_cannot_transition_finished_to_anything(self):
        """FINISHED is terminal - no transitions allowed."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.FINISHED
        )
        for status in ManufacturabilityCheck.Status:
            assert check.can_transition_to(status) is False

    def test_cannot_transition_cancelled_to_anything(self):
        """CANCELLED is terminal - no transitions allowed."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.CANCELLED
        )
        for status in ManufacturabilityCheck.Status:
            assert check.can_transition_to(status) is False

    def test_can_transition_error_to_pending(self):
        """ERROR can transition to PENDING (retry)."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.ERROR
        )
        assert check.can_transition_to(ManufacturabilityCheck.Status.PENDING) is True

    def test_cannot_transition_error_to_dispatched(self):
        """ERROR cannot transition directly to DISPATCHED."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.ERROR
        )
        assert check.can_transition_to(ManufacturabilityCheck.Status.DISPATCHED) is False
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckStateTransitions -v
```

Expected: FAIL with `AttributeError: 'ManufacturabilityCheck' object has no attribute 'can_transition_to'`

**Step 3: Add ALLOWED_TRANSITIONS and can_transition_to() to model**

Add after the Status enum in `wafer_space/projects/models.py`:

```python
from typing import ClassVar

class ManufacturabilityCheck(models.Model):
    """Track manufacturability checking process for projects."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        DISPATCHED = "dispatched", "Dispatched"
        RUNNING = "running", "Running"
        FINISHED = "finished", "Finished"
        ERROR = "error", "Error"
        CANCELLED = "cancelled", "Cancelled"

    # State machine: defines valid transitions
    # PENDING: waiting for capacity to dispatch to Celery
    # DISPATCHED: job sent to Celery, waiting for worker
    # RUNNING: Celery worker executing analysis
    # FINISHED: analysis complete (terminal)
    # ERROR: system failure, can retry
    # CANCELLED: user cancelled (terminal)
    ALLOWED_TRANSITIONS: ClassVar[dict[Status, set[Status]]] = {
        Status.PENDING: {Status.DISPATCHED, Status.ERROR, Status.CANCELLED},
        Status.DISPATCHED: {Status.RUNNING, Status.ERROR, Status.CANCELLED},
        Status.RUNNING: {Status.FINISHED, Status.ERROR, Status.CANCELLED},
        Status.FINISHED: set(),  # Terminal - no transitions
        Status.ERROR: {Status.PENDING},  # Can retry
        Status.CANCELLED: set(),  # Terminal - no transitions
    }
```

Add the method to the class (after `can_retry` method):

```python
def can_transition_to(self, new_status: Status) -> bool:
    """Check if transition from current status to new_status is valid.

    Args:
        new_status: The status to transition to

    Returns:
        True if transition is allowed, False otherwise
    """
    allowed = self.ALLOWED_TRANSITIONS.get(self.status, set())
    return new_status in allowed
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckStateTransitions -v
```

Expected: All tests PASS

**Step 5: Run full lint and type check**

```bash
make lint-fix && make lint && make type-check
```

**Step 6: Commit**

```bash
git add wafer_space/projects/models.py wafer_space/projects/tests/test_models.py
git commit -m "feat: add ALLOWED_TRANSITIONS state machine to ManufacturabilityCheck

Defines valid state transitions:
- PENDING → DISPATCHED, ERROR, CANCELLED
- DISPATCHED → RUNNING, ERROR, CANCELLED
- RUNNING → FINISHED, ERROR, CANCELLED
- FINISHED → (terminal)
- ERROR → PENDING (retry)
- CANCELLED → (terminal)"
```

---

## Phase 2: Field Renames

### Task 2.1: Rename Celery Job Fields

**Files:**
- Modify: `wafer_space/projects/models.py`

**Step 1: Rename fields in model**

Change:
```python
started_at = models.DateTimeField(null=True, blank=True)
completed_at = models.DateTimeField(null=True, blank=True)
task_id = models.CharField(max_length=100, blank=True, default="")  # Celery task ID
queued_at = models.DateTimeField(
    null=True,
    blank=True,
    help_text="When check entered/re-entered the QUEUED state",
)
```

To:
```python
celery_job_started_at = models.DateTimeField(null=True, blank=True)
celery_job_finished_at = models.DateTimeField(null=True, blank=True)
celery_job_id = models.CharField(
    max_length=100,
    blank=True,
    default="",
    help_text="ID of the Celery job processing this check",
)
celery_job_dispatched_at = models.DateTimeField(
    null=True,
    blank=True,
    help_text="When job was dispatched to Celery queue",
)
```

**Step 2: Rename worker fields**

Change:
```python
worker_pid = models.IntegerField(
    null=True,
    blank=True,
    help_text="Process ID of worker executing this check",
)
worker_hostname = models.CharField(
    max_length=255,
    blank=True,
    default="",
    help_text="Hostname of worker executing this check",
)
```

To:
```python
celery_worker_pid = models.IntegerField(
    null=True,
    blank=True,
    help_text="Process ID of Celery worker executing this check",
)
celery_worker_hostname = models.CharField(
    max_length=255,
    blank=True,
    default="",
    help_text="Hostname of Celery worker executing this check",
)
```

**Step 3: Commit model changes (migrations will be created later)**

```bash
git add wafer_space/projects/models.py
git commit -m "refactor: rename ManufacturabilityCheck fields for clarity

Field renames:
- task_id → celery_job_id
- queued_at → celery_job_dispatched_at
- started_at → celery_job_started_at
- completed_at → celery_job_finished_at
- worker_pid → celery_worker_pid
- worker_hostname → celery_worker_hostname"
```

---

### Task 2.2: Add Docker Container Tracking Fields

**Files:**
- Modify: `wafer_space/projects/models.py`

**Step 1: Add new fields after celery_worker_hostname**

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

**Step 2: Commit**

```bash
git add wafer_space/projects/models.py
git commit -m "feat: add Docker container tracking fields

New fields:
- docker_container_id: container ID for watchdog verification
- docker_container_started_at: when container started"
```

---

## Phase 3: New Model Methods

### Task 3.1: Add mark_dispatched() Method

**Files:**
- Modify: `wafer_space/projects/models.py`
- Test: `wafer_space/projects/tests/test_models.py`

**Step 1: Write failing test**

Add to test file:

```python
class TestManufacturabilityCheckMarkDispatched:
    """Tests for mark_dispatched() method."""

    def test_mark_dispatched_from_pending(self):
        """Can mark PENDING check as DISPATCHED."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )
        check.mark_dispatched(celery_job_id="test-job-123")

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.DISPATCHED
        assert check.celery_job_id == "test-job-123"
        assert check.celery_job_dispatched_at is not None

    def test_mark_dispatched_from_invalid_state_raises(self):
        """Cannot mark FINISHED check as DISPATCHED."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.FINISHED
        )
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            check.mark_dispatched(celery_job_id="test-job-123")

        assert "finished" in str(exc_info.value).lower()
        assert "dispatched" in str(exc_info.value).lower()

    def test_mark_dispatched_from_cancelled_raises(self):
        """Cannot mark CANCELLED check as DISPATCHED."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.CANCELLED
        )
        with pytest.raises(InvalidStateTransitionError):
            check.mark_dispatched(celery_job_id="test-job-123")
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckMarkDispatched -v
```

Expected: FAIL with `AttributeError`

**Step 3: Implement mark_dispatched()**

Add to model (remember to import the exception at top of models.py):

```python
from wafer_space.projects.exceptions import InvalidStateTransitionError
```

Add method:

```python
def mark_dispatched(self, *, celery_job_id: str) -> None:
    """Mark check as dispatched to Celery queue.

    Pathway 2: PENDING → DISPATCHED

    Args:
        celery_job_id: The ID returned by celery_task.delay()

    Raises:
        InvalidStateTransitionError: If transition is not allowed
    """
    if not self.can_transition_to(self.Status.DISPATCHED):
        raise InvalidStateTransitionError(
            from_status=self.status,
            to_status=self.Status.DISPATCHED,
        )

    self.status = self.Status.DISPATCHED
    self.celery_job_id = celery_job_id
    self.celery_job_dispatched_at = timezone.now()
    self.save(update_fields=["status", "celery_job_id", "celery_job_dispatched_at"])
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckMarkDispatched -v
```

**Step 5: Commit**

```bash
git add wafer_space/projects/models.py wafer_space/projects/tests/test_models.py wafer_space/projects/exceptions.py
git commit -m "feat: add mark_dispatched() method with state validation"
```

---

### Task 3.2: Add mark_running() Method

**Files:**
- Modify: `wafer_space/projects/models.py`
- Test: `wafer_space/projects/tests/test_models.py`

**Step 1: Write failing test**

```python
class TestManufacturabilityCheckMarkRunning:
    """Tests for mark_running() method."""

    def test_mark_running_from_dispatched(self):
        """Can mark DISPATCHED check as RUNNING."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.DISPATCHED
        )
        check.mark_running(
            celery_worker_pid=12345,
            celery_worker_hostname="worker-1",
            docker_container_id="abc123def456",
        )

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.RUNNING
        assert check.celery_worker_pid == 12345
        assert check.celery_worker_hostname == "worker-1"
        assert check.docker_container_id == "abc123def456"
        assert check.docker_container_started_at is not None
        assert check.celery_job_started_at is not None

    def test_mark_running_from_pending_raises(self):
        """Cannot mark PENDING check as RUNNING (must go through DISPATCHED)."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )
        with pytest.raises(InvalidStateTransitionError):
            check.mark_running(
                celery_worker_pid=12345,
                celery_worker_hostname="worker-1",
                docker_container_id="abc123",
            )

    def test_mark_running_from_cancelled_raises(self):
        """Cannot mark CANCELLED check as RUNNING."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.CANCELLED
        )
        with pytest.raises(InvalidStateTransitionError):
            check.mark_running(
                celery_worker_pid=12345,
                celery_worker_hostname="worker-1",
                docker_container_id="abc123",
            )
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckMarkRunning -v
```

**Step 3: Implement mark_running()**

```python
def mark_running(
    self,
    *,
    celery_worker_pid: int,
    celery_worker_hostname: str,
    docker_container_id: str,
) -> None:
    """Mark check as running on a Celery worker.

    Pathway 3: DISPATCHED → RUNNING

    Args:
        celery_worker_pid: Process ID from os.getpid()
        celery_worker_hostname: Hostname from socket.gethostname()
        docker_container_id: Docker container ID running the analysis

    Raises:
        InvalidStateTransitionError: If transition is not allowed
    """
    if not self.can_transition_to(self.Status.RUNNING):
        raise InvalidStateTransitionError(
            from_status=self.status,
            to_status=self.Status.RUNNING,
        )

    now = timezone.now()
    self.status = self.Status.RUNNING
    self.celery_worker_pid = celery_worker_pid
    self.celery_worker_hostname = celery_worker_hostname
    self.docker_container_id = docker_container_id
    self.docker_container_started_at = now
    self.celery_job_started_at = now
    self.save(
        update_fields=[
            "status",
            "celery_worker_pid",
            "celery_worker_hostname",
            "docker_container_id",
            "docker_container_started_at",
            "celery_job_started_at",
        ]
    )
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckMarkRunning -v
```

**Step 5: Commit**

```bash
git add wafer_space/projects/models.py wafer_space/projects/tests/test_models.py
git commit -m "feat: add mark_running() method with worker and container tracking"
```

---

### Task 3.3: Add mark_finished() Method

**Files:**
- Modify: `wafer_space/projects/models.py`
- Test: `wafer_space/projects/tests/test_models.py`

**Step 1: Write failing test**

```python
class TestManufacturabilityCheckMarkFinished:
    """Tests for mark_finished() method."""

    def test_mark_finished_manufacturable(self):
        """Can mark RUNNING check as FINISHED with manufacturable result."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING
        )
        check.mark_finished(
            is_manufacturable=True,
            errors=[],
            warnings=[{"type": "warning", "message": "Minor issue"}],
            processing_logs="All checks passed",
        )

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.FINISHED
        assert check.is_manufacturable is True
        assert check.errors == []
        assert len(check.warnings) == 1
        assert check.processing_logs == "All checks passed"
        assert check.celery_job_finished_at is not None

    def test_mark_finished_not_manufacturable(self):
        """Can mark RUNNING check as FINISHED with not manufacturable result."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING
        )
        check.mark_finished(
            is_manufacturable=False,
            errors=[{"type": "error", "message": "DRC violation"}],
            warnings=[],
            processing_logs="Check failed",
        )

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.FINISHED
        assert check.is_manufacturable is False
        assert len(check.errors) == 1

    def test_mark_finished_updates_project_status(self):
        """mark_finished updates the parent project status."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING
        )
        project = check.project

        check.mark_finished(
            is_manufacturable=True,
            errors=[],
            warnings=[],
            processing_logs="",
        )

        project.refresh_from_db()
        assert project.status == Project.Status.MANUFACTURABLE
        assert project.is_manufacturable is True

    def test_mark_finished_from_pending_raises(self):
        """Cannot mark PENDING check as FINISHED."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )
        with pytest.raises(InvalidStateTransitionError):
            check.mark_finished(
                is_manufacturable=True,
                errors=[],
                warnings=[],
                processing_logs="",
            )
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckMarkFinished -v
```

**Step 3: Implement mark_finished() (replacing complete())**

```python
def mark_finished(
    self,
    *,
    is_manufacturable: bool,
    errors: list,
    warnings: list,
    processing_logs: str,
) -> None:
    """Mark check as finished with results.

    Pathway 4: RUNNING → FINISHED

    Args:
        is_manufacturable: Whether design passed all checks
        errors: List of design errors found
        warnings: List of warnings found
        processing_logs: Full log output

    Raises:
        InvalidStateTransitionError: If transition is not allowed
    """
    if not self.can_transition_to(self.Status.FINISHED):
        raise InvalidStateTransitionError(
            from_status=self.status,
            to_status=self.Status.FINISHED,
        )

    self.status = self.Status.FINISHED
    self.celery_job_finished_at = timezone.now()
    self.is_manufacturable = is_manufacturable
    self.errors = errors
    self.warnings = warnings
    self.processing_logs = processing_logs
    self.save()

    # Update project status
    if is_manufacturable:
        self.project.status = Project.Status.MANUFACTURABLE
    else:
        self.project.status = Project.Status.NOT_MANUFACTURABLE
    self.project.is_manufacturable = is_manufacturable
    self.project.manufacturability_errors = self.errors
    self.project.check_completed_at = self.celery_job_finished_at
    self.project.save()
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckMarkFinished -v
```

**Step 5: Commit**

```bash
git add wafer_space/projects/models.py wafer_space/projects/tests/test_models.py
git commit -m "feat: add mark_finished() method replacing complete()"
```

---

### Task 3.4: Add mark_error() Method

**Files:**
- Modify: `wafer_space/projects/models.py`
- Test: `wafer_space/projects/tests/test_models.py`

**Step 1: Write failing test**

```python
class TestManufacturabilityCheckMarkError:
    """Tests for mark_error() method."""

    def test_mark_error_from_running(self):
        """Can mark RUNNING check as ERROR."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING
        )
        check.mark_error(
            error_message="Docker container crashed",
            processing_logs="Partial logs before crash",
        )

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.ERROR
        assert check.error_message == "Docker container crashed"
        assert "Partial logs" in check.processing_logs
        assert check.celery_job_finished_at is not None

    def test_mark_error_from_dispatched(self):
        """Can mark DISPATCHED check as ERROR (worker died before starting)."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.DISPATCHED
        )
        check.mark_error(error_message="Worker died")

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.ERROR

    def test_mark_error_from_pending(self):
        """Can mark PENDING check as ERROR."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )
        check.mark_error(error_message="System error")

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.ERROR

    def test_mark_error_from_finished_raises(self):
        """Cannot mark FINISHED check as ERROR."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.FINISHED
        )
        with pytest.raises(InvalidStateTransitionError):
            check.mark_error(error_message="Too late")

    def test_mark_error_from_cancelled_raises(self):
        """Cannot mark CANCELLED check as ERROR."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.CANCELLED
        )
        with pytest.raises(InvalidStateTransitionError):
            check.mark_error(error_message="Already cancelled")
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckMarkError -v
```

**Step 3: Implement mark_error() (replacing fail())**

```python
def mark_error(self, *, error_message: str, processing_logs: str = "") -> None:
    """Mark check as failed due to system error.

    Pathway 5/6: PENDING/DISPATCHED/RUNNING → ERROR

    System failures (Docker errors, timeouts, orphaned tasks) can be retried.
    This is different from a check that completed but found design issues.

    Args:
        error_message: Description of the system error
        processing_logs: Partial logs up to failure (if available)

    Raises:
        InvalidStateTransitionError: If transition is not allowed
    """
    if not self.can_transition_to(self.Status.ERROR):
        raise InvalidStateTransitionError(
            from_status=self.status,
            to_status=self.Status.ERROR,
        )

    self.status = self.Status.ERROR
    self.celery_job_finished_at = timezone.now()
    self.error_message = error_message
    if processing_logs:
        self.processing_logs = processing_logs
    self.processing_logs += "\n\n=== SYSTEM ERROR - See error_message field ==="
    self.save()
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckMarkError -v
```

**Step 5: Commit**

```bash
git add wafer_space/projects/models.py wafer_space/projects/tests/test_models.py
git commit -m "feat: add mark_error() method replacing fail()"
```

---

### Task 3.5: Update mark_cancelled() Method

**Files:**
- Modify: `wafer_space/projects/models.py`
- Test: `wafer_space/projects/tests/test_models.py`

**Step 1: Write failing test**

```python
class TestManufacturabilityCheckMarkCancelled:
    """Tests for mark_cancelled() method."""

    def test_mark_cancelled_from_pending(self):
        """Can cancel PENDING check."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )
        result = check.mark_cancelled(reason="User requested")

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLED
        assert check.celery_job_finished_at is not None
        assert "User requested" in check.processing_logs
        assert result is None  # No job to revoke

    def test_mark_cancelled_from_dispatched_returns_job_id(self):
        """Cancelling DISPATCHED check returns job ID to revoke."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.DISPATCHED,
            celery_job_id="job-to-revoke-123",
        )
        result = check.mark_cancelled(reason="Changed mind")

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLED
        assert result == "job-to-revoke-123"

    def test_mark_cancelled_from_running_returns_job_id(self):
        """Cancelling RUNNING check returns job ID to revoke."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING,
            celery_job_id="running-job-456",
        )
        result = check.mark_cancelled(reason="Taking too long")

        assert result == "running-job-456"

    def test_mark_cancelled_from_finished_raises(self):
        """Cannot cancel FINISHED check."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.FINISHED
        )
        with pytest.raises(InvalidStateTransitionError):
            check.mark_cancelled(reason="Too late")

    def test_mark_cancelled_from_error_raises(self):
        """Cannot cancel ERROR check."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.ERROR
        )
        with pytest.raises(InvalidStateTransitionError):
            check.mark_cancelled(reason="Already failed")

    def test_mark_cancelled_from_cancelled_raises(self):
        """Cannot cancel already CANCELLED check."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.CANCELLED
        )
        with pytest.raises(InvalidStateTransitionError):
            check.mark_cancelled(reason="Double cancel")
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckMarkCancelled -v
```

**Step 3: Update mark_cancelled() (refactoring existing cancel())**

```python
def mark_cancelled(self, *, reason: str = "Cancelled by user") -> str | None:
    """Cancel the check if it's still active.

    Pathway 8: PENDING/DISPATCHED/RUNNING → CANCELLED

    Args:
        reason: Why the check was cancelled

    Returns:
        The celery_job_id to revoke if one exists, None otherwise

    Raises:
        InvalidStateTransitionError: If transition is not allowed
    """
    if not self.can_transition_to(self.Status.CANCELLED):
        raise InvalidStateTransitionError(
            from_status=self.status,
            to_status=self.Status.CANCELLED,
        )

    celery_job_id = self.celery_job_id or None  # Return None if empty string
    self.status = self.Status.CANCELLED
    self.celery_job_finished_at = timezone.now()
    self.processing_logs += f"\n\nCANCELLED: {reason}"
    self.save()

    return celery_job_id
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckMarkCancelled -v
```

**Step 5: Commit**

```bash
git add wafer_space/projects/models.py wafer_space/projects/tests/test_models.py
git commit -m "refactor: update mark_cancelled() with state validation"
```

---

### Task 3.6: Add reset_for_retry() Method

**Files:**
- Modify: `wafer_space/projects/models.py`
- Test: `wafer_space/projects/tests/test_models.py`

**Step 1: Write failing test**

```python
class TestManufacturabilityCheckResetForRetry:
    """Tests for reset_for_retry() method."""

    def test_reset_for_retry_from_error(self):
        """Can reset ERROR check for retry."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.ERROR,
            retry_count=1,
            celery_job_id="old-job-id",
            celery_job_dispatched_at=timezone.now(),
            celery_job_started_at=timezone.now(),
            celery_job_finished_at=timezone.now(),
            celery_worker_pid=12345,
            celery_worker_hostname="old-worker",
            docker_container_id="old-container",
            error_message="Previous error",
        )
        check.reset_for_retry()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.PENDING
        assert check.retry_count == 2  # Incremented
        assert check.celery_job_id == ""
        assert check.celery_job_dispatched_at is None
        assert check.celery_job_started_at is None
        assert check.celery_job_finished_at is None
        assert check.celery_worker_pid is None
        assert check.celery_worker_hostname == ""
        assert check.docker_container_id == ""
        assert check.docker_container_started_at is None
        assert check.error_message == ""

    def test_reset_for_retry_from_pending_raises(self):
        """Cannot reset PENDING check (not in ERROR state)."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )
        with pytest.raises(InvalidStateTransitionError):
            check.reset_for_retry()

    def test_reset_for_retry_from_cancelled_raises(self):
        """Cannot reset CANCELLED check."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.CANCELLED
        )
        with pytest.raises(InvalidStateTransitionError):
            check.reset_for_retry()

    def test_reset_for_retry_from_finished_raises(self):
        """Cannot reset FINISHED check."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.FINISHED
        )
        with pytest.raises(InvalidStateTransitionError):
            check.reset_for_retry()
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckResetForRetry -v
```

**Step 3: Implement reset_for_retry()**

```python
def reset_for_retry(self) -> None:
    """Reset check for retry after ERROR state.

    Pathway 7: ERROR → PENDING

    Increments retry_count and clears all job/worker/docker fields.

    Raises:
        InvalidStateTransitionError: If not in ERROR state
    """
    if not self.can_transition_to(self.Status.PENDING):
        raise InvalidStateTransitionError(
            from_status=self.status,
            to_status=self.Status.PENDING,
        )

    self.status = self.Status.PENDING
    self.retry_count += 1

    # Clear Celery job fields
    self.celery_job_id = ""
    self.celery_job_dispatched_at = None
    self.celery_job_started_at = None
    self.celery_job_finished_at = None

    # Clear worker fields
    self.celery_worker_pid = None
    self.celery_worker_hostname = ""

    # Clear Docker fields
    self.docker_container_id = ""
    self.docker_container_started_at = None

    # Clear error
    self.error_message = ""

    self.save()
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckResetForRetry -v
```

**Step 5: Commit**

```bash
git add wafer_space/projects/models.py wafer_space/projects/tests/test_models.py
git commit -m "feat: add reset_for_retry() method for ERROR → PENDING transition"
```

---

## Phase 4: Migration

### Task 4.1: Create Migration for Field Renames and New Fields

**Step 1: Generate migration**

```bash
cd /home/tim/github/wafer-space/test-platform/.worktrees/issue-121-cancelled-state
uv run python manage.py makemigrations projects --name rename_manufacturability_check_fields
```

**Step 2: Review the generated migration**

The migration should rename fields and add new ones. If Django doesn't auto-detect renames, manually edit to use `RenameField`.

**Step 3: Create data migration for status values**

```bash
uv run python manage.py makemigrations projects --empty --name migrate_manufacturability_check_status_values
```

Edit the migration:

```python
from django.db import migrations


def migrate_status_values_forward(apps, schema_editor):
    """Migrate old status values to new ones."""
    ManufacturabilityCheck = apps.get_model("projects", "ManufacturabilityCheck")

    # Map old values to new
    status_map = {
        "queued": "pending",
        "starting": "dispatched",
        "processing": "running",
        "completed": "finished",
        "failed": "error",
        # "cancelled" stays the same
    }

    for old_status, new_status in status_map.items():
        ManufacturabilityCheck.objects.filter(status=old_status).update(
            status=new_status
        )


def migrate_status_values_backward(apps, schema_editor):
    """Reverse migration."""
    ManufacturabilityCheck = apps.get_model("projects", "ManufacturabilityCheck")

    status_map = {
        "pending": "queued",
        "dispatched": "starting",
        "running": "processing",
        "finished": "completed",
        "error": "failed",
    }

    for new_status, old_status in status_map.items():
        ManufacturabilityCheck.objects.filter(status=new_status).update(
            status=old_status
        )


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "XXXX_rename_manufacturability_check_fields"),  # Update this
    ]

    operations = [
        migrations.RunPython(
            migrate_status_values_forward,
            migrate_status_values_backward,
        ),
    ]
```

**Step 4: Run migrations**

```bash
uv run python manage.py migrate
```

**Step 5: Run tests to verify migrations work**

```bash
make test
```

**Step 6: Commit**

```bash
git add wafer_space/projects/migrations/
git commit -m "feat: add migrations for ManufacturabilityCheck field renames and status values"
```

---

## Phase 5: Update Tasks

### Task 5.1: Rename Celery Job Function

**Files:**
- Modify: `wafer_space/projects/tasks.py`

**Step 1: Rename function and update ALL references**

Change `check_project_manufacturability` to `celery_job_run` at line ~898.

**NO ALIASES** - delete the old name completely:

```python
@shared_task(bind=True, ...)
def celery_job_run(self, check_id: int):
    """Celery job: Execute manufacturability analysis for a check.

    ... existing docstring updated ...
    """
    # ... existing implementation ...
```

Search for all references to update:
```bash
grep -r "check_project_manufacturability" wafer_space/
```

**Step 2: Update task dispatch calls**

Find all `.delay(` calls that reference the old function name and update:

```python
# Old
task = check_project_manufacturability.delay(check.id)

# New
task = celery_job_run.delay(check.id)
```

**Step 3: Run tests**

```bash
make test
```

**Step 4: Commit**

```bash
git add wafer_space/projects/tasks.py
git commit -m "refactor: rename check_project_manufacturability to celery_job_run"
```

---

### Task 5.2: Update Task to Use New Model Methods

**Files:**
- Modify: `wafer_space/projects/tasks.py`

**Step 1: Update celery_job_run to use mark_running()**

Replace the manual field setting with:

```python
# Old (around line 920-926)
check.task_id = self.request.id or "test-task"
check.worker_pid = os.getpid()
check.worker_hostname = socket.gethostname()
check.save(update_fields=["task_id", "worker_pid", "worker_hostname"])
check.start_processing()

# New
check.celery_job_id = self.request.id or "test-task"
check.save(update_fields=["celery_job_id"])

# Get container ID after docker.run() returns
container = client.containers.run(...)
check.mark_running(
    celery_worker_pid=os.getpid(),
    celery_worker_hostname=socket.gethostname(),
    docker_container_id=container.id,
)
```

**Note:** The exact placement depends on when the Docker container is created. The container ID should be captured from the `docker.containers.run()` call.

**Step 2: Update success path to use mark_finished()**

```python
# Old
check.complete(is_manufacturable, errors, warnings, logs)

# New
check.mark_finished(
    is_manufacturable=is_manufacturable,
    errors=errors,
    warnings=warnings,
    processing_logs=logs,
)
```

**Step 3: Update error handlers to use mark_error()**

```python
# Old
check.fail(str(exc))

# New
check.mark_error(error_message=str(exc), processing_logs=partial_logs)
```

**Step 4: Run tests**

```bash
make test
```

**Step 5: Commit**

```bash
git add wafer_space/projects/tasks.py
git commit -m "refactor: update celery_job_run to use new model methods"
```

---

### Task 5.3: Update Queue Processor Functions

**Files:**
- Modify: `wafer_space/projects/tasks.py`

**Step 1: Rename helper functions (NO ALIASES)**

```python
# Old → New (delete old names completely)
_handle_starting_checks → _handle_dispatched_checks
_handle_processing_checks → _handle_running_checks
_handle_failed_checks → _handle_error_checks
_handle_queued_checks → _handle_pending_checks
_reset_check_for_retry → (delete entirely, use check.reset_for_retry())
scan_and_queue_manufacturability_checks → (delete alias at line ~3180)
```

Search for all references:
```bash
grep -r "_handle_starting_checks\|_handle_processing_checks\|_handle_failed_checks\|_handle_queued_checks\|_reset_check_for_retry\|scan_and_queue" wafer_space/
```

**Step 2: Update status references in each function**

```python
# Old
ManufacturabilityCheck.Status.QUEUED
ManufacturabilityCheck.Status.STARTING
ManufacturabilityCheck.Status.PROCESSING
ManufacturabilityCheck.Status.COMPLETED
ManufacturabilityCheck.Status.FAILED

# New
ManufacturabilityCheck.Status.PENDING
ManufacturabilityCheck.Status.DISPATCHED
ManufacturabilityCheck.Status.RUNNING
ManufacturabilityCheck.Status.FINISHED
ManufacturabilityCheck.Status.ERROR
```

**Step 3: Update _handle_pending_checks to use mark_dispatched()**

```python
# Old (around line 3103-3106)
task = check_project_manufacturability.delay(check.id)
check.status = ManufacturabilityCheck.Status.STARTING
check.task_id = task.id
check.save(update_fields=["status", "task_id"])

# New
task = celery_job_run.delay(check.id)
check.mark_dispatched(celery_job_id=task.id)
```

**Step 4: Update _handle_running_checks to use mark_error()**

```python
# Old (around line 3012-3025)
check.status = ManufacturabilityCheck.Status.FAILED
check.error_message = "Task not running..."
check.completed_at = timezone.now()
check.worker_pid = None
check.worker_hostname = ""
check.save(...)

# New
check.mark_error(error_message="Task not running (worker crashed or task failed)")
```

**Step 5: Update _handle_error_checks to use reset_for_retry()**

```python
# Old
_reset_check_for_retry(check)

# New
check.reset_for_retry()
```

**Step 6: Run tests**

```bash
make test
```

**Step 7: Commit**

```bash
git add wafer_space/projects/tasks.py
git commit -m "refactor: update queue processor to use new status names and methods"
```

---

### Task 5.4: Update Creation Pathway

**Files:**
- Modify: `wafer_space/projects/tasks.py`

**Step 1: Rename function**

```python
# Old (line ~2249)
def _queue_manufacturability_check(project_file: ProjectFile) -> ManufacturabilityCheck:

# New
def _create_manufacturability_check(project_file: ProjectFile) -> ManufacturabilityCheck:
```

**Step 2: Update status references**

```python
# Old (line ~2264-2270)
status__in=[
    ManufacturabilityCheck.Status.QUEUED,
    ManufacturabilityCheck.Status.STARTING,
    ManufacturabilityCheck.Status.PROCESSING,
],

# New
status__in=[
    ManufacturabilityCheck.Status.PENDING,
    ManufacturabilityCheck.Status.DISPATCHED,
    ManufacturabilityCheck.Status.RUNNING,
],
```

```python
# Old (line ~2285)
status=ManufacturabilityCheck.Status.QUEUED,

# New
status=ManufacturabilityCheck.Status.PENDING,
```

**Step 3: Update caller**

```python
# Old (line ~2366)
_queue_manufacturability_check(project_file)

# New
_create_manufacturability_check(project_file)
```

**Step 4: Run tests**

```bash
make test
```

**Step 5: Commit**

```bash
git add wafer_space/projects/tasks.py
git commit -m "refactor: rename _queue_manufacturability_check to _create_manufacturability_check"
```

---

## Phase 6: Update Services

### Task 6.1: Refactor queue_check() Method

**Files:**
- Modify: `wafer_space/projects/services.py`
- Test: `wafer_space/projects/tests/test_services.py`

**Step 1: Write test for new behavior**

```python
class TestManufacturabilityServiceQueueCheckStateValidation:
    """Tests for queue_check() state transition validation."""

    def test_queue_check_cancelled_raises_error(self):
        """Cannot re-queue a CANCELLED check."""
        project_file = ProjectFileFactory()
        check = ManufacturabilityCheckFactory(
            project=project_file.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.CANCELLED,
        )

        with pytest.raises(InvalidStateTransitionError):
            ManufacturabilityService.queue_check(
                project=project_file.project,
                project_file=project_file,
            )

    def test_queue_check_finished_raises_error(self):
        """Cannot re-queue a FINISHED check."""
        project_file = ProjectFileFactory()
        check = ManufacturabilityCheckFactory(
            project=project_file.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
        )

        with pytest.raises(InvalidStateTransitionError):
            ManufacturabilityService.queue_check(
                project=project_file.project,
                project_file=project_file,
            )
```

**Step 2: Run tests to see current behavior**

```bash
uv run pytest wafer_space/projects/tests/test_services.py::TestManufacturabilityServiceQueueCheckStateValidation -v
```

**Step 3: Update queue_check() to validate state transitions**

The refactored method should:
- Return immediately if already PENDING/DISPATCHED/RUNNING
- Raise InvalidStateTransitionError for CANCELLED/FINISHED
- NOT dispatch to Celery (scheduler handles that)
- NOT reset retry_count

```python
@classmethod
def queue_check(
    cls,
    project: Project,
    project_file: "ProjectFile",
    *,
    force: bool = False,
) -> ManufacturabilityCheck:
    """Queue a manufacturability check for a specific project file.

    This method is for manual queueing from admin. Normally checks are
    created by _create_manufacturability_check() during file processing
    and dispatched by the periodic scheduler task.

    Args:
        project: The project to check
        project_file: The specific file to check
        force: If True, skip concurrent limit check (for admin use)

    Returns:
        ManufacturabilityCheck instance

    Raises:
        InvalidStateTransitionError: If check is in terminal state
        ValidationError: If global concurrent limit reached
    """
    from wafer_space.projects.exceptions import InvalidStateTransitionError

    with transaction.atomic():
        try:
            check = ManufacturabilityCheck.objects.get(
                project=project,
                project_file=project_file,
            )
        except ManufacturabilityCheck.DoesNotExist:
            # Create new check in PENDING state
            check = ManufacturabilityCheck.objects.create(
                project=project,
                project_file=project_file,
                status=ManufacturabilityCheck.Status.PENDING,
            )
            return check

        # Already active - return immediately (idempotent)
        if check.status in [
            ManufacturabilityCheck.Status.PENDING,
            ManufacturabilityCheck.Status.DISPATCHED,
            ManufacturabilityCheck.Status.RUNNING,
        ]:
            return check

        # Terminal states - cannot re-queue
        if check.status in [
            ManufacturabilityCheck.Status.FINISHED,
            ManufacturabilityCheck.Status.CANCELLED,
        ]:
            raise InvalidStateTransitionError(
                from_status=check.status,
                to_status=ManufacturabilityCheck.Status.PENDING,
            )

        # ERROR state - can retry via reset_for_retry()
        if check.status == ManufacturabilityCheck.Status.ERROR:
            if not check.can_retry():
                msg = f"Check has exceeded maximum retries ({check.retry_count})"
                raise ValidationError(msg)
            check.reset_for_retry()

        return check
```

**Step 4: Run tests**

```bash
uv run pytest wafer_space/projects/tests/test_services.py -v
```

**Step 5: Commit**

```bash
git add wafer_space/projects/services.py wafer_space/projects/tests/test_services.py
git commit -m "refactor: queue_check() now validates state transitions

- CANCELLED/FINISHED checks raise InvalidStateTransitionError
- ERROR checks use reset_for_retry() (respects retry limit)
- No longer dispatches to Celery (scheduler handles that)
- No longer resets retry_count unconditionally"
```

---

## Phase 7: Update Views and Admin

### Task 7.1: Update Views Status References

**Files:**
- Modify: `wafer_space/projects/views.py`

**Step 1: Update status references**

```python
# Line ~515
ManufacturabilityCheck.Status.PROCESSING → ManufacturabilityCheck.Status.RUNNING

# Line ~528
ManufacturabilityCheck.Status.QUEUED → ManufacturabilityCheck.Status.PENDING
```

**Step 2: Run tests**

```bash
make test
```

**Step 3: Commit**

```bash
git add wafer_space/projects/views.py
git commit -m "refactor: update views to use new status names"
```

---

### Task 7.2: Update Admin Field References

**Files:**
- Modify: `wafer_space/projects/admin.py`

**Step 1: Update readonly_fields**

```python
# Old (line ~100)
"task_id",

# New
"celery_job_id",
```

**Step 2: Update any other field references**

Check for references to renamed fields and update them.

**Step 3: Run tests**

```bash
make test
```

**Step 4: Commit**

```bash
git add wafer_space/projects/admin.py
git commit -m "refactor: update admin to use new field names"
```

---

## Phase 8: Update Model Properties and Remove Old Methods

### Task 8.1: Update is_cancellable Property

**Files:**
- Modify: `wafer_space/projects/models.py`

**Step 1: Update the property**

```python
@property
def is_cancellable(self) -> bool:
    """Check if this check can be cancelled."""
    return self.status in [
        self.Status.PENDING,
        self.Status.DISPATCHED,
        self.Status.RUNNING,
    ]
```

**Step 2: Update result_display property**

```python
# Old (line ~1266)
if self.status != self.Status.COMPLETED or self.is_manufacturable is None:

# New
if self.status != self.Status.FINISHED or self.is_manufacturable is None:
```

**Step 3: Update queue_position property**

```python
# Old (line ~1286)
status=self.Status.QUEUED,

# New
status=self.Status.PENDING,
```

**Step 4: Remove old methods**

Delete or deprecate:
- `start_processing()` (replaced by `mark_running()`)
- `complete()` (replaced by `mark_finished()`)
- `fail()` (replaced by `mark_error()`)
- `cancel()` (replaced by `mark_cancelled()`)

**Step 5: Run tests**

```bash
make test
```

**Step 6: Commit**

```bash
git add wafer_space/projects/models.py
git commit -m "refactor: update model properties and remove deprecated methods"
```

---

## Phase 9: Update All Tests

### Task 9.1: Update Test Factories

**Files:**
- Modify: `wafer_space/projects/tests/factories.py` (if exists) or test files

**Step 1: Update ManufacturabilityCheckFactory defaults**

Ensure factory uses new field names and status values.

**Step 2: Run tests**

```bash
make test
```

**Step 3: Commit**

```bash
git add wafer_space/projects/tests/
git commit -m "refactor: update test factories for new field names"
```

---

### Task 9.2: Update Remaining Test Files

**Files:**
- Modify: All test files in `wafer_space/projects/tests/`

**Step 1: Search and replace status references**

```bash
# In the worktree directory
grep -r "Status.QUEUED" wafer_space/projects/tests/
grep -r "Status.STARTING" wafer_space/projects/tests/
grep -r "Status.PROCESSING" wafer_space/projects/tests/
grep -r "Status.COMPLETED" wafer_space/projects/tests/
grep -r "Status.FAILED" wafer_space/projects/tests/
```

Update all occurrences.

**Step 2: Search and replace field references**

```bash
grep -r "task_id" wafer_space/projects/tests/
grep -r "started_at" wafer_space/projects/tests/
grep -r "completed_at" wafer_space/projects/tests/
grep -r "queued_at" wafer_space/projects/tests/
grep -r "worker_pid" wafer_space/projects/tests/
grep -r "worker_hostname" wafer_space/projects/tests/
```

Update all occurrences.

**Step 3: Search and replace method references**

```bash
grep -r "start_processing" wafer_space/projects/tests/
grep -r "\.complete(" wafer_space/projects/tests/
grep -r "\.fail(" wafer_space/projects/tests/
grep -r "\.cancel(" wafer_space/projects/tests/
```

Update to use new method names.

**Step 4: Run full test suite**

```bash
make test
```

**Step 5: Fix any remaining failures**

Iterate until all tests pass.

**Step 6: Commit**

```bash
git add wafer_space/projects/tests/
git commit -m "refactor: update all tests for new status names, fields, and methods"
```

---

## Phase 10: Final Verification

### Task 10.1: Run Full Quality Checks

**Step 1: Run all quality checks**

```bash
make lint-fix && make lint && make type-check && make test
```

**Step 2: Fix any remaining issues**

**Step 3: Final commit if needed**

```bash
git add -A
git commit -m "fix: address remaining lint and type issues"
```

---

### Task 10.2: Create Summary Commit

**Step 1: Verify all changes**

```bash
git log --oneline origin/main..HEAD
```

**Step 2: Push branch**

```bash
git push -u origin feature/cancelled-state-protection
```

---

## Summary

| Phase | Tasks | Description |
|-------|-------|-------------|
| 1 | 1.1-1.3 | Exception, Status enum, ALLOWED_TRANSITIONS |
| 2 | 2.1-2.2 | Field renames, Docker tracking fields |
| 3 | 3.1-3.6 | New model methods (mark_dispatched, mark_running, etc.) |
| 4 | 4.1 | Database migrations |
| 5 | 5.1-5.4 | Update tasks (rename functions, use new methods) |
| 6 | 6.1 | Refactor services (queue_check validation) |
| 7 | 7.1-7.2 | Update views and admin |
| 8 | 8.1 | Update model properties, remove old methods |
| 9 | 9.1-9.2 | Update all tests |
| 10 | 10.1-10.2 | Final verification and push |

**Estimated tasks:** ~25 discrete commits
**Key principle:** Each task is independently testable and committable
