# Celery Docker Polling Architecture Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the long-running `check_process_job` task with a stateless polling architecture where all tasks are short-running (<60s) and Celery restarts don't affect running Docker containers.

**Architecture:** Beat tasks orchestrate state transitions without touching Docker. Work tasks (`do_*`) perform Docker operations and are queued by beat tasks. A separate `ManufacturabilityCheckTask` table tracks pending Celery tasks to prevent duplicate queuing.

**Tech Stack:** Django 5.2+, Celery with PostgreSQL broker, Docker SDK for Python

**Reference:** See `docs/plans/2025-12-05-celery-docker-polling-architecture-design.md` for full design.

---

## Phase 1: Status Enum Updates

### Task 1.1: Add New Status Values to Enum

**Files:**
- Modify: `wafer_space/projects/models.py` (ManufacturabilityCheck.Status enum ~line 1120)
- Test: `wafer_space/projects/tests/test_models.py`

**Step 1: Write the failing test**

Add to `test_models.py`:

```python
class TestManufacturabilityCheckStatusValues:
    """Test new status values exist."""

    def test_dispatching_status_exists(self) -> None:
        """DISPATCHING status should exist for image pulling phase."""
        assert ManufacturabilityCheck.Status.DISPATCHING == "dispatching"

    def test_starting_status_exists(self) -> None:
        """STARTING status should exist for container creation phase."""
        assert ManufacturabilityCheck.Status.STARTING == "starting"

    def test_analyzing_status_exists(self) -> None:
        """ANALYZING status should exist for post-container log analysis."""
        assert ManufacturabilityCheck.Status.ANALYZING == "analyzing"
```

**Step 2: Run test to verify it fails**

Run: `make test ARGS="wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckStatusValues -v"`

Expected: FAIL with `AttributeError: type object 'Status' has no attribute 'DISPATCHING'`

**Step 3: Write minimal implementation**

In `wafer_space/projects/models.py`, update the Status enum (around line 1120):

```python
class Status(models.TextChoices):
    PENDING = "pending", "Pending"
    DISPATCHING = "dispatching", "Dispatching"  # NEW: Image being pulled
    STARTING = "starting", "Starting"            # NEW: Container being created
    RUNNING = "running", "Running"
    ANALYZING = "analyzing", "Analyzing"         # NEW: Logs being analyzed
    FINISHED = "finished", "Finished"
    ERROR = "error", "Error"
    CANCELLING = "cancelling", "Cancelling"
    CANCELLED = "cancelled", "Cancelled"
```

Note: Remove `DISPATCHED` - it's replaced by `DISPATCHING`.

**Step 4: Run test to verify it passes**

Run: `make test ARGS="wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckStatusValues -v"`

Expected: PASS

**Step 5: Commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/models.py wafer_space/projects/tests/test_models.py
git commit -m "feat(models): add DISPATCHING, STARTING, ANALYZING status values"
```

---

### Task 1.2: Add Status Classification Methods

**Files:**
- Modify: `wafer_space/projects/models.py` (Status enum)
- Test: `wafer_space/projects/tests/test_models.py`

**Step 1: Write the failing tests**

```python
class TestManufacturabilityCheckStatusClassification:
    """Test status classification methods."""

    def test_active_returns_processing_statuses(self) -> None:
        """active() returns statuses where check is actively being processed."""
        active = ManufacturabilityCheck.Status.active()
        assert ManufacturabilityCheck.Status.DISPATCHING in active
        assert ManufacturabilityCheck.Status.STARTING in active
        assert ManufacturabilityCheck.Status.RUNNING in active
        assert ManufacturabilityCheck.Status.ANALYZING in active
        assert ManufacturabilityCheck.Status.CANCELLING in active
        # These should NOT be in active:
        assert ManufacturabilityCheck.Status.PENDING not in active
        assert ManufacturabilityCheck.Status.FINISHED not in active

    def test_terminal_returns_completion_statuses(self) -> None:
        """terminal() returns statuses representing completion."""
        terminal = ManufacturabilityCheck.Status.terminal()
        assert ManufacturabilityCheck.Status.FINISHED in terminal
        assert ManufacturabilityCheck.Status.CANCELLED in terminal
        # These should NOT be in terminal:
        assert ManufacturabilityCheck.Status.PENDING not in terminal
        assert ManufacturabilityCheck.Status.RUNNING not in terminal
        assert ManufacturabilityCheck.Status.ERROR not in terminal
```

**Step 2: Run test to verify it fails**

Run: `make test ARGS="wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckStatusClassification -v"`

Expected: FAIL with `AttributeError: type object 'Status' has no attribute 'active'`

**Step 3: Write minimal implementation**

Add methods to the Status enum in `wafer_space/projects/models.py`:

```python
class Status(models.TextChoices):
    PENDING = "pending", "Pending"
    DISPATCHING = "dispatching", "Dispatching"
    STARTING = "starting", "Starting"
    RUNNING = "running", "Running"
    ANALYZING = "analyzing", "Analyzing"
    FINISHED = "finished", "Finished"
    ERROR = "error", "Error"
    CANCELLING = "cancelling", "Cancelling"
    CANCELLED = "cancelled", "Cancelled"

    @classmethod
    def active(cls) -> list[str]:
        """Statuses that count toward server concurrent limit.

        These statuses indicate a check is actively using Docker server resources
        (container exists or is being created).
        """
        return [cls.DISPATCHING, cls.STARTING, cls.RUNNING, cls.CANCELLING]

    @classmethod
    def working(cls) -> list[str]:
        """Statuses where check is actively being processed.

        These statuses indicate work is happening - either on Docker or analysis.
        """
        return [
            cls.DISPATCHING,
            cls.STARTING,
            cls.RUNNING,
            cls.ANALYZING,
            cls.CANCELLING,
        ]

    @classmethod
    def terminal(cls) -> list[str]:
        """Statuses that represent completion (success or failure)."""
        return [cls.FINISHED, cls.CANCELLED]
```

**Step 4: Run test to verify it passes**

Run: `make test ARGS="wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckStatusClassification -v"`

Expected: PASS

**Step 5: Commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/models.py wafer_space/projects/tests/test_models.py
git commit -m "feat(models): add active(), working(), terminal() status classification methods"
```

---

### Task 1.3: Update ALLOWED_TRANSITIONS for New Statuses

**Files:**
- Modify: `wafer_space/projects/models.py` (ALLOWED_TRANSITIONS dict)
- Test: `wafer_space/projects/tests/test_models.py`

**Step 1: Write the failing tests**

```python
class TestManufacturabilityCheckNewTransitions:
    """Test new state transitions are allowed."""

    @pytest.fixture
    def pending_check(self) -> ManufacturabilityCheck:
        return ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.PENDING)

    @pytest.fixture
    def dispatching_check(self) -> ManufacturabilityCheck:
        return ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.DISPATCHING)

    @pytest.fixture
    def starting_check(self) -> ManufacturabilityCheck:
        return ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.STARTING)

    @pytest.fixture
    def running_check(self) -> ManufacturabilityCheck:
        return ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.RUNNING)

    @pytest.fixture
    def analyzing_check(self) -> ManufacturabilityCheck:
        return ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.ANALYZING)

    def test_pending_can_transition_to_dispatching(self, pending_check: ManufacturabilityCheck) -> None:
        """PENDING -> DISPATCHING is allowed."""
        assert pending_check.can_transition_to(ManufacturabilityCheck.Status.DISPATCHING)

    def test_dispatching_can_transition_to_starting(self, dispatching_check: ManufacturabilityCheck) -> None:
        """DISPATCHING -> STARTING is allowed."""
        assert dispatching_check.can_transition_to(ManufacturabilityCheck.Status.STARTING)

    def test_starting_can_transition_to_running(self, starting_check: ManufacturabilityCheck) -> None:
        """STARTING -> RUNNING is allowed."""
        assert starting_check.can_transition_to(ManufacturabilityCheck.Status.RUNNING)

    def test_running_can_transition_to_analyzing(self, running_check: ManufacturabilityCheck) -> None:
        """RUNNING -> ANALYZING is allowed."""
        assert running_check.can_transition_to(ManufacturabilityCheck.Status.ANALYZING)

    def test_analyzing_can_transition_to_finished(self, analyzing_check: ManufacturabilityCheck) -> None:
        """ANALYZING -> FINISHED is allowed."""
        assert analyzing_check.can_transition_to(ManufacturabilityCheck.Status.FINISHED)

    def test_analyzing_can_transition_to_error(self, analyzing_check: ManufacturabilityCheck) -> None:
        """ANALYZING -> ERROR is allowed."""
        assert analyzing_check.can_transition_to(ManufacturabilityCheck.Status.ERROR)
```

