# Manufacturability Check Task Restructure - Implementation Plan

**Status:** Implemented (2025-11-30)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restructure manufacturability check Celery tasks from monolithic to single-responsibility, add CANCELLING state for safe async cleanup, and remove ManufacturabilityService.

**Architecture:** Add CANCELLING intermediate state to model, create 8 new single-responsibility Celery tasks, rename queues to `docker-persistent` and `docker-ephemeral`, update views to call model directly, delete ManufacturabilityService.

**Tech Stack:** Django 5.2+, Celery with PostgreSQL broker, Docker SDK for Python

**Design Document:** `docs/plans/2025-11-30-manufacturability-check-task-restructure.md`

---

## Phase 1: Model Changes (CANCELLING State)

### Task 1.1: Add CANCELLING to Status enum

**Files:**
- Modify: `wafer_space/projects/models.py:1032-1038` (Status enum)
- Test: `wafer_space/projects/tests/test_models.py`

**Step 1: Write the failing test**

Add to `wafer_space/projects/tests/test_models.py` after the imports:

```python
class TestManufacturabilityCheckCancellingState(TestCase):
    """Test CANCELLING state in ManufacturabilityCheck."""

    def test_cancelling_status_exists(self):
        """Test CANCELLING is a valid status choice."""
        from wafer_space.projects.models import ManufacturabilityCheck

        assert hasattr(ManufacturabilityCheck.Status, "CANCELLING")
        assert ManufacturabilityCheck.Status.CANCELLING.value == "cancelling"
        assert ManufacturabilityCheck.Status.CANCELLING.label == "Cancelling"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckCancellingState::test_cancelling_status_exists -v`
Expected: FAIL with `AttributeError: CANCELLING`

**Step 3: Add CANCELLING to Status enum**

In `wafer_space/projects/models.py`, find the Status class (line 1032) and add CANCELLING:

```python
class Status(models.TextChoices):
    PENDING = "pending", "Pending"  # Waiting for capacity
    DISPATCHED = "dispatched", "Dispatched"  # Job sent to Celery
    RUNNING = "running", "Running"  # Celery worker executing
    FINISHED = "finished", "Finished"  # Analysis complete
    ERROR = "error", "Error"  # System/processing failure
    CANCELLING = "cancelling", "Cancelling"  # Cleanup in progress
    CANCELLED = "cancelled", "Cancelled"  # User cancelled
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckCancellingState::test_cancelling_status_exists -v`
Expected: PASS

**Step 5: Commit**

```bash
git add wafer_space/projects/models.py wafer_space/projects/tests/test_models.py
git commit -m "feat(models): add CANCELLING status to ManufacturabilityCheck"
```

---

### Task 1.2: Update ALLOWED_TRANSITIONS for CANCELLING

**Files:**
- Modify: `wafer_space/projects/models.py:1047-1054` (ALLOWED_TRANSITIONS)
- Test: `wafer_space/projects/tests/test_models.py`

**Step 1: Write the failing test**

Add to `TestManufacturabilityCheckCancellingState` class:

```python
def test_can_transition_to_cancelling_from_pending(self):
    """Test PENDING can transition to CANCELLING."""
    check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.PENDING)
    assert check.can_transition_to(ManufacturabilityCheck.Status.CANCELLING) is True

def test_can_transition_to_cancelling_from_dispatched(self):
    """Test DISPATCHED can transition to CANCELLING."""
    check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.DISPATCHED)
    assert check.can_transition_to(ManufacturabilityCheck.Status.CANCELLING) is True

def test_can_transition_to_cancelling_from_running(self):
    """Test RUNNING can transition to CANCELLING."""
    check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.RUNNING)
    assert check.can_transition_to(ManufacturabilityCheck.Status.CANCELLING) is True

def test_cancelling_can_only_transition_to_cancelled(self):
    """Test CANCELLING can only transition to CANCELLED."""
    check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.CANCELLING)
    assert check.can_transition_to(ManufacturabilityCheck.Status.CANCELLED) is True
    # Cannot transition to anything else
    assert check.can_transition_to(ManufacturabilityCheck.Status.PENDING) is False
    assert check.can_transition_to(ManufacturabilityCheck.Status.ERROR) is False
    assert check.can_transition_to(ManufacturabilityCheck.Status.FINISHED) is False

def test_cannot_transition_to_cancelled_directly_from_running(self):
    """Test RUNNING cannot skip CANCELLING and go directly to CANCELLED."""
    check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.RUNNING)
    # Must go through CANCELLING first
    assert check.can_transition_to(ManufacturabilityCheck.Status.CANCELLED) is False
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckCancellingState -v`
Expected: FAIL - transitions not allowed yet

**Step 3: Update ALLOWED_TRANSITIONS**

In `wafer_space/projects/models.py`, update ALLOWED_TRANSITIONS (around line 1047):

```python
ALLOWED_TRANSITIONS: ClassVar[dict[Status, set[Status]]] = {
    Status.PENDING: {Status.DISPATCHED, Status.ERROR, Status.CANCELLING},
    Status.DISPATCHED: {Status.RUNNING, Status.ERROR, Status.CANCELLING},
    Status.RUNNING: {Status.FINISHED, Status.ERROR, Status.CANCELLING},
    Status.FINISHED: set(),  # Terminal - no transitions
    Status.ERROR: {Status.PENDING},  # Can retry
    Status.CANCELLING: {Status.CANCELLED},  # Only cleanup task can complete
    Status.CANCELLED: set(),  # Terminal - no transitions
}
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckCancellingState -v`
Expected: PASS

**Step 5: Commit**

```bash
git add wafer_space/projects/models.py wafer_space/projects/tests/test_models.py
git commit -m "feat(models): update ALLOWED_TRANSITIONS for CANCELLING state"
```

---

### Task 1.3: Add mark_cancelling() method

**Files:**
- Modify: `wafer_space/projects/models.py` (after mark_error, around line 1405)
- Test: `wafer_space/projects/tests/test_models.py`

**Step 1: Write the failing test**

Add new test class to `wafer_space/projects/tests/test_models.py`:

