# Download State Verification Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace timeout-based orphaned download detection with multi-layer state verification using explicit download states (PENDING/QUEUED/DOWNLOADING/COMPLETED) and Celery inspect API + PID checking.

**Architecture:** Add QUEUED state to ProjectFile, track worker PID/hostname when downloads start, create new check_download_states periodic task that verifies each state using appropriate method (create task for PENDING, check Celery queue for QUEUED, check active tasks + PID for DOWNLOADING).

**Tech Stack:** Django 5.2, Celery 5.5, psutil, PostgreSQL, pytest

---

## Task 1: Add Database Fields for Worker Tracking

**Files:**
- Modify: `wafer_space/projects/models.py` (ProjectFile model, around line 150)
- Create: `wafer_space/projects/migrations/0009_projectfile_worker_tracking.py`

**Step 1: Write test for new fields**

Add to `wafer_space/projects/tests/test_models.py`:

```python
def test_projectfile_has_worker_tracking_fields(self):
    """Test that ProjectFile has worker tracking fields."""
    project_file = ProjectFile.objects.create(
        project=self.project,
        source_url="http://example.com/test.gds",
        download_status=ProjectFile.DownloadStatus.PENDING,
        is_active=False,
    )

    # Verify fields exist and are nullable
    assert hasattr(project_file, 'worker_pid')
    assert hasattr(project_file, 'worker_hostname')
    assert hasattr(project_file, 'task_started_at')
    assert project_file.worker_pid is None
    assert project_file.worker_hostname is None
    assert project_file.task_started_at is None

    # Verify we can set values
    project_file.worker_pid = 12345
    project_file.worker_hostname = "worker-01"
    project_file.task_started_at = timezone.now()
    project_file.save()

    project_file.refresh_from_db()
    assert project_file.worker_pid == 12345
    assert project_file.worker_hostname == "worker-01"
    assert project_file.task_started_at is not None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestProjectFile::test_projectfile_has_worker_tracking_fields -xvs`

Expected: FAIL with "AttributeError: 'ProjectFile' object has no attribute 'worker_pid'"

**Step 3: Add fields to ProjectFile model**

In `wafer_space/projects/models.py`, add fields to ProjectFile class:

```python
class ProjectFile(models.Model):
    # ... existing fields ...

    # Worker tracking for verification
    worker_pid = models.IntegerField(
        null=True,
        blank=True,
        help_text="Process ID of Celery worker executing download",
    )
    worker_hostname = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Hostname of worker machine",
    )
    task_started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When download task actually began execution",
    )
```

**Step 4: Create migration**

Run: `uv run python manage.py makemigrations projects --name projectfile_worker_tracking`

Expected: Migration file created

**Step 5: Run test to verify it passes**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestProjectFile::test_projectfile_has_worker_tracking_fields -xvs`

Expected: PASS

**Step 6: Commit**

```bash
git add wafer_space/projects/models.py wafer_space/projects/migrations/ wafer_space/projects/tests/test_models.py
git commit -m "Add worker tracking fields to ProjectFile

Added worker_pid, worker_hostname, and task_started_at fields
to enable process-level verification of download tasks.

Part of download state verification system."
```

---

## Task 2: Add QUEUED State to DownloadStatus

**Files:**
- Modify: `wafer_space/projects/models.py` (DownloadStatus enum, around line 75)
- Create: `wafer_space/projects/migrations/0010_projectfile_queued_status.py`

**Step 1: Write test for QUEUED status**

Add to `wafer_space/projects/tests/test_models.py`:

```python
def test_projectfile_queued_status_exists(self):
    """Test that QUEUED status exists in DownloadStatus choices."""
    # Verify QUEUED is in choices
    statuses = [choice[0] for choice in ProjectFile.DownloadStatus.choices]
    assert 'queued' in statuses

    # Verify we can create a file with QUEUED status
    project_file = ProjectFile.objects.create(
        project=self.project,
        source_url="http://example.com/test.gds",
        download_status=ProjectFile.DownloadStatus.QUEUED,
        download_task_id="task-123",
        is_active=False,
    )

    assert project_file.download_status == ProjectFile.DownloadStatus.QUEUED
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestProjectFile::test_projectfile_queued_status_exists -xvs`

Expected: FAIL with "AttributeError: type object 'DownloadStatus' has no attribute 'QUEUED'"

**Step 3: Add QUEUED to DownloadStatus**

In `wafer_space/projects/models.py`, modify DownloadStatus enum:

```python
class DownloadStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    QUEUED = "queued", "Queued"  # NEW
    DOWNLOADING = "downloading", "Downloading"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