**Step 2: Run test to verify it fails**

Run: `make test ARGS="wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckNewTransitions -v"`

Expected: FAIL (transitions not allowed yet)

**Step 3: Write minimal implementation**

Update `ALLOWED_TRANSITIONS` in `wafer_space/projects/models.py`:

```python
ALLOWED_TRANSITIONS: ClassVar[dict[str, list[str]]] = {
    Status.PENDING: [Status.DISPATCHING, Status.ERROR, Status.CANCELLING],
    Status.DISPATCHING: [Status.STARTING, Status.ERROR, Status.CANCELLING],
    Status.STARTING: [Status.RUNNING, Status.ERROR, Status.CANCELLING],
    Status.RUNNING: [Status.ANALYZING, Status.ERROR, Status.CANCELLING],
    Status.ANALYZING: [Status.FINISHED, Status.ERROR, Status.CANCELLING],
    Status.FINISHED: [],  # Terminal
    Status.ERROR: [Status.PENDING],  # Retry
    Status.CANCELLING: [Status.CANCELLED],
    Status.CANCELLED: [],  # Terminal
}
```

**Step 4: Run test to verify it passes**

Run: `make test ARGS="wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckNewTransitions -v"`

Expected: PASS

**Step 5: Commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/models.py wafer_space/projects/tests/test_models.py
git commit -m "feat(models): update ALLOWED_TRANSITIONS for new status flow"
```

---

## Phase 2: New Model Fields

### Task 2.1: Add docker_server_id Field

**Files:**
- Modify: `wafer_space/projects/models.py`
- Test: `wafer_space/projects/tests/test_models.py`

**Step 1: Write the failing test**

```python
class TestManufacturabilityCheckServerField:
    """Test docker_server_id field."""

    def test_docker_server_id_field_exists(self) -> None:
        """Check should have docker_server_id field."""
        check = ManufacturabilityCheckFactory()
        assert hasattr(check, "docker_server_id")
        assert check.docker_server_id is None  # Default is null

    def test_docker_server_id_can_be_set(self) -> None:
        """docker_server_id can store server identifier."""
        check = ManufacturabilityCheckFactory(docker_server_id="local")
        assert check.docker_server_id == "local"
```

**Step 2: Run test to verify it fails**

Run: `make test ARGS="wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckServerField -v"`

Expected: FAIL with `TypeError: ManufacturabilityCheckFactory() got unexpected keyword argument 'docker_server_id'`

**Step 3: Write minimal implementation**

Add field to ManufacturabilityCheck model:

```python
docker_server_id = models.CharField(
    max_length=64,
    null=True,
    blank=True,
    help_text="ID of Docker server running this check (from DOCKER_SERVERS setting)",
)
```

Update factory in `wafer_space/projects/tests/factories.py`:

```python
docker_server_id = None
```

**Step 4: Run test to verify it passes**

Run: `make test ARGS="wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckServerField -v"`

Expected: PASS

**Step 5: Create and apply migration**

```bash
uv run python manage.py makemigrations projects --name add_docker_server_id
uv run python manage.py migrate
```

**Step 6: Commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/models.py wafer_space/projects/migrations/ wafer_space/projects/tests/
git commit -m "feat(models): add docker_server_id field to ManufacturabilityCheck"
```

---

### Task 2.2: Add Granular Timestamp Fields

**Files:**
- Modify: `wafer_space/projects/models.py`
- Test: `wafer_space/projects/tests/test_models.py`

**Step 1: Write the failing test**

```python
class TestManufacturabilityCheckTimestampFields:
    """Test new granular timestamp fields."""

    def test_dispatching_started_at_field_exists(self) -> None:
        """Check should have dispatching_started_at field."""
        check = ManufacturabilityCheckFactory()
        assert hasattr(check, "dispatching_started_at")
        assert check.dispatching_started_at is None

    def test_starting_started_at_field_exists(self) -> None:
        """Check should have starting_started_at field."""
        check = ManufacturabilityCheckFactory()
        assert hasattr(check, "starting_started_at")
        assert check.starting_started_at is None

    def test_container_started_at_field_exists(self) -> None:
        """Check should have container_started_at field (renamed from docker_container_started_at)."""
        check = ManufacturabilityCheckFactory()
        assert hasattr(check, "container_started_at")
        assert check.container_started_at is None

    def test_container_finished_at_field_exists(self) -> None:
        """Check should have container_finished_at field."""
        check = ManufacturabilityCheckFactory()
        assert hasattr(check, "container_finished_at")
        assert check.container_finished_at is None

    def test_analysis_completed_at_field_exists(self) -> None:
        """Check should have analysis_completed_at field."""
        check = ManufacturabilityCheckFactory()
        assert hasattr(check, "analysis_completed_at")
        assert check.analysis_completed_at is None
```

**Step 2: Run test to verify it fails**

Run: `make test ARGS="wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckTimestampFields -v"`

Expected: FAIL

**Step 3: Write minimal implementation**

Add fields to ManufacturabilityCheck model:

```python
# Granular timestamps for each phase
dispatching_started_at = models.DateTimeField(
    null=True,
    blank=True,
    help_text="When check entered DISPATCHING (image pull started)",
)
starting_started_at = models.DateTimeField(
    null=True,
    blank=True,
    help_text="When check entered STARTING (container creation started)",
)
container_started_at = models.DateTimeField(
    null=True,
    blank=True,
    help_text="When container was confirmed running",
)
container_finished_at = models.DateTimeField(
    null=True,
    blank=True,
    help_text="When container exited",
)
analysis_completed_at = models.DateTimeField(
    null=True,
    blank=True,
    help_text="When log analysis completed",
)
```

Note: Keep the existing `docker_container_started_at` for backwards compatibility during migration, then rename in a later task.

**Step 4: Run test to verify it passes**

Run: `make test ARGS="wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckTimestampFields -v"`

Expected: PASS

**Step 5: Create and apply migration**

```bash
uv run python manage.py makemigrations projects --name add_granular_timestamps
uv run python manage.py migrate
```

**Step 6: Commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/models.py wafer_space/projects/migrations/ wafer_space/projects/tests/
git commit -m "feat(models): add granular timestamp fields for each phase"
```

---

### Task 2.3: Add docker_exit_code and logs_downloaded_until Fields

**Files:**
- Modify: `wafer_space/projects/models.py`
- Test: `wafer_space/projects/tests/test_models.py`

**Step 1: Write the failing test**

```python
class TestManufacturabilityCheckDockerFields:
    """Test Docker-related fields."""

    def test_docker_exit_code_field_exists(self) -> None:
        """Check should have docker_exit_code field."""
        check = ManufacturabilityCheckFactory()
        assert hasattr(check, "docker_exit_code")
        assert check.docker_exit_code is None

    def test_logs_downloaded_until_field_exists(self) -> None:
        """Check should have logs_downloaded_until field for incremental log fetch."""
        check = ManufacturabilityCheckFactory()
        assert hasattr(check, "logs_downloaded_until")
        assert check.logs_downloaded_until is None

    def test_logs_downloaded_until_stores_float(self) -> None:
        """logs_downloaded_until stores Unix timestamp with nanosecond precision."""
        check = ManufacturabilityCheckFactory()
        check.logs_downloaded_until = 1733400000.123456789
        check.save()
        check.refresh_from_db()
        # Float precision may vary, but should be close
        assert abs(check.logs_downloaded_until - 1733400000.123456789) < 0.000001