```python
class TestManufacturabilityCheckMarkCancelling(TestCase):
    """Test mark_cancelling method."""

    def test_mark_cancelling_from_pending(self):
        """Test mark_cancelling transitions PENDING to CANCELLING."""
        check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.PENDING)

        check.mark_cancelling(reason="User requested cancellation")

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLING
        assert "User requested cancellation" in check.processing_logs

    def test_mark_cancelling_from_dispatched(self):
        """Test mark_cancelling transitions DISPATCHED to CANCELLING."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.DISPATCHED,
            celery_job_id="test-job-123",
        )

        check.mark_cancelling(reason="New file submitted")

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLING
        # Job ID preserved for cleanup task
        assert check.celery_job_id == "test-job-123"

    def test_mark_cancelling_from_running(self):
        """Test mark_cancelling transitions RUNNING to CANCELLING."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING,
            docker_container_id="abc123def",
        )

        check.mark_cancelling(reason="Admin cancelled")

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLING
        # Container ID preserved for cleanup task
        assert check.docker_container_id == "abc123def"

    def test_mark_cancelling_appends_to_existing_logs(self):
        """Test mark_cancelling appends reason to existing logs."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING,
            processing_logs="Previous log output",
        )

        check.mark_cancelling(reason="Cancelled by user")

        check.refresh_from_db()
        assert "Previous log output" in check.processing_logs
        assert "CANCELLATION REQUESTED: Cancelled by user" in check.processing_logs

    def test_mark_cancelling_from_finished_raises(self):
        """Test mark_cancelling raises for terminal FINISHED state."""
        check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.FINISHED)

        with pytest.raises(InvalidStateTransitionError):
            check.mark_cancelling(reason="Should fail")

    def test_mark_cancelling_from_cancelled_raises(self):
        """Test mark_cancelling raises for terminal CANCELLED state."""
        check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.CANCELLED)

        with pytest.raises(InvalidStateTransitionError):
            check.mark_cancelling(reason="Should fail")

    def test_mark_cancelling_from_error_raises(self):
        """Test mark_cancelling raises for ERROR state (should retry instead)."""
        check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.ERROR)

        with pytest.raises(InvalidStateTransitionError):
            check.mark_cancelling(reason="Should fail")
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckMarkCancelling -v`
Expected: FAIL with `AttributeError: 'ManufacturabilityCheck' object has no attribute 'mark_cancelling'`

**Step 3: Add mark_cancelling method**

In `wafer_space/projects/models.py`, add after mark_error method (around line 1405):

```python
def mark_cancelling(self, *, reason: str) -> None:
    """Request cancellation - transitions to CANCELLING state.

    Cleanup task will complete the transition to CANCELLED after
    revoking Celery task and stopping Docker container.

    Args:
        reason: Description of why the check is being cancelled

    Raises:
        InvalidStateTransitionError: If transition is not allowed
    """
    if not self.can_transition_to(self.Status.CANCELLING):
        raise InvalidStateTransitionError(
            from_status=self.status,
            to_status=self.Status.CANCELLING,
        )

    self.status = self.Status.CANCELLING

    # Append reason to processing_logs
    cancellation_msg = f"CANCELLATION REQUESTED: {reason}"
    if self.processing_logs:
        self.processing_logs += f"\n\n{cancellation_msg}"
    else:
        self.processing_logs = cancellation_msg

    self.save()
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckMarkCancelling -v`
Expected: PASS

**Step 5: Commit**

```bash
git add wafer_space/projects/models.py wafer_space/projects/tests/test_models.py
git commit -m "feat(models): add mark_cancelling() method for async cancellation"
```

---

### Task 1.4: Update mark_cancelled() to only work from CANCELLING

**Files:**
- Modify: `wafer_space/projects/models.py:1407-1441` (mark_cancelled method)
- Modify: `wafer_space/projects/tests/test_models.py`

**Step 1: Write the failing test**

Update `TestManufacturabilityCheckMarkCancelled` class - add new tests and modify expectations:

```python
def test_mark_cancelled_from_cancelling_succeeds(self):
    """Test mark_cancelled works from CANCELLING state."""
    check = ManufacturabilityCheckFactory(
        status=ManufacturabilityCheck.Status.CANCELLING,
        processing_logs="CANCELLATION REQUESTED: User cancelled",
    )

    check.mark_cancelled()

    check.refresh_from_db()
    assert check.status == ManufacturabilityCheck.Status.CANCELLED
    assert check.celery_job_finished_at is not None

def test_mark_cancelled_from_pending_raises(self):
    """Test mark_cancelled raises from PENDING (must use mark_cancelling first)."""
    check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.PENDING)

    with pytest.raises(InvalidStateTransitionError):
        check.mark_cancelled()

def test_mark_cancelled_from_running_raises(self):
    """Test mark_cancelled raises from RUNNING (must use mark_cancelling first)."""
    check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.RUNNING)

    with pytest.raises(InvalidStateTransitionError):
        check.mark_cancelled()
```

**Step 2: Run tests to verify current behavior**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckMarkCancelled -v`
Expected: Some tests fail (old tests expect direct cancellation)

**Step 3: Update mark_cancelled method**

In `wafer_space/projects/models.py`, simplify mark_cancelled (around line 1407):

```python
def mark_cancelled(self) -> None:
    """Complete cancellation - only called by cleanup task after cleanup is done.

    This method should only be called from CANCELLING state, after the
    checks_cancelling task has revoked the Celery task and stopped any
    Docker container.

    Raises:
        InvalidStateTransitionError: If transition is not allowed
    """
    if not self.can_transition_to(self.Status.CANCELLED):
        raise InvalidStateTransitionError(
            from_status=self.status,
            to_status=self.Status.CANCELLED,
        )

    self.status = self.Status.CANCELLED
    self.celery_job_finished_at = timezone.now()
    self.save()