```

**Step 4: Create migration**

Run: `uv run python manage.py makemigrations projects --name projectfile_queued_status`

Expected: Migration file created

**Step 5: Run test to verify it passes**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestProjectFile::test_projectfile_queued_status_exists -xvs`

Expected: PASS

**Step 6: Commit**

```bash
git add wafer_space/projects/models.py wafer_space/projects/migrations/ wafer_space/projects/tests/test_models.py
git commit -m "Add QUEUED status to DownloadStatus enum

QUEUED represents files with tasks created and in Celery queue.
Separates 'not queued yet' (PENDING) from 'queued' (QUEUED).

Part of download state verification system."
```

---

## Task 3: Implement is_task_queued() Verification Function

**Files:**
- Create: `wafer_space/projects/verification.py` (new file)
- Create: `wafer_space/projects/tests/test_verification.py` (new file)

**Step 1: Write test for is_task_queued()**

Create `wafer_space/projects/tests/test_verification.py`:

```python
"""Tests for download verification functions."""

from unittest.mock import Mock, patch

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from wafer_space.projects.models import Project, ProjectFile
from wafer_space.projects.verification import is_task_queued

User = get_user_model()
TEST_PASSWORD = "testpass123"  # noqa: S105


@pytest.mark.django_db
class TaskQueuedVerificationTests(TestCase):
    """Tests for is_task_queued() function."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test Description",
        )

    @patch("wafer_space.projects.verification.current_app")
    def test_task_in_reserved_queue(self, mock_app):
        """Test that task found in reserved queue returns True."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            download_status=ProjectFile.DownloadStatus.QUEUED,
            download_task_id="task-123",
            is_active=False,
        )

        # Mock Celery inspect to return task in reserved
        mock_inspect = Mock()
        mock_inspect.reserved.return_value = {
            "worker1": [
                {"id": "task-123", "name": "download_project_file"},
            ],
        }
        mock_inspect.active.return_value = {}
        mock_app.control.inspect.return_value = mock_inspect

        result = is_task_queued(project_file)

        assert result is True
        project_file.refresh_from_db()
        assert project_file.download_status == ProjectFile.DownloadStatus.QUEUED

    @patch("wafer_space.projects.verification.current_app")
    def test_task_in_active_auto_transitions(self, mock_app):
        """Test that task in active list auto-transitions to DOWNLOADING."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            download_status=ProjectFile.DownloadStatus.QUEUED,
            download_task_id="task-456",
            is_active=False,
        )

        # Mock Celery inspect to return task in active
        mock_inspect = Mock()
        mock_inspect.reserved.return_value = {}
        mock_inspect.active.return_value = {
            "worker1": [
                {"id": "task-456", "name": "download_project_file"},
            ],
        }
        mock_app.control.inspect.return_value = mock_inspect

        result = is_task_queued(project_file)

        assert result is True
        project_file.refresh_from_db()
        # Should auto-transition to DOWNLOADING
        assert project_file.download_status == ProjectFile.DownloadStatus.DOWNLOADING

    @patch("wafer_space.projects.verification.current_app")
    def test_task_not_found_returns_false(self, mock_app):
        """Test that missing task returns False."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            download_status=ProjectFile.DownloadStatus.QUEUED,
            download_task_id="task-789",
            is_active=False,
        )

        # Mock Celery inspect to return empty
        mock_inspect = Mock()
        mock_inspect.reserved.return_value = {}
        mock_inspect.active.return_value = {}
        mock_app.control.inspect.return_value = mock_inspect

        result = is_task_queued(project_file)

        assert result is False
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/projects/tests/test_verification.py::TaskQueuedVerificationTests -xvs`