```

**Step 2: Run test to verify it fails**

Run: `make test ARGS="wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckDockerFields -v"`

Expected: FAIL

**Step 3: Write minimal implementation**

Add fields to ManufacturabilityCheck model:

```python
docker_exit_code = models.IntegerField(
    null=True,
    blank=True,
    help_text="Exit code from Docker container",
)
logs_downloaded_until = models.FloatField(
    null=True,
    blank=True,
    help_text="Unix timestamp (with nanoseconds) for incremental log fetch",
)
```

**Step 4: Run test to verify it passes**

Run: `make test ARGS="wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckDockerFields -v"`

Expected: PASS

**Step 5: Create and apply migration**

```bash
uv run python manage.py makemigrations projects --name add_docker_exit_code_and_logs_until
uv run python manage.py migrate
```

**Step 6: Commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/models.py wafer_space/projects/migrations/ wafer_space/projects/tests/
git commit -m "feat(models): add docker_exit_code and logs_downloaded_until fields"
```

---

### Task 2.4: Create ManufacturabilityCheckTask Model

**Files:**
- Modify: `wafer_space/projects/models.py`
- Create: `wafer_space/projects/tests/test_check_task_model.py`

**Step 1: Write the failing test**

Create new test file `wafer_space/projects/tests/test_check_task_model.py`:

```python
"""Tests for ManufacturabilityCheckTask model."""

from __future__ import annotations

import pytest
from django.db import IntegrityError

from wafer_space.projects.models import ManufacturabilityCheck, ManufacturabilityCheckTask
from wafer_space.projects.tests.factories import ManufacturabilityCheckFactory

pytestmark = pytest.mark.django_db


class TestManufacturabilityCheckTaskModel:
    """Test ManufacturabilityCheckTask model."""

    def test_can_create_task_for_check(self) -> None:
        """Can create a task tracking row for a check."""
        check = ManufacturabilityCheckFactory()
        task = ManufacturabilityCheckTask.objects.create(
            check=check,
            task_id="abc123",
            task_name="do_running",
        )
        assert task.check == check
        assert task.task_id == "abc123"
        assert task.task_name == "do_running"
        assert task.queued_at is not None

    def test_one_to_one_enforces_single_task(self) -> None:
        """Only one pending task allowed per check (OneToOne constraint)."""
        check = ManufacturabilityCheckFactory()
        ManufacturabilityCheckTask.objects.create(
            check=check,
            task_id="task1",
            task_name="do_running",
        )
        with pytest.raises(IntegrityError):
            ManufacturabilityCheckTask.objects.create(
                check=check,
                task_id="task2",
                task_name="do_running",
            )

    def test_deleting_check_deletes_task(self) -> None:
        """Deleting check cascades to delete task."""
        check = ManufacturabilityCheckFactory()
        ManufacturabilityCheckTask.objects.create(
            check=check,
            task_id="abc123",
            task_name="do_running",
        )
        check_id = check.id
        check.delete()
        assert not ManufacturabilityCheckTask.objects.filter(check_id=check_id).exists()

    def test_pending_task_relation(self) -> None:
        """Check has pending_task reverse relation."""
        check = ManufacturabilityCheckFactory()
        task = ManufacturabilityCheckTask.objects.create(
            check=check,
            task_id="abc123",
            task_name="do_running",
        )
        assert check.pending_task == task
```

**Step 2: Run test to verify it fails**

Run: `make test ARGS="wafer_space/projects/tests/test_check_task_model.py -v"`

Expected: FAIL with `ImportError: cannot import name 'ManufacturabilityCheckTask'`

**Step 3: Write minimal implementation**

Add model to `wafer_space/projects/models.py`:

```python
class ManufacturabilityCheckTask(models.Model):
    """Tracks pending/running Celery tasks for manufacturability checks.

    Ephemeral - rows are deleted when tasks complete. Used to prevent
    duplicate task queuing.
    """

    check = models.OneToOneField(
        ManufacturabilityCheck,
        on_delete=models.CASCADE,
        related_name="pending_task",
    )
    task_id = models.CharField(
        max_length=255,
        help_text="Celery task ID",
    )
    task_name = models.CharField(
        max_length=255,
        help_text="Name of the Celery task (e.g., do_running)",
    )
    queued_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When the task was queued",
    )

    class Meta:
        verbose_name = "Manufacturability Check Task"
        verbose_name_plural = "Manufacturability Check Tasks"

    def __str__(self) -> str:
        return f"{self.task_name} for check {self.check_id}"
```

**Step 4: Run test to verify it passes**

Run: `make test ARGS="wafer_space/projects/tests/test_check_task_model.py -v"`

Expected: PASS

**Step 5: Create and apply migration**

```bash
uv run python manage.py makemigrations projects --name add_manufacturability_check_task
uv run python manage.py migrate
```

**Step 6: Commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/models.py wafer_space/projects/migrations/ wafer_space/projects/tests/
git commit -m "feat(models): add ManufacturabilityCheckTask for task deduplication"
```

---

## Phase 3: State Transition Methods

### Task 3.1: Add mark_dispatching Method

**Files:**
- Modify: `wafer_space/projects/models.py`
- Test: `wafer_space/projects/tests/test_models.py`

**Step 1: Write the failing test**

```python
class TestManufacturabilityCheckMarkDispatching:
    """Test mark_dispatching transition method."""

    def test_mark_dispatching_changes_status(self) -> None:
        """mark_dispatching transitions PENDING -> DISPATCHING."""
        check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.PENDING)
        check.mark_dispatching(server_id="local")
        assert check.status == ManufacturabilityCheck.Status.DISPATCHING

    def test_mark_dispatching_sets_server_id(self) -> None:
        """mark_dispatching stores the assigned server ID."""
        check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.PENDING)
        check.mark_dispatching(server_id="remote-1")
        assert check.docker_server_id == "remote-1"

    def test_mark_dispatching_sets_timestamp(self) -> None:
        """mark_dispatching sets dispatching_started_at automatically."""
        check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.PENDING)
        assert check.dispatching_started_at is None
        check.mark_dispatching(server_id="local")
        assert check.dispatching_started_at is not None

    def test_mark_dispatching_saves_to_db(self) -> None:
        """mark_dispatching saves changes to database."""
        check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.PENDING)
        check.mark_dispatching(server_id="local")
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.DISPATCHING
        assert check.docker_server_id == "local"

    def test_mark_dispatching_raises_for_invalid_transition(self) -> None:
        """mark_dispatching raises for non-PENDING status."""
        check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.RUNNING)
        with pytest.raises(ManufacturabilityCheck.InvalidStateTransition):
            check.mark_dispatching(server_id="local")
```

**Step 2: Run test to verify it fails**

Run: `make test ARGS="wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckMarkDispatching -v"`

Expected: FAIL with `AttributeError: 'ManufacturabilityCheck' object has no attribute 'mark_dispatching'`

**Step 3: Write minimal implementation**

Add method to ManufacturabilityCheck model:

```python
def mark_dispatching(self, *, server_id: str) -> None:
    """Transition PENDING -> DISPATCHING with server assignment.

    Args:
        server_id: ID of the Docker server to run this check on.

    Raises:
        InvalidStateTransition: If not in PENDING status.
    """
    self._transition_to(
        self.Status.DISPATCHING,
        docker_server_id=server_id,
        dispatching_started_at=timezone.now(),
    )