```

**Step 4: Update existing tests**

The old `TestManufacturabilityCheckMarkCancelled` tests need updating. Delete the old tests that expect `reason` parameter and direct cancellation from PENDING/DISPATCHED/RUNNING. Keep infrastructure tests but update to go through CANCELLING first.

**Step 5: Run all model tests**

Run: `uv run pytest wafer_space/projects/tests/test_models.py -v`
Expected: PASS (after fixing tests)

**Step 6: Commit**

```bash
git add wafer_space/projects/models.py wafer_space/projects/tests/test_models.py
git commit -m "refactor(models): mark_cancelled only valid from CANCELLING state"
```

---

### Task 1.5: Update is_cancellable property

**Files:**
- Modify: `wafer_space/projects/models.py` (is_cancellable property)
- Test: `wafer_space/projects/tests/test_models.py`

**Step 1: Write the failing test**

Add to `TestManufacturabilityCheckCancellingState`:

```python
def test_is_cancellable_true_for_pending(self):
    """Test is_cancellable returns True for PENDING."""
    check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.PENDING)
    assert check.is_cancellable is True

def test_is_cancellable_true_for_dispatched(self):
    """Test is_cancellable returns True for DISPATCHED."""
    check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.DISPATCHED)
    assert check.is_cancellable is True

def test_is_cancellable_true_for_running(self):
    """Test is_cancellable returns True for RUNNING."""
    check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.RUNNING)
    assert check.is_cancellable is True

def test_is_cancellable_false_for_cancelling(self):
    """Test is_cancellable returns False for CANCELLING (already cancelling)."""
    check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.CANCELLING)
    assert check.is_cancellable is False

def test_is_cancellable_false_for_cancelled(self):
    """Test is_cancellable returns False for CANCELLED."""
    check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.CANCELLED)
    assert check.is_cancellable is False
```

**Step 2: Run tests**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckCancellingState -v -k is_cancellable`
Expected: May pass or fail depending on current implementation

**Step 3: Update is_cancellable property**

Find `is_cancellable` in models.py and update:

```python
@property
def is_cancellable(self) -> bool:
    """Check if this check can be cancelled.

    Returns True if check can transition to CANCELLING state.
    """
    return self.can_transition_to(self.Status.CANCELLING)
```

**Step 4: Run tests**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckCancellingState -v`
Expected: PASS

**Step 5: Commit**

```bash
git add wafer_space/projects/models.py wafer_space/projects/tests/test_models.py
git commit -m "feat(models): update is_cancellable to check CANCELLING transition"
```

---

### Task 1.6: Create database migration

**Files:**
- Create: `wafer_space/projects/migrations/XXXX_add_cancelling_status.py`

**Step 1: Generate migration**

Run: `uv run python manage.py makemigrations projects --name add_cancelling_status`

**Step 2: Verify migration created**

Check that migration file exists and contains the status field change.

**Step 3: Apply migration**

Run: `uv run python manage.py migrate`

**Step 4: Run all tests**

Run: `make test`
Expected: PASS

**Step 5: Commit**

```bash
git add wafer_space/projects/migrations/
git commit -m "feat(migrations): add CANCELLING status to ManufacturabilityCheck"
```

---

## Phase 2: Update Views and Delete ManufacturabilityService

### Task 2.1: Update ManufacturabilityCheckCancelView

**Files:**
- Modify: `wafer_space/projects/views.py:460-494`
- Test: `wafer_space/projects/tests/test_views.py`

**Step 1: Write the failing test**

Update tests in `TestManufacturabilityCheckCancelView`:

```python
def test_cancel_check_transitions_to_cancelling(self):
    """Test cancel sets status to CANCELLING (not CANCELLED)."""
    check = ManufacturabilityCheckFactory(
        project_file=self.project_file,
        status=ManufacturabilityCheck.Status.RUNNING,
    )

    self.client.login(username=self.user.username, password=TEST_PASSWORD)
    url = reverse("projects:cancel_check", kwargs={"pk": self.project.pk})
    response = self.client.post(url)

    check.refresh_from_db()
    # Should be CANCELLING, not CANCELLED
    assert check.status == ManufacturabilityCheck.Status.CANCELLING
    assert response.status_code == 302

def test_cancel_check_shows_cancelling_message(self):
    """Test cancel shows appropriate message about cleanup in progress."""
    check = ManufacturabilityCheckFactory(
        project_file=self.project_file,
        status=ManufacturabilityCheck.Status.PENDING,
    )

    self.client.login(username=self.user.username, password=TEST_PASSWORD)
    url = reverse("projects:cancel_check", kwargs={"pk": self.project.pk})
    response = self.client.post(url, follow=True)

    messages_list = list(response.context["messages"])
    assert len(messages_list) == 1
    assert "Cancellation requested" in str(messages_list[0])
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest wafer_space/projects/tests/test_views.py::TestManufacturabilityCheckCancelView -v`
Expected: FAIL - status will be CANCELLED, not CANCELLING

**Step 3: Update the view**

In `wafer_space/projects/views.py`, update `ManufacturabilityCheckCancelView.post()`:

```python
def post(self, request, pk):
    """Handle check cancellation."""
    project = get_object_or_404(Project, pk=pk)

    # Get active file's manufacturability check
    active_file = ProjectFile.objects.filter(
        project=project,
        is_active=True,
    ).first()

    if not active_file:
        messages.error(request, "No active file found.")
        return redirect("projects:detail", pk=pk)

    try:
        check = active_file.manufacturability_check
    except ManufacturabilityCheck.DoesNotExist:
        messages.error(request, "No manufacturability check found.")
        return redirect("projects:detail", pk=pk)

    try:
        check.mark_cancelling(reason="Cancelled by user")
        messages.success(request, "Cancellation requested. Cleanup in progress...")
    except InvalidStateTransitionError:
        msg = "Check cannot be cancelled (already finished or in error state)."
        messages.warning(request, msg)

    return redirect("projects:detail", pk=pk)