Expected: FAIL with "ModuleNotFoundError: No module named 'wafer_space.projects.verification'"

**Step 3: Implement is_task_queued()**

Create `wafer_space/projects/verification.py`:

```python
"""Download verification functions for state checking."""

from __future__ import annotations

from typing import TYPE_CHECKING

from celery import current_app

if TYPE_CHECKING:
    from wafer_space.projects.models import ProjectFile


def is_task_queued(project_file: ProjectFile) -> bool:
    """Verify task is in Celery queue (reserved but not started).

    Args:
        project_file: ProjectFile to check

    Returns:
        True if task is queued or started, False if missing
    """
    task_id = project_file.download_task_id
    inspect = current_app.control.inspect()

    # Check reserved queue
    reserved = inspect.reserved()
    if reserved:
        for worker, tasks in reserved.items():
            if any(t["id"] == task_id for t in tasks):
                return True

    # Check if task started (auto-transition to DOWNLOADING)
    active = inspect.active()
    if active:
        for worker, tasks in active.items():
            if any(t["id"] == task_id for t in tasks):
                # Update state to DOWNLOADING
                from wafer_space.projects.models import ProjectFile

                project_file.download_status = ProjectFile.DownloadStatus.DOWNLOADING
                project_file.save(update_fields=["download_status"])
                return True

    return False
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest wafer_space/projects/tests/test_verification.py::TaskQueuedVerificationTests -xvs`

Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add wafer_space/projects/verification.py wafer_space/projects/tests/test_verification.py
git commit -m "Add is_task_queued() verification function

Checks if task exists in Celery reserved or active queues.
Auto-transitions QUEUED → DOWNLOADING if task started.

Part of download state verification system."
```

---

## Task 4: Implement is_task_actively_running() Verification Function

**Files:**
- Modify: `wafer_space/projects/verification.py`
- Modify: `wafer_space/projects/tests/test_verification.py`

**Step 1: Write test for is_task_actively_running()**

Add to `wafer_space/projects/tests/test_verification.py`:

```python
from wafer_space.projects.verification import is_task_actively_running


@pytest.mark.django_db
class TaskActivelyRunningTests(TestCase):
    """Tests for is_task_actively_running() function."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test Description",
        )

    @patch("wafer_space.projects.verification.psutil")
    @patch("wafer_space.projects.verification.socket")
    @patch("wafer_space.projects.verification.current_app")
    def test_task_active_and_pid_exists(self, mock_app, mock_socket, mock_psutil):
        """Test task in active list with valid PID returns True."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            download_status=ProjectFile.DownloadStatus.DOWNLOADING,
            download_task_id="task-123",
            worker_pid=12345,
            worker_hostname="worker-01",
            is_active=False,
        )

        # Mock Celery inspect
        mock_inspect = Mock()
        mock_inspect.active.return_value = {
            "worker1": [{"id": "task-123"}],
        }
        mock_app.control.inspect.return_value = mock_inspect

        # Mock socket (same hostname)
        mock_socket.gethostname.return_value = "worker-01"

        # Mock psutil (PID exists, is Celery process)
        mock_psutil.pid_exists.return_value = True
        mock_proc = Mock()
        mock_proc.cmdline.return_value = ["python", "-m", "celery", "worker"]
        mock_psutil.Process.return_value = mock_proc

        result = is_task_actively_running(project_file)

        assert result is True

    @patch("wafer_space.projects.verification.psutil")
    @patch("wafer_space.projects.verification.socket")
    @patch("wafer_space.projects.verification.current_app")
    def test_task_active_but_pid_dead(self, mock_app, mock_socket, mock_psutil):
        """Test task in active but PID doesn't exist returns False."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            download_status=ProjectFile.DownloadStatus.DOWNLOADING,
            download_task_id="task-456",
            worker_pid=99999,
            worker_hostname="worker-01",
            is_active=False,
        )

        # Mock Celery inspect (task shows as active)
        mock_inspect = Mock()
        mock_inspect.active.return_value = {
            "worker1": [{"id": "task-456"}],
        }
        mock_app.control.inspect.return_value = mock_inspect

        # Mock socket (same hostname)
        mock_socket.gethostname.return_value = "worker-01"

        # Mock psutil (PID does NOT exist)
        mock_psutil.pid_exists.return_value = False

        result = is_task_actively_running(project_file)

        assert result is False

    @patch("wafer_space.projects.verification.current_app")
    def test_task_not_in_active(self, mock_app):
        """Test task not in active list returns False."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            download_status=ProjectFile.DownloadStatus.DOWNLOADING,
            download_task_id="task-789",
            is_active=False,
        )

        # Mock Celery inspect (empty)
        mock_inspect = Mock()
        mock_inspect.active.return_value = {}
        mock_app.control.inspect.return_value = mock_inspect

        result = is_task_actively_running(project_file)

        assert result is False
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/projects/tests/test_verification.py::TaskActivelyRunningTests -xvs`

Expected: FAIL with "ImportError: cannot import name 'is_task_actively_running'"

**Step 3: Implement is_task_actively_running()**

Add to `wafer_space/projects/verification.py`:

```python
import socket