```

Note: You may need to update the existing `_transition_to` helper to accept `**kwargs` and set them before saving, or add a new helper. Check existing implementation pattern.

**Step 4: Run test to verify it passes**

Run: `make test ARGS="wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckMarkDispatching -v"`

Expected: PASS

**Step 5: Commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/models.py wafer_space/projects/tests/test_models.py
git commit -m "feat(models): add mark_dispatching transition method"
```

---

### Task 3.2: Add mark_starting Method

**Files:**
- Modify: `wafer_space/projects/models.py`
- Test: `wafer_space/projects/tests/test_models.py`

**Step 1: Write the failing test**

```python
class TestManufacturabilityCheckMarkStarting:
    """Test mark_starting transition method."""

    def test_mark_starting_changes_status(self) -> None:
        """mark_starting transitions DISPATCHING -> STARTING."""
        check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.DISPATCHING)
        check.mark_starting(docker_image="ghcr.io/test:latest", docker_image_digest="sha256:abc123")
        assert check.status == ManufacturabilityCheck.Status.STARTING

    def test_mark_starting_sets_image_info(self) -> None:
        """mark_starting stores image and digest."""
        check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.DISPATCHING)
        check.mark_starting(docker_image="ghcr.io/test:latest", docker_image_digest="sha256:abc123")
        assert check.docker_image == "ghcr.io/test:latest"
        assert check.docker_image_digest == "sha256:abc123"

    def test_mark_starting_sets_timestamp(self) -> None:
        """mark_starting sets starting_started_at automatically."""
        check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.DISPATCHING)
        assert check.starting_started_at is None
        check.mark_starting(docker_image="ghcr.io/test:latest", docker_image_digest="sha256:abc123")
        assert check.starting_started_at is not None

    def test_mark_starting_raises_for_invalid_transition(self) -> None:
        """mark_starting raises for non-DISPATCHING status."""
        check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.PENDING)
        with pytest.raises(ManufacturabilityCheck.InvalidStateTransition):
            check.mark_starting(docker_image="test", docker_image_digest="sha256:abc")
```

**Step 2: Run test to verify it fails**

Run: `make test ARGS="wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckMarkStarting -v"`

Expected: FAIL

**Step 3: Write minimal implementation**

```python
def mark_starting(self, *, docker_image: str, docker_image_digest: str) -> None:
    """Transition DISPATCHING -> STARTING with image info.

    Args:
        docker_image: Full Docker image name with tag.
        docker_image_digest: Image digest (sha256:...).

    Raises:
        InvalidStateTransition: If not in DISPATCHING status.
    """
    self._transition_to(
        self.Status.STARTING,
        docker_image=docker_image,
        docker_image_digest=docker_image_digest,
        starting_started_at=timezone.now(),
    )
```

**Step 4: Run test to verify it passes**

Run: `make test ARGS="wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckMarkStarting -v"`

Expected: PASS

**Step 5: Commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/models.py wafer_space/projects/tests/test_models.py
git commit -m "feat(models): add mark_starting transition method"
```

---

### Task 3.3: Update mark_running Method

**Files:**
- Modify: `wafer_space/projects/models.py`
- Test: `wafer_space/projects/tests/test_models.py`

**Step 1: Write the failing test**

```python
class TestManufacturabilityCheckMarkRunningUpdated:
    """Test updated mark_running transition method."""

    def test_mark_running_from_starting(self) -> None:
        """mark_running transitions STARTING -> RUNNING."""
        check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.STARTING)
        check.mark_running(docker_container_id="abc123", docker_command=["precheck", "/input"])
        assert check.status == ManufacturabilityCheck.Status.RUNNING

    def test_mark_running_sets_container_info(self) -> None:
        """mark_running stores container ID and command."""
        check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.STARTING)
        check.mark_running(docker_container_id="abc123", docker_command=["precheck", "/input"])
        assert check.docker_container_id == "abc123"
        assert check.docker_command == ["precheck", "/input"]

    def test_mark_running_sets_container_started_at(self) -> None:
        """mark_running sets container_started_at automatically."""
        check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.STARTING)
        assert check.container_started_at is None
        check.mark_running(docker_container_id="abc123", docker_command=["precheck"])
        assert check.container_started_at is not None

    def test_mark_running_raises_for_invalid_transition(self) -> None:
        """mark_running raises for non-STARTING status."""
        check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.DISPATCHING)
        with pytest.raises(ManufacturabilityCheck.InvalidStateTransition):
            check.mark_running(docker_container_id="abc", docker_command=["test"])
```

**Step 2: Run test to verify it fails**

Run: `make test ARGS="wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckMarkRunningUpdated -v"`

Expected: FAIL (existing mark_running likely has different signature or starts from DISPATCHED)

**Step 3: Update implementation**

Update `mark_running` method to:
1. Accept new parameters
2. Transition from STARTING (not DISPATCHED)
3. Set `container_started_at`

```python
def mark_running(
    self,
    *,
    docker_container_id: str,
    docker_command: list[str],
) -> None:
    """Transition STARTING -> RUNNING with container info.

    Args:
        docker_container_id: Docker container ID.
        docker_command: Command executed in container.

    Raises:
        InvalidStateTransition: If not in STARTING status.
    """
    self._transition_to(
        self.Status.RUNNING,
        docker_container_id=docker_container_id,
        docker_command=docker_command,
        container_started_at=timezone.now(),
    )
```

**Step 4: Run test to verify it passes**

Run: `make test ARGS="wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckMarkRunningUpdated -v"`

Expected: PASS

**Step 5: Commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/models.py wafer_space/projects/tests/test_models.py
git commit -m "feat(models): update mark_running to transition from STARTING"
```

---

### Task 3.4: Add mark_analyzing Method

**Files:**
- Modify: `wafer_space/projects/models.py`
- Test: `wafer_space/projects/tests/test_models.py`

**Step 1: Write the failing test**

```python
class TestManufacturabilityCheckMarkAnalyzing:
    """Test mark_analyzing transition method."""

    def test_mark_analyzing_changes_status(self) -> None:
        """mark_analyzing transitions RUNNING -> ANALYZING."""
        check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.RUNNING)
        check.mark_analyzing(docker_exit_code=0)
        assert check.status == ManufacturabilityCheck.Status.ANALYZING

    def test_mark_analyzing_sets_exit_code(self) -> None:
        """mark_analyzing stores container exit code."""
        check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.RUNNING)
        check.mark_analyzing(docker_exit_code=1)
        assert check.docker_exit_code == 1

    def test_mark_analyzing_sets_container_finished_at(self) -> None:
        """mark_analyzing sets container_finished_at automatically."""
        check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.RUNNING)
        assert check.container_finished_at is None
        check.mark_analyzing(docker_exit_code=0)
        assert check.container_finished_at is not None

    def test_mark_analyzing_raises_for_invalid_transition(self) -> None:
        """mark_analyzing raises for non-RUNNING status."""
        check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.STARTING)
        with pytest.raises(ManufacturabilityCheck.InvalidStateTransition):
            check.mark_analyzing(docker_exit_code=0)
```

**Step 2: Run test to verify it fails**

Run: `make test ARGS="wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckMarkAnalyzing -v"`

Expected: FAIL

**Step 3: Write minimal implementation**

```python
def mark_analyzing(self, *, docker_exit_code: int) -> None:
    """Transition RUNNING -> ANALYZING with exit code.

    Args:
        docker_exit_code: Container exit code.

    Raises:
        InvalidStateTransition: If not in RUNNING status.
    """
    self._transition_to(
        self.Status.ANALYZING,
        docker_exit_code=docker_exit_code,
        container_finished_at=timezone.now(),
    )
```

**Step 4: Run test to verify it passes**

Run: `make test ARGS="wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckMarkAnalyzing -v"`

Expected: PASS