```

Also remove the import of `ManufacturabilityService` from views.py (line 34).

**Step 4: Run tests**

Run: `uv run pytest wafer_space/projects/tests/test_views.py::TestManufacturabilityCheckCancelView -v`
Expected: PASS

**Step 5: Commit**

```bash
git add wafer_space/projects/views.py wafer_space/projects/tests/test_views.py
git commit -m "refactor(views): call mark_cancelling directly instead of ManufacturabilityService"
```

---

### Task 2.2: Update ProjectFileService to use mark_cancelling

**Files:**
- Modify: `wafer_space/projects/services.py:340-365`
- Test: `wafer_space/projects/tests/test_services.py`

**Step 1: Update the service method**

In `wafer_space/projects/services.py`, find the method that calls `ManufacturabilityService.cancel_check` (around line 354) and change to:

```python
if active_file:
    # Cancel any running manufacturability check on this file
    try:
        check = active_file.manufacturability_check
        if check.is_cancellable:
            check.mark_cancelling(reason="Cancelled: new file submitted")
    except ManufacturabilityCheck.DoesNotExist:
        pass  # No check to cancel

    # Mark as inactive (the new file will be marked active)
    active_file.is_active = False
    active_file.save(update_fields=["is_active"])
```

Remove the import of `ManufacturabilityService` from the file imports.

**Step 2: Run tests**

Run: `uv run pytest wafer_space/projects/tests/test_services.py -v`
Expected: PASS (or update tests if they expect CANCELLED)

**Step 3: Commit**

```bash
git add wafer_space/projects/services.py
git commit -m "refactor(services): use mark_cancelling in ProjectFileService"
```

---

### Task 2.3: Delete ManufacturabilityService class

**Files:**
- Modify: `wafer_space/projects/services.py` (delete lines 559-587)
- Delete tests: `wafer_space/projects/tests/test_services.py` (TestManufacturabilityService class)

**Step 1: Delete the class**

In `wafer_space/projects/services.py`, delete the entire `ManufacturabilityService` class (lines 559-587).

**Step 2: Delete the tests**

In `wafer_space/projects/tests/test_services.py`, delete the entire `TestManufacturabilityService` class (starts at line 618).

**Step 3: Remove import from test file**

Remove `from wafer_space.projects.services import ManufacturabilityService` from test_services.py imports.

**Step 4: Run lint and tests**

Run: `make lint-fix && make lint && make type-check && make test`
Expected: PASS

**Step 5: Commit**

```bash
git add wafer_space/projects/services.py wafer_space/projects/tests/test_services.py
git commit -m "refactor(services): delete ManufacturabilityService class"
```

---

## Phase 3: New Celery Tasks

### Task 3.1: Rename celery_job_run to check_process_job

**Files:**
- Modify: `wafer_space/projects/tasks.py:893` (rename function)
- Modify: All call sites

**Step 1: Find and rename**

In `wafer_space/projects/tasks.py`, find `celery_job_run` (line 893) and rename to `check_process_job`.

Update the queue to `docker-persistent`:

```python
@shared_task(
    bind=True,
    queue="docker-persistent",
    autoretry_for=(),
    default_retry_delay=60,
    max_retries=0,
    acks_late=True,
    reject_on_worker_lost=True,
)
def check_process_job(self, check_id: int) -> dict:
    """Run manufacturability check in Docker container for a single check."""
    # ... existing implementation
```

**Step 2: Update all call sites**

Search for `celery_job_run` and update to `check_process_job`:
- In the task file itself (any `.delay()` calls)
- In any test files

**Step 3: Run tests**

Run: `make test`
Expected: PASS

**Step 4: Commit**

```bash
git add wafer_space/projects/tasks.py wafer_space/projects/tests/
git commit -m "refactor(tasks): rename celery_job_run to check_process_job"
```

---

### Task 3.2: Create checks_dispatch task

**Files:**
- Modify: `wafer_space/projects/tasks.py`
- Test: `wafer_space/projects/tests/test_tasks.py`

**Step 1: Write the failing test**

Add new test class:

```python
class TestChecksDispatch(TestCase):
    """Test checks_dispatch task."""

    def test_dispatches_pending_checks_under_limit(self):
        """Test pending checks are dispatched when under concurrent limit."""
        # Create a pending check
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )

        with patch("wafer_space.projects.tasks.check_process_job") as mock_task:
            mock_task.delay.return_value = Mock(id="task-123")
            result = checks_dispatch()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.DISPATCHED
        assert check.celery_job_id == "task-123"
        assert result["dispatched"] == 1

    def test_respects_concurrent_limit(self):
        """Test dispatch respects concurrent limit."""
        # Create checks already at limit
        for _ in range(settings.PRECHECK_CONCURRENT_LIMIT):
            ManufacturabilityCheckFactory(
                status=ManufacturabilityCheck.Status.RUNNING
            )
        # Create pending check
        pending = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )

        with patch("wafer_space.projects.tasks.check_process_job") as mock_task:
            result = checks_dispatch()

        pending.refresh_from_db()
        assert pending.status == ManufacturabilityCheck.Status.PENDING
        assert result["dispatched"] == 0
        mock_task.delay.assert_not_called()

    def test_cancelling_counts_toward_limit(self):
        """Test CANCELLING checks count toward concurrent limit."""
        # Create checks in CANCELLING state (Docker still running)
        for _ in range(settings.PRECHECK_CONCURRENT_LIMIT):
            ManufacturabilityCheckFactory(
                status=ManufacturabilityCheck.Status.CANCELLING
            )
        pending = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )

        with patch("wafer_space.projects.tasks.check_process_job") as mock_task:
            result = checks_dispatch()

        pending.refresh_from_db()
        assert pending.status == ManufacturabilityCheck.Status.PENDING
        assert result["dispatched"] == 0
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest wafer_space/projects/tests/test_tasks.py::TestChecksDispatch -v`
Expected: FAIL with import error

**Step 3: Add the task**

In `wafer_space/projects/tasks.py`:

```python
@shared_task(queue="default")
def checks_dispatch() -> dict:
    """Dispatch PENDING checks to Celery queue (respecting concurrent limit).

    CANCELLING checks count toward the limit because their Docker containers
    may still be running.

    Returns:
        dict with 'dispatched' and 'waiting' counts
    """
    from django.conf import settings
    from wafer_space.projects.models import ManufacturabilityCheck

    Status = ManufacturabilityCheck.Status
    concurrent_limit = getattr(settings, "PRECHECK_CONCURRENT_LIMIT", 4)

    # CANCELLING counts because Docker container may still be running
    active_count = ManufacturabilityCheck.objects.filter(
        status__in=[Status.DISPATCHED, Status.RUNNING, Status.CANCELLING]
    ).count()

    pending = ManufacturabilityCheck.objects.filter(
        status=Status.PENDING
    ).order_by("created_at")

    dispatched = 0
    for check in pending:
        if active_count >= concurrent_limit:
            break
        task = check_process_job.delay(check.id)
        check.mark_dispatched(celery_job_id=task.id)
        active_count += 1
        dispatched += 1

    return {"dispatched": dispatched, "waiting": pending.count() - dispatched}