import psutil


def is_task_actively_running(project_file: ProjectFile) -> bool:
    """Verify task is executing AND process exists.

    Args:
        project_file: ProjectFile to check

    Returns:
        True if task is running with valid PID, False otherwise
    """
    task_id = project_file.download_task_id
    inspect = current_app.control.inspect()

    # Check task in active list
    active = inspect.active()
    task_in_active = False

    if active:
        for worker, tasks in active.items():
            if any(t["id"] == task_id for t in tasks):
                task_in_active = True
                break

    if not task_in_active:
        return False

    # Verify PID exists (MANDATORY if available)
    if project_file.worker_pid and project_file.worker_hostname:
        # Only check if on same host
        if socket.gethostname() == project_file.worker_hostname:
            try:
                if not psutil.pid_exists(project_file.worker_pid):
                    return False

                proc = psutil.Process(project_file.worker_pid)
                cmdline = " ".join(proc.cmdline()).lower()

                if "celery" not in cmdline:
                    return False
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return False

    return True
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest wafer_space/projects/tests/test_verification.py::TaskActivelyRunningTests -xvs`

Expected: PASS (3 tests)

**Step 5: Run all verification tests**

Run: `uv run pytest wafer_space/projects/tests/test_verification.py -v`

Expected: PASS (6 tests total)

**Step 6: Commit**

```bash
git add wafer_space/projects/verification.py wafer_space/projects/tests/test_verification.py
git commit -m "Add is_task_actively_running() verification function

Checks if task is in Celery active list AND PID exists.
Uses psutil to verify worker process is actually running.

Part of download state verification system."
```

---

## Task 5: Implement check_download_states() Periodic Task

**Files:**
- Modify: `wafer_space/projects/tasks.py` (add new task)
- Create: `wafer_space/projects/tests/test_state_verification.py` (new test file)

**Step 1: Write test for check_download_states()**

Create `wafer_space/projects/tests/test_state_verification.py`:

```python
"""Tests for download state verification periodic task."""

from unittest.mock import Mock, patch

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase

from wafer_space.projects.models import Project, ProjectFile
from wafer_space.projects.tasks import check_download_states

User = get_user_model()
TEST_PASSWORD = "testpass123"  # noqa: S105