**Step 5: Commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/models.py wafer_space/projects/tests/test_models.py
git commit -m "feat(models): add mark_analyzing transition method"
```

---

### Task 3.5: Update mark_finished Method

**Files:**
- Modify: `wafer_space/projects/models.py`
- Test: `wafer_space/projects/tests/test_models.py`

**Step 1: Write the failing test**

```python
class TestManufacturabilityCheckMarkFinishedUpdated:
    """Test updated mark_finished transition method."""

    def test_mark_finished_from_analyzing(self) -> None:
        """mark_finished transitions ANALYZING -> FINISHED."""
        check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.ANALYZING)
        check.mark_finished(
            is_manufacturable=True,
            errors=[],
            warnings=["minor issue"],
            tool_versions={"precheck": "1.0"},
        )
        assert check.status == ManufacturabilityCheck.Status.FINISHED

    def test_mark_finished_sets_results(self) -> None:
        """mark_finished stores analysis results."""
        check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.ANALYZING)
        check.mark_finished(
            is_manufacturable=False,
            errors=["fatal error"],
            warnings=[],
            tool_versions={"precheck": "2.0"},
        )
        assert check.is_manufacturable is False
        assert check.errors == ["fatal error"]
        assert check.warnings == []
        assert check.tool_versions == {"precheck": "2.0"}

    def test_mark_finished_sets_analysis_completed_at(self) -> None:
        """mark_finished sets analysis_completed_at automatically."""
        check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.ANALYZING)
        assert check.analysis_completed_at is None
        check.mark_finished(
            is_manufacturable=True,
            errors=[],
            warnings=[],
            tool_versions={},
        )
        assert check.analysis_completed_at is not None

    def test_mark_finished_raises_for_invalid_transition(self) -> None:
        """mark_finished raises for non-ANALYZING status."""
        check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.RUNNING)
        with pytest.raises(ManufacturabilityCheck.InvalidStateTransition):
            check.mark_finished(
                is_manufacturable=True, errors=[], warnings=[], tool_versions={}
            )
```

**Step 2: Run test to verify it fails**

Run: `make test ARGS="wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckMarkFinishedUpdated -v"`

Expected: FAIL (existing mark_finished likely transitions from RUNNING)

**Step 3: Update implementation**

Update `mark_finished` to transition from ANALYZING:

```python
def mark_finished(
    self,
    *,
    is_manufacturable: bool,
    errors: list[str],
    warnings: list[str],
    tool_versions: dict[str, str],
) -> None:
    """Transition ANALYZING -> FINISHED with results.

    Args:
        is_manufacturable: Whether the design is manufacturable.
        errors: List of error messages.
        warnings: List of warning messages.
        tool_versions: Dict of tool name to version.

    Raises:
        InvalidStateTransition: If not in ANALYZING status.
    """
    self._transition_to(
        self.Status.FINISHED,
        is_manufacturable=is_manufacturable,
        errors=errors,
        warnings=warnings,
        tool_versions=tool_versions,
        analysis_completed_at=timezone.now(),
    )
```

**Step 4: Run test to verify it passes**

Run: `make test ARGS="wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckMarkFinishedUpdated -v"`

Expected: PASS

**Step 5: Commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/models.py wafer_space/projects/tests/test_models.py
git commit -m "feat(models): update mark_finished to transition from ANALYZING"
```

---

## Phase 4: Helper Functions

### Task 4.1: Add Docker Timestamp Parser

**Files:**
- Create: `wafer_space/projects/docker_utils.py`
- Create: `wafer_space/projects/tests/test_docker_utils.py`

**Step 1: Write the failing test**

Create `wafer_space/projects/tests/test_docker_utils.py`:

```python
"""Tests for Docker utility functions."""

from __future__ import annotations

import pytest

from wafer_space.projects.docker_utils import parse_docker_timestamp_float, strip_docker_timestamps


class TestParseDockerTimestampFloat:
    """Test parse_docker_timestamp_float function."""

    def test_parses_standard_docker_timestamp(self) -> None:
        """Parses standard Docker timestamp to float."""
        line = "2024-12-05T14:30:45.123456789Z Some log message"
        result = parse_docker_timestamp_float(line)
        assert result is not None
        # 2024-12-05T14:30:45Z = 1733408245.0 (approximate)
        assert 1733408245.0 < result < 1733408246.0

    def test_preserves_nanosecond_precision(self) -> None:
        """Float preserves sub-second precision."""
        line1 = "2024-12-05T14:30:45.000000001Z First"
        line2 = "2024-12-05T14:30:45.000000002Z Second"
        result1 = parse_docker_timestamp_float(line1)
        result2 = parse_docker_timestamp_float(line2)
        assert result1 is not None
        assert result2 is not None
        assert result2 > result1

    def test_returns_none_for_invalid_line(self) -> None:
        """Returns None if line doesn't start with timestamp."""
        result = parse_docker_timestamp_float("No timestamp here")
        assert result is None

    def test_handles_varying_nanosecond_lengths(self) -> None:
        """Handles timestamps with different nanosecond digit counts."""
        # 3 digits
        result = parse_docker_timestamp_float("2024-12-05T14:30:45.123Z msg")
        assert result is not None
        # 9 digits
        result = parse_docker_timestamp_float("2024-12-05T14:30:45.123456789Z msg")
        assert result is not None


class TestStripDockerTimestamps:
    """Test strip_docker_timestamps function."""

    def test_strips_timestamps_from_log_lines(self) -> None:
        """Removes Docker timestamps from beginning of lines."""
        logs = "2024-12-05T14:30:45.123456789Z Hello\n2024-12-05T14:30:46.000000000Z World"
        result = strip_docker_timestamps(logs)
        assert result == "Hello\nWorld"

    def test_preserves_lines_without_timestamps(self) -> None:
        """Lines without timestamps are preserved as-is."""
        logs = "No timestamp here\nAlso no timestamp"
        result = strip_docker_timestamps(logs)
        assert result == "No timestamp here\nAlso no timestamp"

    def test_handles_empty_string(self) -> None:
        """Empty string returns empty string."""
        assert strip_docker_timestamps("") == ""
```

**Step 2: Run test to verify it fails**

Run: `make test ARGS="wafer_space/projects/tests/test_docker_utils.py -v"`

Expected: FAIL with `ModuleNotFoundError: No module named 'wafer_space.projects.docker_utils'`

**Step 3: Write minimal implementation**

Create `wafer_space/projects/docker_utils.py`:

```python
"""Docker utility functions for manufacturability checks."""

from __future__ import annotations

import re
from datetime import datetime, timezone

# Matches Docker RFC3339Nano timestamp at start of line
DOCKER_TIMESTAMP_PATTERN = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})\.(\d+)Z"
)


def parse_docker_timestamp_float(line: str) -> float | None:
    """Extract timestamp from Docker log line as Unix float with nanoseconds.

    Docker log timestamps are RFC3339Nano format:
    2024-12-05T14:30:45.123456789Z

    Args:
        line: A Docker log line, potentially starting with timestamp.

    Returns:
        Unix timestamp as float with nanosecond precision, or None if no match.
    """
    match = DOCKER_TIMESTAMP_PATTERN.match(line)
    if not match:
        return None

    year, month, day, hour, minute, second, nanos = match.groups()

    dt = datetime(
        int(year),
        int(month),
        int(day),
        int(hour),
        int(minute),
        int(second),
        tzinfo=timezone.utc,
    )

    unix_seconds = dt.timestamp()
    nano_fraction = int(nanos) / (10 ** len(nanos))

    return unix_seconds + nano_fraction


def strip_docker_timestamps(logs: str) -> str:
    """Remove Docker timestamps from log lines.

    Args:
        logs: Raw Docker logs with timestamps.

    Returns:
        Logs with timestamps stripped from each line.
    """
    if not logs:
        return logs

    lines = logs.split("\n")
    clean_lines = []

    for line in lines:
        match = DOCKER_TIMESTAMP_PATTERN.match(line)
        if match:
            # Remove timestamp and the 'Z ' after it
            clean_lines.append(line[match.end() + 1 :].lstrip())
        else:
            clean_lines.append(line)

    return "\n".join(clean_lines)
```