```

**Step 4: Run tests**

Run: `uv run pytest wafer_space/projects/tests/test_tasks.py::TestChecksDispatch -v`
Expected: PASS

**Step 5: Commit**

```bash
git add wafer_space/projects/tasks.py wafer_space/projects/tests/test_tasks.py
git commit -m "feat(tasks): add checks_dispatch single-responsibility task"
```

---

### Task 3.3: Create checks_retry task

**Files:**
- Modify: `wafer_space/projects/tasks.py`
- Test: `wafer_space/projects/tests/test_tasks.py`

**Step 1: Write the failing test**

```python
class TestChecksRetry(TestCase):
    """Test checks_retry task."""

    def test_retries_error_checks_under_limit(self):
        """Test ERROR checks are retried when under retry limit."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.ERROR,
            retry_count=0,
            max_retries=3,
        )

        result = checks_retry()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.PENDING
        assert check.retry_count == 1
        assert result["retried"] == 1

    def test_does_not_retry_exhausted_checks(self):
        """Test ERROR checks at retry limit are not retried."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.ERROR,
            retry_count=3,
            max_retries=3,
        )

        result = checks_retry()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.ERROR
        assert result["exhausted"] == 1
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest wafer_space/projects/tests/test_tasks.py::TestChecksRetry -v`
Expected: FAIL

**Step 3: Add the task**

```python
@shared_task(queue="default")
def checks_retry() -> dict:
    """Move retryable ERROR checks back to PENDING state.

    Returns:
        dict with 'retried' and 'exhausted' counts
    """
    from wafer_space.projects.models import ManufacturabilityCheck

    Status = ManufacturabilityCheck.Status
    retried = 0
    exhausted = 0

    for check in ManufacturabilityCheck.objects.filter(status=Status.ERROR):
        if check.can_retry():
            check.reset_for_retry(reason="Automatic retry after error")
            retried += 1
        else:
            exhausted += 1

    return {"retried": retried, "exhausted": exhausted}
```

**Step 4: Run tests**

Run: `uv run pytest wafer_space/projects/tests/test_tasks.py::TestChecksRetry -v`
Expected: PASS

**Step 5: Commit**

```bash
git add wafer_space/projects/tasks.py wafer_space/projects/tests/test_tasks.py
git commit -m "feat(tasks): add checks_retry single-responsibility task"
```

---

### Task 3.4: Create checks_create task

**Files:**
- Modify: `wafer_space/projects/tasks.py`
- Test: `wafer_space/projects/tests/test_tasks.py`

**Step 1: Write the failing test**

```python
class TestChecksCreate(TestCase):
    """Test checks_create task."""

    def test_creates_check_for_verified_file(self):
        """Test check is created for verified file without existing check."""
        project_file = ProjectFileFactory(
            is_active=True,
            hash_verified=True,
            download_status=ProjectFile.DownloadStatus.COMPLETED,
        )
        # Ensure no check exists
        assert not hasattr(project_file, "manufacturability_check")

        result = checks_create()

        assert result["created"] == 1
        project_file.refresh_from_db()
        assert hasattr(project_file, "manufacturability_check")
        assert project_file.manufacturability_check.status == ManufacturabilityCheck.Status.PENDING

    def test_does_not_create_for_unverified_file(self):
        """Test no check created for unverified file."""
        project_file = ProjectFileFactory(
            is_active=True,
            hash_verified=False,
        )

        result = checks_create()

        assert result["created"] == 0

    def test_does_not_create_duplicate_check(self):
        """Test no duplicate check created if one exists."""
        check = ManufacturabilityCheckFactory()
        project_file = check.project_file
        project_file.is_active = True
        project_file.hash_verified = True
        project_file.save()

        result = checks_create()

        assert result["created"] == 0
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest wafer_space/projects/tests/test_tasks.py::TestChecksCreate -v`
Expected: FAIL

**Step 3: Add the task**

```python
@shared_task(queue="default")
def checks_create() -> dict:
    """Create ManufacturabilityChecks for verified downloads that need them.

    Returns:
        dict with 'created' count
    """
    from wafer_space.projects.models import ManufacturabilityCheck, ProjectFile

    created = 0

    # Find active, verified files without a check
    files_needing_checks = ProjectFile.objects.filter(
        is_active=True,
        hash_verified=True,
    ).exclude(
        manufacturability_check__isnull=False
    )

    for project_file in files_needing_checks:
        ManufacturabilityCheck.objects.create(
            project=project_file.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        created += 1

    return {"created": created}
```

**Step 4: Run tests**

Run: `uv run pytest wafer_space/projects/tests/test_tasks.py::TestChecksCreate -v`
Expected: PASS

**Step 5: Commit**

```bash
git add wafer_space/projects/tasks.py wafer_space/projects/tests/test_tasks.py
git commit -m "feat(tasks): add checks_create single-responsibility task"
```

---

### Task 3.5: Create checks_cancelling task

**Files:**
- Modify: `wafer_space/projects/tasks.py`
- Test: `wafer_space/projects/tests/test_tasks.py`

**Step 1: Write the failing test**

```python
class TestChecksCancelling(TestCase):
    """Test checks_cancelling task."""

    @patch("wafer_space.projects.tasks.docker")
    @patch("wafer_space.projects.tasks.celery_app")
    def test_completes_cancellation_with_cleanup(self, mock_celery, mock_docker):
        """Test CANCELLING check completes after cleanup."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.CANCELLING,
            celery_job_id="task-123",
            docker_container_id="container-abc",
        )

        mock_container = Mock()
        mock_container.status = "running"
        mock_docker.from_env.return_value.containers.get.return_value = mock_container

        result = checks_cancelling()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLED
        assert check.celery_job_id == ""
        assert check.docker_container_id == ""
        mock_celery.control.revoke.assert_called_once_with("task-123", terminate=True)
        mock_container.stop.assert_called_once()
        mock_container.remove.assert_called_once()
        assert result["completed"] == 1

    @patch("wafer_space.projects.tasks.docker")
    @patch("wafer_space.projects.tasks.celery_app")
    def test_handles_missing_container(self, mock_celery, mock_docker):
        """Test cleanup handles already-removed container."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.CANCELLING,
            docker_container_id="gone-container",
        )

        import docker.errors
        mock_docker.from_env.return_value.containers.get.side_effect = docker.errors.NotFound("not found")

        result = checks_cancelling()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLED
        assert result["completed"] == 1
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest wafer_space/projects/tests/test_tasks.py::TestChecksCancelling -v`
Expected: FAIL

**Step 3: Add the task**

```python
@shared_task(queue="docker-ephemeral")
def checks_cancelling() -> dict:
    """Complete cancellation for checks in CANCELLING state.

    This task performs all cleanup before transitioning to CANCELLED,
    ensuring Docker containers are stopped before releasing the slot.

    Returns:
        dict with 'completed' and 'failed' counts
    """
    import docker
    import docker.errors

    from wafer_space.projects.models import ManufacturabilityCheck

    Status = ManufacturabilityCheck.Status
    completed = 0
    failed = 0

    client = docker.from_env()

    for check in ManufacturabilityCheck.objects.filter(status=Status.CANCELLING):
        try:
            # Step 1: Revoke Celery task
            if check.celery_job_id:
                celery_app.control.revoke(check.celery_job_id, terminate=True)
                check.celery_job_id = ""
                check.save(update_fields=["celery_job_id"])

            # Step 2: Stop and remove Docker container
            if check.docker_container_id:
                try:
                    container = client.containers.get(check.docker_container_id)
                    if container.status == "running":
                        container.stop(timeout=10)
                    container.remove(force=True)
                except docker.errors.NotFound:
                    pass  # Already gone

                check.docker_container_id = ""
                check.save(update_fields=["docker_container_id"])

            # Step 3: Complete the transition
            check.mark_cancelled()
            completed += 1

        except Exception as exc:
            logger.exception("Failed to complete cancellation for check %s: %s", check.id, exc)
            failed += 1

    return {"completed": completed, "failed": failed}