@pytest.mark.django_db
class DownloadStateVerificationTests(TestCase):
    """Tests for check_download_states() task."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test Description",
        )

    @patch("wafer_space.projects.tasks.download_project_file.delay")
    def test_pending_file_creates_task(self, mock_delay):
        """Test PENDING file gets task created and transitions to QUEUED."""
        # Create PENDING file with no task
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            download_status=ProjectFile.DownloadStatus.PENDING,
            is_active=False,
        )

        # Mock task creation
        mock_task = Mock()
        mock_task.id = "new-task-123"
        mock_delay.return_value = mock_task

        # Run state check
        result = check_download_states()

        # Verify task created
        mock_delay.assert_called_once_with(self.project.id)
        assert result["created_tasks"] == 1

        # Verify state transition
        project_file.refresh_from_db()
        assert project_file.download_task_id == "new-task-123"
        assert project_file.download_status == ProjectFile.DownloadStatus.QUEUED

    @patch("wafer_space.projects.tasks.is_task_queued")
    def test_queued_file_verified(self, mock_is_queued):
        """Test QUEUED file is verified and counted."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            download_status=ProjectFile.DownloadStatus.QUEUED,
            download_task_id="task-123",
            is_active=False,
        )

        # Mock verification returns True
        mock_is_queued.return_value = True

        result = check_download_states()

        assert result["verified"] == 1
        assert result["orphaned"] == 0

        # File should still be QUEUED
        project_file.refresh_from_db()
        assert project_file.download_status == ProjectFile.DownloadStatus.QUEUED

    @patch("wafer_space.projects.tasks.is_task_queued")
    def test_queued_file_orphaned(self, mock_is_queued):
        """Test QUEUED file not in queue is marked orphaned."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            download_status=ProjectFile.DownloadStatus.QUEUED,
            download_task_id="task-456",
            is_active=False,
        )

        # Mock verification returns False
        mock_is_queued.return_value = False

        result = check_download_states()

        assert result["verified"] == 0
        assert result["orphaned"] == 1

        # File should be FAILED
        project_file.refresh_from_db()
        assert project_file.download_status == ProjectFile.DownloadStatus.FAILED
        assert "not found in Celery queue" in project_file.download_error

    @patch("wafer_space.projects.tasks.is_task_actively_running")
    def test_downloading_file_verified(self, mock_is_running):
        """Test DOWNLOADING file is verified and counted."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            download_status=ProjectFile.DownloadStatus.DOWNLOADING,
            download_task_id="task-789",
            is_active=False,
        )

        # Mock verification returns True
        mock_is_running.return_value = True

        result = check_download_states()

        assert result["verified"] == 1
        assert result["orphaned"] == 0

    @patch("wafer_space.projects.tasks.is_task_actively_running")
    def test_downloading_file_orphaned(self, mock_is_running):
        """Test DOWNLOADING file not running is marked orphaned."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            download_status=ProjectFile.DownloadStatus.DOWNLOADING,
            download_task_id="task-999",
            is_active=False,
        )

        # Mock verification returns False
        mock_is_running.return_value = False

        result = check_download_states()

        assert result["verified"] == 0
        assert result["orphaned"] == 1

        # File should be FAILED
        project_file.refresh_from_db()
        assert project_file.download_status == ProjectFile.DownloadStatus.FAILED
        assert "not running" in project_file.download_error
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/projects/tests/test_state_verification.py -xvs`

Expected: FAIL with "ImportError: cannot import name 'check_download_states'"

**Step 3: Implement check_download_states()**

Add to `wafer_space/projects/tasks.py`:

```python
from .verification import is_task_actively_running, is_task_queued


@shared_task
def check_download_states():
    """Verify all downloading files are in correct state.

    Runs frequently (every 30s) - no timeout needed.

    Returns:
        dict: Status with counts of created_tasks, orphaned, verified
    """
    logger = logging.getLogger(__name__)

    created_tasks = 0
    orphaned_count = 0
    verified_count = 0

    # PENDING: Create tasks if missing
    pending_files = ProjectFile.objects.filter(
        download_status=ProjectFile.DownloadStatus.PENDING
    )

    for project_file in pending_files:
        if not project_file.download_task_id:
            # Create task and transition to QUEUED
            task = download_project_file.delay(project_file.project.id)
            project_file.download_task_id = task.id
            project_file.download_status = ProjectFile.DownloadStatus.QUEUED
            project_file.save(update_fields=["download_task_id", "download_status"])
            created_tasks += 1
            logger.info("Created task for pending file %s", project_file.id)
        else:
            # Has task - should be QUEUED
            project_file.download_status = ProjectFile.DownloadStatus.QUEUED
            project_file.save(update_fields=["download_status"])

    # QUEUED: Verify task in Celery queue
    queued_files = ProjectFile.objects.filter(
        download_status=ProjectFile.DownloadStatus.QUEUED
    ).exclude(download_task_id="")

    for project_file in queued_files:
        if is_task_queued(project_file):
            verified_count += 1
        else:
            error_msg = "Task not found in Celery queue (worker may be down)"
            logger.warning("Orphaned queued file %s", project_file.id)
            project_file.mark_download_failed(error_msg)
            orphaned_count += 1

    # DOWNLOADING: Verify task executing AND PID exists
    downloading_files = ProjectFile.objects.filter(
        download_status=ProjectFile.DownloadStatus.DOWNLOADING
    ).exclude(download_task_id="")

    for project_file in downloading_files:
        if is_task_actively_running(project_file):
            verified_count += 1
        else:
            error_msg = "Task not running (worker crashed or task failed)"
            logger.warning("Orphaned downloading file %s", project_file.id)
            project_file.mark_download_failed(error_msg)
            orphaned_count += 1

    logger.info(
        "State check: %d created, %d orphaned, %d verified",
        created_tasks,
        orphaned_count,
        verified_count,
    )

    return {
        "status": "completed",
        "created_tasks": created_tasks,
        "orphaned": orphaned_count,
        "verified": verified_count,
    }
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest wafer_space/projects/tests/test_state_verification.py -xvs`

Expected: PASS (6 tests)

**Step 5: Run linting**

Run: `make lint-fix && make lint`

Expected: No errors

**Step 6: Commit**

```bash
git add wafer_space/projects/tasks.py wafer_space/projects/tests/test_state_verification.py
git commit -m "Add check_download_states() periodic task

Replaces timeout-based orphan detection with state verification:
- PENDING: Creates tasks, transitions to QUEUED
- QUEUED: Verifies task in Celery queue
- DOWNLOADING: Verifies task running + PID exists

Part of download state verification system."
```

---

## Task 6: Update download_project_file() to Capture Worker Info

**Files:**
- Modify: `wafer_space/projects/tasks.py` (download_project_file function)

**Step 1: Write test for worker info capture**

Add to `wafer_space/projects/tests/test_state_verification.py`:

```python
@patch("wafer_space.projects.tasks.socket")
@patch("wafer_space.projects.tasks.os")
def test_download_task_captures_worker_info(self, mock_os, mock_socket):
    """Test that download task captures PID and hostname."""
    from wafer_space.projects.tasks import download_project_file

    project_file = ProjectFile.objects.create(
        project=self.project,
        source_url="http://example.com/small.txt",
        download_status=ProjectFile.DownloadStatus.QUEUED,
        download_task_id="task-123",
        is_active=True,
    )

    # Mock PID and hostname
    mock_os.getpid.return_value = 12345
    mock_socket.gethostname.return_value = "worker-01"

    # This will fail to download (no server), but should capture worker info
    try:
        download_project_file(self.project.id)
    except Exception:
        pass  # Expected to fail

    # Verify worker info was captured
    project_file.refresh_from_db()
    assert project_file.worker_pid == 12345
    assert project_file.worker_hostname == "worker-01"
    assert project_file.task_started_at is not None
```

**Step 2: Run test to verify current behavior**

Run: `uv run pytest wafer_space/projects/tests/test_state_verification.py::DownloadStateVerificationTests::test_download_task_captures_worker_info -xvs`

Expected: FAIL (worker_pid is None)

**Step 3: Update download_project_file() to capture worker info**

In `wafer_space/projects/tasks.py`, find the `download_project_file` function and add at the beginning:

```python
@shared_task(bind=True, max_retries=5, default_retry_delay=60)
def download_project_file(self, project_id):
    """Download a project file from URL."""
    import os
    import socket

    logger = logging.getLogger(__name__)

    # Get project and file
    project = Project.objects.get(id=project_id)
    project_file = project.get_active_file()

    if not project_file:
        logger.error("No active file for project %s", project_id)
        return

    # Transition QUEUED → DOWNLOADING and capture worker info
    project_file.download_status = ProjectFile.DownloadStatus.DOWNLOADING
    project_file.worker_pid = os.getpid()
    project_file.worker_hostname = socket.gethostname()
    project_file.task_started_at = timezone.now()
    project_file.save(
        update_fields=[
            "download_status",
            "worker_pid",
            "worker_hostname",
            "task_started_at",
        ]
    )

    logger.info(
        "Download started: file=%s, PID=%s, host=%s, task_id=%s",
        project_file.id,
        project_file.worker_pid,
        project_file.worker_hostname,
        self.request.id,
    )

    # Continue with existing download logic...
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest wafer_space/projects/tests/test_state_verification.py::DownloadStateVerificationTests::test_download_task_captures_worker_info -xvs`

Expected: PASS

**Step 5: Run all tests**

Run: `make test`

Expected: All tests pass

**Step 6: Commit**

```bash
git add wafer_space/projects/tasks.py wafer_space/projects/tests/test_state_verification.py
git commit -m "Update download task to capture worker info

Captures PID, hostname, and start time when task begins.
Transitions QUEUED → DOWNLOADING at task start.

Part of download state verification system."
```

---

## Task 7: Update Settings and Celery Beat Schedule

**Files:**
- Modify: `config/settings/base.py`
- Modify: `config/settings/local.py`

**Step 1: Update base.py settings**

In `config/settings/base.py`, replace old timeout settings with new check interval:

```python
# Download state verification configuration (production)
DOWNLOAD_STATE_CHECK_INTERVAL_SECONDS = 60.0  # Check every 1 minute

# Celery Beat periodic tasks
CELERY_BEAT_SCHEDULE = {
    "retry-failed-downloads": {
        "task": "wafer_space.projects.tasks.retry_failed_downloads",
        "schedule": DOWNLOAD_RETRY_CHECK_INTERVAL_SECONDS,
    },
    "check-download-states": {
        "task": "wafer_space.projects.tasks.check_download_states",
        "schedule": DOWNLOAD_STATE_CHECK_INTERVAL_SECONDS,
    },
    # Remove old: "check-orphaned-downloads"
}

# Remove these old settings:
# DOWNLOAD_ORPHAN_TIMEOUT_SECONDS = 900.0
# DOWNLOAD_PENDING_TIMEOUT_SECONDS = 600.0
# DOWNLOAD_ORPHAN_CHECK_INTERVAL_SECONDS = 300.0
```

**Step 2: Update local.py settings**

In `config/settings/local.py`, override with faster dev interval:

```python
# Download state verification - faster checks in development
DOWNLOAD_STATE_CHECK_INTERVAL_SECONDS = 30.0  # Check every 30 seconds

# Override Celery Beat schedule
CELERY_BEAT_SCHEDULE = {
    "retry-failed-downloads": {
        "task": "wafer_space.projects.tasks.retry_failed_downloads",
        "schedule": DOWNLOAD_RETRY_CHECK_INTERVAL_SECONDS,
    },
    "check-download-states": {
        "task": "wafer_space.projects.tasks.check_download_states",
        "schedule": DOWNLOAD_STATE_CHECK_INTERVAL_SECONDS,
    },
}
```

**Step 3: Verify settings load**

Run: `uv run python manage.py check`

Expected: No errors

**Step 4: Commit**

```bash
git add config/settings/base.py config/settings/local.py
git commit -m "Update settings for download state verification

Replaced timeout-based config with check interval.
Production: 60s, Development: 30s.

Removed old check-orphaned-downloads from beat schedule.

Part of download state verification system."
```

---

## Task 8: Remove Old check_orphaned_downloads() Task

**Files:**
- Modify: `wafer_space/projects/tasks.py` (remove old function)
- Remove: `wafer_space/projects/tests/test_tasks.py::OrphanedDownloadDetectionTests`

**Step 1: Remove old test class**

In `wafer_space/projects/tests/test_tasks.py`, delete the entire `OrphanedDownloadDetectionTests` class (should be around lines 444-683).

**Step 2: Run tests to verify old tests removed**

Run: `uv run pytest wafer_space/projects/tests/test_tasks.py -v | grep -i orphan`

Expected: No output (old tests gone)

**Step 3: Remove old check_orphaned_downloads() function**

In `wafer_space/projects/tasks.py`, delete the `check_orphaned_downloads()` function (should be around lines 1260-1365).

**Step 4: Run all tests to verify nothing breaks**

Run: `make test`

Expected: All tests pass

**Step 5: Commit**

```bash
git add wafer_space/projects/tasks.py wafer_space/projects/tests/test_tasks.py
git commit -m "Remove old timeout-based orphan detection

Deleted check_orphaned_downloads() task and tests.
Replaced by state-based check_download_states().

Part of download state verification system."
```

---

## Task 9: Run Migrations and Full Test Suite

**Files:**
- N/A (migration verification)

**Step 1: Run all migrations**

Run: `uv run python manage.py migrate`

Expected: All migrations apply successfully

**Step 2: Run full test suite**

Run: `make test`

Expected: All tests pass

**Step 3: Run type checking**

Run: `make type-check`

Expected: No type errors

**Step 4: Run linting**

Run: `make lint`

Expected: No lint errors

**Step 5: Verify in dev environment**

Run development server and worker:
```bash
make runserver  # Terminal 1
make celery     # Terminal 2
```

Create a test file upload and verify logs show:
- "Download started: file=X, PID=Y, host=Z"
- "State check: X created, Y orphaned, Z verified"

**Step 6: Commit verification note**

```bash
git commit --allow-empty -m "Verify download state verification system

All tests passing, migrations applied, type checking clean.
System ready for production deployment.

Completed download state verification implementation."
```

---

## Task 10: Update Documentation

**Files:**
- Create: `docs/download-state-verification.md`

**Step 1: Create user documentation**

Create `docs/download-state-verification.md`:

```markdown
# Download State Verification System

## Overview

The download state verification system ensures that file downloads are properly tracked and orphaned downloads are detected and recovered.

## Download States

1. **PENDING**: File uploaded, no Celery task created yet
2. **QUEUED**: Task created and in Celery queue
3. **DOWNLOADING**: Worker actively downloading file
4. **COMPLETED**: Download successful
5. **FAILED**: Download failed or orphaned

## Verification Process

### PENDING Files
- System creates Celery task if missing
- Auto-transitions to QUEUED when task created

### QUEUED Files
- Verifies task exists in Celery reserved queue
- Auto-transitions to DOWNLOADING when task starts
- Marks as FAILED if task not found

### DOWNLOADING Files
- Verifies task in Celery active list
- Verifies worker process (PID) exists
- Marks as FAILED if task not running or PID dead

## Configuration

- **Production**: Check every 60 seconds
- **Development**: Check every 30 seconds

## Monitoring

Check logs for:
```
State check: X created, Y orphaned, Z verified
```

## Troubleshooting

**File stuck in PENDING**:
- Check Celery worker is running
- Check logs for task creation

**File stuck in QUEUED**:
- Check Celery queue has capacity
- Verify worker is accepting tasks

**File stuck in DOWNLOADING**:
- Check worker didn't crash (PID verification)
- Check network connectivity

All orphaned files trigger auto-retry if enabled.
```

**Step 2: Commit documentation**

```bash
git add docs/download-state-verification.md
git commit -m "Add documentation for download state verification

User-facing documentation explaining states, verification,
configuration, and troubleshooting.

Completed download state verification implementation."
```

---

## Summary

Total tasks: 10
Estimated time: 4-6 hours
Files created: 3
Files modified: 6
Tests added: ~25
Lines of code: ~500

**Verification checklist:**
- [ ] All migrations applied
- [ ] All tests pass
- [ ] Type checking clean
- [ ] Linting clean
- [ ] Dev environment verified
- [ ] Documentation complete