**Step 4: Run test to verify it passes**

Run: `make test ARGS="wafer_space/projects/tests/test_docker_utils.py -v"`

Expected: PASS

**Step 5: Commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/docker_utils.py wafer_space/projects/tests/test_docker_utils.py
git commit -m "feat(utils): add Docker timestamp parsing utilities"
```

---

### Task 4.2: Add track_task Context Manager

**Files:**
- Modify: `wafer_space/projects/docker_utils.py`
- Modify: `wafer_space/projects/tests/test_docker_utils.py`

**Step 1: Write the failing test**

Add to `test_docker_utils.py`:

```python
from wafer_space.projects.docker_utils import track_task
from wafer_space.projects.models import ManufacturabilityCheckTask
from wafer_space.projects.tests.factories import ManufacturabilityCheckFactory


class TestTrackTask:
    """Test track_task context manager."""

    @pytest.mark.django_db
    def test_deletes_task_on_success(self) -> None:
        """Task tracking row is deleted when context exits normally."""
        check = ManufacturabilityCheckFactory()
        ManufacturabilityCheckTask.objects.create(
            check=check,
            task_id="abc123",
            task_name="do_running",
        )
        assert ManufacturabilityCheckTask.objects.filter(check=check).exists()

        with track_task(check.id):
            pass  # Simulated work

        assert not ManufacturabilityCheckTask.objects.filter(check=check).exists()

    @pytest.mark.django_db
    def test_deletes_task_on_exception(self) -> None:
        """Task tracking row is deleted even when exception occurs."""
        check = ManufacturabilityCheckFactory()
        ManufacturabilityCheckTask.objects.create(
            check=check,
            task_id="abc123",
            task_name="do_running",
        )

        with pytest.raises(ValueError, match="test error"):
            with track_task(check.id):
                msg = "test error"
                raise ValueError(msg)

        assert not ManufacturabilityCheckTask.objects.filter(check=check).exists()

    @pytest.mark.django_db
    def test_handles_missing_task_gracefully(self) -> None:
        """No error if task row doesn't exist."""
        check = ManufacturabilityCheckFactory()
        # No ManufacturabilityCheckTask created

        with track_task(check.id):
            pass  # Should not raise
```

**Step 2: Run test to verify it fails**

Run: `make test ARGS="wafer_space/projects/tests/test_docker_utils.py::TestTrackTask -v"`

Expected: FAIL with `ImportError: cannot import name 'track_task'`

**Step 3: Write minimal implementation**

Add to `wafer_space/projects/docker_utils.py`:

```python
from contextlib import contextmanager
from typing import Generator

from wafer_space.projects.models import ManufacturabilityCheckTask


@contextmanager
def track_task(check_id: int) -> Generator[None, None, None]:
    """Delete task tracking row when work completes.

    Used by work tasks (do_*) to clean up their ManufacturabilityCheckTask
    row regardless of success or failure.

    Args:
        check_id: ID of the ManufacturabilityCheck.

    Yields:
        None - work is done in the context block.
    """
    try:
        yield
    finally:
        ManufacturabilityCheckTask.objects.filter(check_id=check_id).delete()
```

**Step 4: Run test to verify it passes**

Run: `make test ARGS="wafer_space/projects/tests/test_docker_utils.py::TestTrackTask -v"`

Expected: PASS

**Step 5: Commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/docker_utils.py wafer_space/projects/tests/test_docker_utils.py
git commit -m "feat(utils): add track_task context manager for task cleanup"
```

---

## Phase 5: Settings Configuration

### Task 5.1: Add DOCKER_SERVERS Setting

**Files:**
- Modify: `config/settings/base.py`
- Modify: `config/settings/dev.py`
- Modify: `config/settings/pytest.py`
- Test: `wafer_space/projects/tests/test_settings.py`

**Step 1: Write the failing test**

Create `wafer_space/projects/tests/test_settings.py`:

```python
"""Tests for Docker server settings."""

from __future__ import annotations

from django.conf import settings


class TestDockerServersSettings:
    """Test DOCKER_SERVERS configuration."""

    def test_docker_servers_exists(self) -> None:
        """DOCKER_SERVERS setting exists."""
        assert hasattr(settings, "DOCKER_SERVERS")
        assert isinstance(settings.DOCKER_SERVERS, list)

    def test_docker_servers_has_required_keys(self) -> None:
        """Each server has id, url, max_concurrent, priority."""
        for server in settings.DOCKER_SERVERS:
            assert "id" in server
            assert "url" in server
            assert "max_concurrent" in server
            assert "priority" in server

    def test_docker_servers_sorted_by_priority(self) -> None:
        """Servers should be sorted by priority (lowest first)."""
        priorities = [s["priority"] for s in settings.DOCKER_SERVERS]
        assert priorities == sorted(priorities)
```

**Step 2: Run test to verify it fails**

Run: `make test ARGS="wafer_space/projects/tests/test_settings.py -v"`