```

**Step 4: Run tests**

Run: `uv run pytest wafer_space/projects/tests/test_tasks.py::TestChecksCancelling -v`
Expected: PASS

**Step 5: Commit**

```bash
git add wafer_space/projects/tasks.py wafer_space/projects/tests/test_tasks.py
git commit -m "feat(tasks): add checks_cancelling for async cleanup"
```

---

### Task 3.6: Create checks_cleanup_orphaned_dispatch task

**Files:**
- Modify: `wafer_space/projects/tasks.py`
- Test: `wafer_space/projects/tests/test_tasks.py`

**Step 1: Write the failing test**

```python
class TestChecksCleanupOrphanedDispatch(TestCase):
    """Test checks_cleanup_orphaned_dispatch task."""

    @patch("wafer_space.projects.tasks.is_check_task_queued")
    def test_marks_lost_dispatched_as_error(self, mock_is_queued):
        """Test DISPATCHED check with lost task is marked ERROR."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.DISPATCHED,
            celery_job_id="lost-task",
        )
        mock_is_queued.return_value = False

        result = checks_cleanup_orphaned_dispatch()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.ERROR
        assert "lost from queue" in check.error_message
        assert result["orphaned"] == 1

    @patch("wafer_space.projects.tasks.is_check_task_queued")
    def test_leaves_valid_dispatched_alone(self, mock_is_queued):
        """Test DISPATCHED check with valid task is not modified."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.DISPATCHED,
        )
        mock_is_queued.return_value = True

        result = checks_cleanup_orphaned_dispatch()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.DISPATCHED
        assert result["verified"] == 1
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest wafer_space/projects/tests/test_tasks.py::TestChecksCleanupOrphanedDispatch -v`
Expected: FAIL

**Step 3: Add the task**

```python
@shared_task(queue="default")
def checks_cleanup_orphaned_dispatch() -> dict:
    """Mark DISPATCHED checks with lost Celery tasks as ERROR.

    Returns:
        dict with 'orphaned' and 'verified' counts
    """
    from wafer_space.projects.models import ManufacturabilityCheck

    Status = ManufacturabilityCheck.Status
    orphaned = 0
    verified = 0

    for check in ManufacturabilityCheck.objects.filter(status=Status.DISPATCHED):
        if is_check_task_queued(check):
            verified += 1
        else:
            check.mark_error(
                error_message="Celery task lost from queue (will retry if allowed)"
            )
            orphaned += 1

    return {"orphaned": orphaned, "verified": verified}
```

**Step 4: Run tests**

Run: `uv run pytest wafer_space/projects/tests/test_tasks.py::TestChecksCleanupOrphanedDispatch -v`
Expected: PASS

**Step 5: Commit**

```bash
git add wafer_space/projects/tasks.py wafer_space/projects/tests/test_tasks.py
git commit -m "feat(tasks): add checks_cleanup_orphaned_dispatch task"
```

---

### Task 3.7: Create checks_cleanup_orphaned_processing task

**Files:**
- Modify: `wafer_space/projects/tasks.py`
- Test: `wafer_space/projects/tests/test_tasks.py`

**Step 1: Write the failing test**

```python
class TestChecksCleanupOrphanedProcessing(TestCase):
    """Test checks_cleanup_orphaned_processing task."""

    @patch("wafer_space.projects.tasks.is_check_task_actively_running")
    def test_marks_dead_running_as_error(self, mock_is_running):
        """Test RUNNING check with dead worker is marked ERROR."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING,
            celery_worker_pid=12345,
            celery_worker_hostname="worker@host",
        )
        mock_is_running.return_value = False

        result = checks_cleanup_orphaned_processing()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.ERROR
        assert "Worker process died" in check.error_message
        assert check.celery_worker_pid is None
        assert result["orphaned"] == 1

    @patch("wafer_space.projects.tasks.is_check_task_actively_running")
    def test_leaves_valid_running_alone(self, mock_is_running):
        """Test RUNNING check with active worker is not modified."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING,
        )
        mock_is_running.return_value = True

        result = checks_cleanup_orphaned_processing()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.RUNNING
        assert result["verified"] == 1
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest wafer_space/projects/tests/test_tasks.py::TestChecksCleanupOrphanedProcessing -v`
Expected: FAIL

**Step 3: Add the task**

```python
@shared_task(queue="default")
def checks_cleanup_orphaned_processing() -> dict:
    """Mark RUNNING checks with dead workers as ERROR.

    Returns:
        dict with 'orphaned' and 'verified' counts
    """
    from wafer_space.projects.models import ManufacturabilityCheck

    Status = ManufacturabilityCheck.Status
    orphaned = 0
    verified = 0

    for check in ManufacturabilityCheck.objects.filter(status=Status.RUNNING):
        if is_check_task_actively_running(check):
            verified += 1
        else:
            check.mark_error(
                error_message="Worker process died (will retry if allowed)"
            )
            check.celery_worker_pid = None
            check.celery_worker_hostname = ""
            check.save(update_fields=["celery_worker_pid", "celery_worker_hostname"])
            orphaned += 1

    return {"orphaned": orphaned, "verified": verified}
```

**Step 4: Run tests**

Run: `uv run pytest wafer_space/projects/tests/test_tasks.py::TestChecksCleanupOrphanedProcessing -v`
Expected: PASS

**Step 5: Commit**

```bash
git add wafer_space/projects/tasks.py wafer_space/projects/tests/test_tasks.py
git commit -m "feat(tasks): add checks_cleanup_orphaned_processing task"
```

---

### Task 3.8: Rename cleanup_orphaned_precheck_containers to checks_cleanup_orphaned_docker

**Files:**
- Modify: `wafer_space/projects/tasks.py:3176`
- Test: `wafer_space/projects/tests/test_tasks.py`

**Step 1: Find and rename**

In `wafer_space/projects/tasks.py`, find `cleanup_orphaned_precheck_containers` (line 3176) and rename to `checks_cleanup_orphaned_docker`.

Update the queue to `docker-ephemeral`:

```python
@shared_task(bind=True, queue="docker-ephemeral")
def checks_cleanup_orphaned_docker(self) -> dict:
    """Remove Docker containers not linked to active checks (fallback cleanup).

    Starts from Docker (source of truth) and validates against database.

    Returns:
        dict with 'containers_scanned' and 'removed' counts
    """
```

**Step 2: Update implementation to start from Docker**

Update the implementation to scan containers first, then check database:

```python
@shared_task(bind=True, queue="docker-ephemeral")
def checks_cleanup_orphaned_docker(self) -> dict:
    """Remove Docker containers not linked to active checks (fallback cleanup).

    Starts from Docker (source of truth) and validates against database.
    """
    import docker
    import docker.errors
    from wafer_space.projects.models import ManufacturabilityCheck

    Status = ManufacturabilityCheck.Status
    client = docker.from_env()

    # Get all containers with our label
    containers = client.containers.list(
        all=True,
        filters={"label": "wafer.space.service=manufacturability-check"},
    )

    removed = 0
    for container in containers:
        check_id = container.labels.get("wafer.space.check_id")

        # No check_id label = definitely orphaned
        if not check_id:
            _stop_and_remove_container(container)
            removed += 1
            continue

        # Look up the check
        try:
            check = ManufacturabilityCheck.objects.get(id=check_id)
        except ManufacturabilityCheck.DoesNotExist:
            # Check deleted = orphaned
            _stop_and_remove_container(container)
            removed += 1
            continue

        # Check exists - is it in an active state?
        # CANCELLING containers are handled by checks_cancelling, not here
        if check.status not in [Status.DISPATCHED, Status.RUNNING, Status.CANCELLING]:
            # Check is FINISHED/ERROR/CANCELLED but container still exists
            _stop_and_remove_container(container)
            removed += 1

    return {"containers_scanned": len(containers), "removed": removed}


def _stop_and_remove_container(container) -> None:
    """Stop and remove a Docker container safely."""
    try:
        if container.status == "running":
            container.stop(timeout=10)
        container.remove(force=True)
    except Exception:
        logger.exception("Failed to remove container %s", container.id)