Expected: FAIL with `AssertionError` (DOCKER_SERVERS doesn't exist)

**Step 3: Write minimal implementation**

Add to `config/settings/base.py` (near other Docker settings around line 446):

```python
# Docker server configuration
# Servers are selected in priority order (lowest number = highest priority)
# Override in environment-specific settings
DOCKER_SERVERS: list[dict[str, str | int]] = []
```

Add to `config/settings/dev.py`:

```python
# Local Docker server for development
DOCKER_SERVERS = [
    {
        "id": "local",
        "url": "unix:///var/run/docker.sock",
        "max_concurrent": 4,
        "priority": 1,
    },
]
```

Add to `config/settings/pytest.py`:

```python
# Test Docker server configuration
DOCKER_SERVERS = [
    {
        "id": "test-local",
        "url": "unix:///var/run/docker.sock",
        "max_concurrent": 2,
        "priority": 1,
    },
]
```

**Step 4: Run test to verify it passes**

Run: `make test ARGS="wafer_space/projects/tests/test_settings.py -v"`

Expected: PASS

**Step 5: Commit**

```bash
make lint-fix && make lint && make type-check
git add config/settings/base.py config/settings/dev.py config/settings/pytest.py wafer_space/projects/tests/test_settings.py
git commit -m "feat(settings): add DOCKER_SERVERS configuration"
```

---

## Phase 6: Beat Tasks

### Task 6.1: Add checks_pending Beat Task

**Files:**
- Modify: `wafer_space/projects/tasks.py`
- Test: `wafer_space/projects/tests/test_tasks.py`

**Step 1: Write the failing test**

Add to `test_tasks.py`:

```python
from wafer_space.projects.tasks import checks_pending


class TestChecksPending:
    """Test checks_pending beat task."""

    @pytest.mark.django_db
    def test_transitions_pending_to_dispatching(self) -> None:
        """Transitions PENDING checks to DISPATCHING with server assignment."""
        check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.PENDING)

        checks_pending()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.DISPATCHING
        assert check.docker_server_id is not None

    @pytest.mark.django_db
    def test_respects_server_capacity(self, settings) -> None:
        """Only dispatches up to max_concurrent per server."""
        settings.DOCKER_SERVERS = [
            {"id": "test", "url": "unix:///test.sock", "max_concurrent": 2, "priority": 1},
        ]
        # Create 2 already active checks
        ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING,
            docker_server_id="test",
        )
        ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING,
            docker_server_id="test",
        )
        # Create pending check
        check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.PENDING)

        checks_pending()

        check.refresh_from_db()
        # Should remain PENDING - server at capacity
        assert check.status == ManufacturabilityCheck.Status.PENDING

    @pytest.mark.django_db
    def test_uses_priority_order(self, settings) -> None:
        """Uses servers in priority order (lowest priority number first)."""
        settings.DOCKER_SERVERS = [
            {"id": "low-priority", "url": "unix:///a.sock", "max_concurrent": 2, "priority": 10},
            {"id": "high-priority", "url": "unix:///b.sock", "max_concurrent": 2, "priority": 1},
        ]
        check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.PENDING)

        checks_pending()

        check.refresh_from_db()
        assert check.docker_server_id == "high-priority"

    @pytest.mark.django_db
    def test_does_not_touch_non_pending(self) -> None:
        """Does not affect checks not in PENDING status."""
        check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.RUNNING)

        checks_pending()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.RUNNING
```

**Step 2: Run test to verify it fails**

Run: `make test ARGS="wafer_space/projects/tests/test_tasks.py::TestChecksPending -v"`

Expected: FAIL

**Step 3: Write minimal implementation**

Add/update in `wafer_space/projects/tasks.py`:

```python
from django.conf import settings as django_settings

from wafer_space.projects.models import ManufacturabilityCheck


@shared_task
def checks_pending() -> dict[str, int]:
    """Transition PENDING checks to DISPATCHING with server assignment.

    Respects per-server concurrent limits. Assigns to servers in priority order.

    Returns:
        Dict with count of dispatched checks.
    """
    dispatched = 0

    # Sort servers by priority (lowest first)
    servers = sorted(django_settings.DOCKER_SERVERS, key=lambda s: s["priority"])

    for server in servers:
        server_id = server["id"]
        max_concurrent = server["max_concurrent"]

        # Count active checks on this server
        active_count = ManufacturabilityCheck.objects.filter(
            docker_server_id=server_id,
            status__in=ManufacturabilityCheck.Status.active(),
        ).count()

        available_slots = max_concurrent - active_count

        if available_slots > 0:
            pending_checks = ManufacturabilityCheck.objects.filter(
                status=ManufacturabilityCheck.Status.PENDING
            ).order_by("created_at")[:available_slots]

            for check in pending_checks:
                check.mark_dispatching(server_id=server_id)
                dispatched += 1

    return {"dispatched": dispatched}
```

**Step 4: Run test to verify it passes**

Run: `make test ARGS="wafer_space/projects/tests/test_tasks.py::TestChecksPending -v"`

Expected: PASS

**Step 5: Commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/tasks.py wafer_space/projects/tests/test_tasks.py
git commit -m "feat(tasks): add checks_pending beat task for server assignment"
```

---

### Task 6.2: Add checks_dispatching Beat Task

**Files:**
- Modify: `wafer_space/projects/tasks.py`
- Test: `wafer_space/projects/tests/test_tasks.py`

**Step 1: Write the failing test**

```python
from wafer_space.projects.models import ManufacturabilityCheckTask
from wafer_space.projects.tasks import checks_dispatching


class TestChecksDispatching:
    """Test checks_dispatching beat task."""

    @pytest.mark.django_db
    def test_queues_do_dispatching_for_dispatching_checks(self) -> None:
        """Queues do_dispatching work task for DISPATCHING checks."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.DISPATCHING,
            docker_server_id="local",
        )

        with patch("wafer_space.projects.tasks.do_dispatching.delay") as mock_delay:
            mock_delay.return_value.id = "task-123"
            result = checks_dispatching()

        mock_delay.assert_called_once_with(check.id)
        assert result["queued"] == 1

        # Should create task tracking row
        task = ManufacturabilityCheckTask.objects.get(check=check)
        assert task.task_id == "task-123"
        assert task.task_name == "do_dispatching"

    @pytest.mark.django_db
    def test_skips_checks_with_pending_task(self) -> None:
        """Does not queue if check already has pending task."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.DISPATCHING,
            docker_server_id="local",
        )
        ManufacturabilityCheckTask.objects.create(
            check=check,
            task_id="existing",
            task_name="do_dispatching",
        )

        with patch("wafer_space.projects.tasks.do_dispatching.delay") as mock_delay:
            result = checks_dispatching()

        mock_delay.assert_not_called()
        assert result["queued"] == 0
```

**Step 2: Run test to verify it fails**

Run: `make test ARGS="wafer_space/projects/tests/test_tasks.py::TestChecksDispatching -v"`

Expected: FAIL

**Step 3: Write minimal implementation**

```python
@shared_task
def checks_dispatching() -> dict[str, int]:
    """Queue do_dispatching work tasks for DISPATCHING checks.

    Only queues if check doesn't already have a pending task.

    Returns:
        Dict with count of queued tasks.
    """
    queued = 0

    dispatching_checks = ManufacturabilityCheck.objects.filter(
        status=ManufacturabilityCheck.Status.DISPATCHING,
    ).exclude(
        pending_task__isnull=False
    )

    for check in dispatching_checks:
        result = do_dispatching.delay(check.id)
        ManufacturabilityCheckTask.objects.create(
            check=check,
            task_id=result.id,
            task_name="do_dispatching",
        )
        queued += 1

    return {"queued": queued}
```

**Step 4: Run test to verify it passes**

Run: `make test ARGS="wafer_space/projects/tests/test_tasks.py::TestChecksDispatching -v"`

Expected: PASS

**Step 5: Commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/tasks.py wafer_space/projects/tests/test_tasks.py
git commit -m "feat(tasks): add checks_dispatching beat task"
```

---

### Task 6.3: Add checks_starting, checks_running, checks_analyzing Beat Tasks

Follow the same pattern as Task 6.2 for:
- `checks_starting` - queues `do_starting` for STARTING checks
- `checks_running` - queues `do_running` for RUNNING checks
- `checks_analyzing` - queues `do_analyzing` for ANALYZING checks

Each task:
1. Finds checks in the target status
2. Excludes checks with existing `pending_task`
3. Queues the corresponding `do_*` work task
4. Creates `ManufacturabilityCheckTask` tracking row

**Commit after each task is implemented and tested.**

---

### Task 6.4: Update checks_cancelling Beat Task

**Files:**
- Modify: `wafer_space/projects/tasks.py`
- Test: `wafer_space/projects/tests/test_tasks.py`

Update the existing `checks_cancelling` task to use the new task deduplication pattern:

1. Find CANCELLING checks without pending_task
2. Queue `do_cancelling` work task
3. Create ManufacturabilityCheckTask row

---

## Phase 7: Work Tasks

### Task 7.1: Add do_dispatching Work Task

**Files:**
- Modify: `wafer_space/projects/tasks.py`
- Test: `wafer_space/projects/tests/test_tasks.py`

**Step 1: Write the failing test**

```python
class TestDoDispatching:
    """Test do_dispatching work task."""

    @pytest.mark.django_db
    def test_pulls_image_and_transitions_to_starting(self) -> None:
        """Pulls Docker image and transitions to STARTING."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.DISPATCHING,
            docker_server_id="local",
        )
        ManufacturabilityCheckTask.objects.create(
            check=check, task_id="test", task_name="do_dispatching"
        )

        with patch("wafer_space.projects.tasks.docker.from_env") as mock_docker:
            mock_client = MagicMock()
            mock_docker.return_value = mock_client
            mock_image = MagicMock()
            mock_image.attrs = {"RepoDigests": ["ghcr.io/test@sha256:abc123"]}
            mock_client.images.pull.return_value = mock_image

            do_dispatching(check.id)

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.STARTING
        assert check.docker_image_digest == "sha256:abc123"

    @pytest.mark.django_db
    def test_cleans_up_task_tracking(self) -> None:
        """Deletes ManufacturabilityCheckTask when done."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.DISPATCHING,
            docker_server_id="local",
        )
        ManufacturabilityCheckTask.objects.create(
            check=check, task_id="test", task_name="do_dispatching"
        )

        with patch("wafer_space.projects.tasks.docker.from_env"):
            # Mock successful pull
            do_dispatching(check.id)

        assert not ManufacturabilityCheckTask.objects.filter(check=check).exists()

    @pytest.mark.django_db
    def test_skips_if_status_changed(self) -> None:
        """Does nothing if status is no longer DISPATCHING."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.CANCELLED,  # Changed
            docker_server_id="local",
        )

        with patch("wafer_space.projects.tasks.docker.from_env") as mock_docker:
            do_dispatching(check.id)

        # Should not interact with Docker
        mock_docker.assert_not_called()
```