```

**Step 3: Update tests**

Update test class name and assertions.

**Step 4: Run tests**

Run: `make test`
Expected: PASS

**Step 5: Commit**

```bash
git add wafer_space/projects/tasks.py wafer_space/projects/tests/test_tasks.py
git commit -m "refactor(tasks): rename cleanup_orphaned_precheck_containers to checks_cleanup_orphaned_docker"
```

---

### Task 3.9: Delete process_manufacturability_check_queue monolith

**Files:**
- Modify: `wafer_space/projects/tasks.py` (delete function at line 3096)
- Delete: Tests for `TestProcessManufacturabilityCheckQueue`

**Step 1: Delete the monolith function**

In `wafer_space/projects/tasks.py`, delete the entire `process_manufacturability_check_queue` function (starts around line 3096).

Also delete any helper functions that were only used by this monolith:
- `_handle_dispatched_checks`
- `_handle_running_checks`
- `_handle_error_checks`
- `_handle_pending_checks`

**Step 2: Delete the tests**

In `wafer_space/projects/tests/test_tasks.py`, delete the entire `TestProcessManufacturabilityCheckQueue` class (starts at line 1304).

**Step 3: Run lint and tests**

Run: `make lint-fix && make lint && make type-check && make test`
Expected: PASS

**Step 4: Commit**

```bash
git add wafer_space/projects/tasks.py wafer_space/projects/tests/test_tasks.py
git commit -m "refactor(tasks): delete process_manufacturability_check_queue monolith"
```

---

## Phase 4: Update Settings and Celery Beat Schedule

### Task 4.1: Update CELERY_BEAT_SCHEDULE in base.py

**Files:**
- Modify: `config/settings/base.py:449-458`

**Step 1: Update the schedule**

```python
CELERY_BEAT_SCHEDULE = {
    # Download recovery
    "ensure-download-tasks-queued": {
        "task": "wafer_space.projects.tasks.ensure_download_tasks_queued",
        "schedule": DOWNLOAD_STATE_CHECK_INTERVAL_SECONDS,
    },
    # Manufacturability check lifecycle
    "checks-create": {
        "task": "wafer_space.projects.tasks.checks_create",
        "schedule": 30.0,
    },
    "checks-dispatch": {
        "task": "wafer_space.projects.tasks.checks_dispatch",
        "schedule": 30.0,
    },
    "checks-retry": {
        "task": "wafer_space.projects.tasks.checks_retry",
        "schedule": 60.0,
    },
    # Cancellation cleanup (fast - critical for releasing slots)
    "checks-cancelling": {
        "task": "wafer_space.projects.tasks.checks_cancelling",
        "schedule": 15.0,
    },
    # Orphan detection
    "checks-cleanup-orphaned-dispatch": {
        "task": "wafer_space.projects.tasks.checks_cleanup_orphaned_dispatch",
        "schedule": 60.0,
    },
    "checks-cleanup-orphaned-processing": {
        "task": "wafer_space.projects.tasks.checks_cleanup_orphaned_processing",
        "schedule": 60.0,
    },
    "checks-cleanup-orphaned-docker": {
        "task": "wafer_space.projects.tasks.checks_cleanup_orphaned_docker",
        "schedule": 300.0,
    },
}
```

**Step 2: Run lint**

Run: `make lint-fix && make lint`
Expected: PASS

**Step 3: Commit**

```bash
git add config/settings/base.py
git commit -m "feat(settings): update CELERY_BEAT_SCHEDULE with new task names"
```

---

### Task 4.2: Update CELERY_BEAT_SCHEDULE in dev.py

**Files:**
- Modify: `config/settings/dev.py:86-99`

**Step 1: Update dev.py schedule**

Apply same changes as base.py (dev.py overrides base.py schedule).

**Step 2: Run tests**

Run: `make test`
Expected: PASS

**Step 3: Commit**

```bash
git add config/settings/dev.py
git commit -m "feat(settings): update dev.py CELERY_BEAT_SCHEDULE"
```

---

## Phase 5: Deployment Updates

### Task 5.1: Rename systemd service files for new queue names

**Files:**
- Rename: `deployment/systemd/django-celery-manufacturability.service` → `django-celery-docker-persistent.service`
- Rename: `deployment/systemd/django-celery-maintenance.service` → `django-celery-docker-ephemeral.service`

**Step 1: Rename and update manufacturability service**

```bash
mv deployment/systemd/django-celery-manufacturability.service deployment/systemd/django-celery-docker-persistent.service
```

Update the file content:
- Description: `platform.wafer.space Celery Worker (Docker Persistent)`
- `--queues=docker-persistent`
- `--hostname=docker-persistent@%h`
- RuntimeDirectory/LogsDirectory: `platform.wafer.space-celery-docker-persistent`

**Step 2: Rename and update maintenance service**

```bash
mv deployment/systemd/django-celery-maintenance.service deployment/systemd/django-celery-docker-ephemeral.service
```

Update the file content:
- Description: `platform.wafer.space Celery Worker (Docker Ephemeral)`
- `--queues=docker-ephemeral`
- `--hostname=docker-ephemeral@%h`
- RuntimeDirectory/LogsDirectory: `platform.wafer.space-celery-docker-ephemeral`

**Step 3: Commit**

```bash
git add deployment/systemd/
git commit -m "refactor(deployment): rename systemd services for new queue names"
```

---

### Task 5.2: Update docs/systemd-services.md

**Files:**
- Modify: `docs/systemd-services.md`

**Step 1: Update documentation**

Update all references to queue names:
- `manufacturability` → `docker-persistent`
- `maintenance` → `docker-ephemeral`

Update task mappings table with new task names.

Update architecture diagram.

**Step 2: Commit**

```bash
git add docs/systemd-services.md
git commit -m "docs: update systemd-services.md for new queue names and tasks"
```

---

### Task 5.3: Update deployment install script

**Files:**
- Modify: `deployment/systemd/install.sh` (if exists)

**Step 1: Update service names in script**

Update any references to old service names.

**Step 2: Commit**

```bash
git add deployment/
git commit -m "refactor(deployment): update install script for renamed services"
```

---

## Phase 6: Final Cleanup and Verification

### Task 6.1: Run full test suite

**Step 1: Run all checks**

```bash
make lint-fix && make lint && make type-check && make test
```

Expected: All pass

**Step 2: Commit any fixes**

---

### Task 6.2: Update design document status

**Files:**
- Modify: `docs/plans/2025-11-30-manufacturability-check-task-restructure.md`

**Step 1: Add implementation status**

Add at the top: `**Status:** Implemented`

**Step 2: Commit**

```bash
git add docs/plans/
git commit -m "docs: mark manufacturability check restructure as implemented"
```

---

## Summary of Changes

### Files Created
- `wafer_space/projects/migrations/XXXX_add_cancelling_status.py`

### Files Modified
- `wafer_space/projects/models.py` (CANCELLING state, mark_cancelling, updated mark_cancelled)
- `wafer_space/projects/tasks.py` (8 new tasks, renamed 2, deleted monolith)
- `wafer_space/projects/services.py` (deleted ManufacturabilityService)
- `wafer_space/projects/views.py` (updated cancel view)
- `config/settings/base.py` (new CELERY_BEAT_SCHEDULE)
- `config/settings/dev.py` (new CELERY_BEAT_SCHEDULE)
- `deployment/systemd/*.service` (renamed for new queues)
- `docs/systemd-services.md` (updated documentation)

### Files Deleted (content)
- `ManufacturabilityService` class from services.py
- `process_manufacturability_check_queue` from tasks.py
- Old test classes for deleted functionality

### Key Architectural Changes
1. **CANCELLING state** - Intermediate state for async cleanup
2. **Single-responsibility tasks** - 8 focused tasks replace 1 monolith
3. **Queue separation by Docker access** - `default`, `docker-ephemeral`, `docker-persistent`
4. **Direct model access** - Views call model methods, no service layer