**Step 2: Run test to verify it fails**

Run: `make test ARGS="wafer_space/projects/tests/test_tasks.py::TestDoDispatching -v"`

Expected: FAIL

**Step 3: Write minimal implementation**

```python
import docker

from wafer_space.projects.docker_utils import track_task


@shared_task(queue="docker-ephemeral")
def do_dispatching(check_id: int) -> dict[str, str]:
    """Pull Docker image for a DISPATCHING check.

    Transitions to STARTING on success.

    Args:
        check_id: ManufacturabilityCheck ID.

    Returns:
        Dict with result status.
    """
    with track_task(check_id):
        check = ManufacturabilityCheck.objects.get(id=check_id)

        if check.status != ManufacturabilityCheck.Status.DISPATCHING:
            return {"status": "skipped", "reason": "status_changed"}

        # Get server config
        server = next(
            (s for s in django_settings.DOCKER_SERVERS if s["id"] == check.docker_server_id),
            None,
        )
        if not server:
            check.mark_error(error_message=f"Unknown server: {check.docker_server_id}")
            return {"status": "error", "reason": "unknown_server"}

        # Connect to Docker
        client = docker.DockerClient(base_url=server["url"])

        try:
            image_name = django_settings.PRECHECK_DOCKER_IMAGE
            image = client.images.pull(image_name)

            # Extract digest from pulled image
            digests = image.attrs.get("RepoDigests", [])
            digest = digests[0].split("@")[1] if digests else "unknown"

            check.mark_starting(
                docker_image=image_name,
                docker_image_digest=digest,
            )

            return {"status": "success", "image": image_name, "digest": digest}

        except docker.errors.DockerException as e:
            check.mark_error(error_message=f"Docker pull failed: {e}")
            return {"status": "error", "reason": str(e)}
```

**Step 4: Run test to verify it passes**

Run: `make test ARGS="wafer_space/projects/tests/test_tasks.py::TestDoDispatching -v"`

Expected: PASS

**Step 5: Commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/tasks.py wafer_space/projects/tests/test_tasks.py
git commit -m "feat(tasks): add do_dispatching work task for image pulling"
```

---

### Task 7.2-7.5: Add Remaining Work Tasks

Follow similar patterns for:

**Task 7.2: do_starting**
- Creates container with labels
- Starts container
- Waits for container to be running
- Transitions to RUNNING

**Task 7.3: do_running**
- Checks container status
- Downloads logs incrementally using `since` parameter
- Appends logs to check
- If container exited, transitions to ANALYZING

**Task 7.4: do_analyzing**
- Parses logs for results
- Extracts tool versions
- Sets is_manufacturable, errors, warnings
- Saves log file and archive
- Transitions to FINISHED

**Task 7.5: do_cancelling**
- Stops container if running
- Removes container
- Transitions to CANCELLED

Each task should:
1. Use `track_task(check_id)` context manager
2. Check status before doing work
3. Handle Docker exceptions
4. Clean up resources

---

## Phase 8: Beat Schedule Update

### Task 8.1: Update CELERY_BEAT_SCHEDULE

**Files:**
- Modify: `config/settings/base.py`

**Step 1: Update the beat schedule**

Replace the manufacturability check section of `CELERY_BEAT_SCHEDULE`:

```python
CELERY_BEAT_SCHEDULE = {
    # Manufacturability check lifecycle - polling architecture
    "checks-pending": {
        "task": "wafer_space.projects.tasks.checks_pending",
        "schedule": 30.0,
    },
    "checks-dispatching": {
        "task": "wafer_space.projects.tasks.checks_dispatching",
        "schedule": 15.0,
    },
    "checks-starting": {
        "task": "wafer_space.projects.tasks.checks_starting",
        "schedule": 15.0,
    },
    "checks-running": {
        "task": "wafer_space.projects.tasks.checks_running",
        "schedule": 15.0,
    },
    "checks-analyzing": {
        "task": "wafer_space.projects.tasks.checks_analyzing",
        "schedule": 30.0,
    },
    "checks-cancelling": {
        "task": "wafer_space.projects.tasks.checks_cancelling",
        "schedule": 15.0,
    },
    "checks-retry": {
        "task": "wafer_space.projects.tasks.checks_retry",
        "schedule": 60.0,
    },
    # Cleanup tasks
    "checks-cleanup-orphaned-dispatching": {
        "task": "wafer_space.projects.tasks.checks_cleanup_orphaned_dispatching",
        "schedule": 60.0,
    },
    "checks-cleanup-orphaned-starting": {
        "task": "wafer_space.projects.tasks.checks_cleanup_orphaned_starting",
        "schedule": 60.0,
    },
    "checks-cleanup-orphaned-running": {
        "task": "wafer_space.projects.tasks.checks_cleanup_orphaned_running",
        "schedule": 60.0,
    },
    "checks-cleanup-orphaned-docker": {
        "task": "wafer_space.projects.tasks.checks_cleanup_orphaned_docker",
        "schedule": 300.0,
    },
    "checks-cleanup-stale-files": {
        "task": "wafer_space.projects.tasks.checks_cleanup_stale_files",
        "schedule": 60.0,
    },
    # ... other tasks
}
```

**Step 2: Commit**

```bash
make lint-fix && make lint && make type-check
git add config/settings/base.py
git commit -m "feat(settings): update CELERY_BEAT_SCHEDULE for polling architecture"
```

---

## Phase 9: Cleanup Old Code

### Task 9.1: Remove check_process_job Task

**Files:**
- Modify: `wafer_space/projects/tasks.py`

**Step 1: Delete or deprecate check_process_job**

Remove the entire `check_process_job` task function and any related helper functions that are no longer used.

**Step 2: Remove from beat schedule**

Ensure `check-process-job` is not in `CELERY_BEAT_SCHEDULE`.

**Step 3: Run full test suite**

```bash
make test
```

Fix any tests that relied on the old task.

**Step 4: Commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/tasks.py config/settings/base.py
git commit -m "refactor(tasks): remove deprecated check_process_job task"
```

---

### Task 9.2: Remove Old Model Fields

**Files:**
- Modify: `wafer_space/projects/models.py`

After all functionality is working with new fields:

1. Remove `celery_job_id`
2. Remove `celery_job_started_at`
3. Remove `celery_job_finished_at`
4. Remove `celery_worker_pid`
5. Remove `celery_worker_hostname`
6. Remove `DISPATCHED` status value

**Create migration and run full test suite before committing.**

---

## Phase 10: Integration Testing

### Task 10.1: End-to-End Test

**Files:**
- Create: `wafer_space/projects/tests/test_polling_integration.py`

Write integration tests that:
1. Create a check in PENDING
2. Run `checks_pending` - verify DISPATCHING
3. Run `checks_dispatching` - verify task queued
4. Run `do_dispatching` (mocked Docker) - verify STARTING
5. Continue through full lifecycle to FINISHED

---

## Summary

This plan implements the Celery Docker polling architecture in 10 phases:

1. **Status Enum Updates** - New statuses and classification methods
2. **New Model Fields** - Server ID, timestamps, log tracking
3. **State Transition Methods** - mark_dispatching, mark_starting, etc.
4. **Helper Functions** - Timestamp parsing, track_task context manager
5. **Settings Configuration** - DOCKER_SERVERS
6. **Beat Tasks** - Orchestrators that queue work
7. **Work Tasks** - Docker operations (do_*)
8. **Beat Schedule Update** - Wire up new tasks
9. **Cleanup Old Code** - Remove check_process_job
10. **Integration Testing** - End-to-end verification

Each task follows TDD: write failing test, implement, verify pass, commit.
