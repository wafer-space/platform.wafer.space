# Download State Verification System Design

**Date:** 2025-10-22
**Status:** Approved
**Author:** Claude Code

## Problem Statement

The current orphaned download detection system has two critical issues:

1. **Conflated States**: The PENDING status represents both "file uploaded, waiting to be queued" and "task queued in Celery". This prevents accurate state verification.

2. **Incomplete Verification**: The system checks TaskResult database records but doesn't verify if Celery tasks are actually running or if worker processes exist. This leads to false negatives where downloads appear active but the worker has crashed.

**Real-world impact:** Files stuck in DOWNLOADING state with messages like "no activity for 120.0s (task may have crashed)" or PENDING files with "never started - pending for 60.0s (worker may be down)" without proper verification.

## Solution Overview

Implement a proper state machine with explicit download states and multi-layer verification that checks actual Celery queue state and process existence.

### Key Principles

1. **Explicit States**: Separate PENDING (not queued), QUEUED (in Celery), and DOWNLOADING (executing)
2. **No Timeouts**: Verify actual state instead of timeout-based detection
3. **Multi-Layer Verification**: Check TaskResult, Celery inspect API, and PID existence
4. **Frequent Checks**: Run every 30 seconds (no performance impact due to small file count)

## Download State Machine

### States

```python
class DownloadStatus(models.TextChoices):
    PENDING = "pending", "Pending"           # File uploaded, no task created
    QUEUED = "queued", "Queued"              # Task created, in Celery queue
    DOWNLOADING = "downloading", "Downloading"  # Task actively executing
    COMPLETED = "completed", "Completed"     # Successfully downloaded
    FAILED = "failed", "Failed"              # Error occurred
```

### State Transitions

```
PENDING → QUEUED → DOWNLOADING → COMPLETED
   ↓         ↓           ↓
   └─────────┴───────────┴─────→ FAILED
```

### State Descriptions

| State | Meaning | Expected Celery State | Verification Method |
|-------|---------|----------------------|---------------------|
| PENDING | File uploaded, awaiting task creation | No task exists | Create task if missing |
| QUEUED | Task created, waiting in Celery queue | In `inspect.reserved()` | Check reserved queue |
| DOWNLOADING | Worker executing download | In `inspect.active()` + PID exists | Check active list + PID |
| COMPLETED | Download successful | Task SUCCESS | N/A |
| FAILED | Download failed or orphaned | Task FAILURE or missing | N/A |

## Database Schema Changes

### ProjectFile Model Updates

Add new fields for tracking worker execution:

```python
class ProjectFile(models.Model):
    # ... existing fields ...

    # New fields for worker tracking
    worker_pid = models.IntegerField(
        null=True,
        blank=True,
        help_text="Process ID of Celery worker executing download"
    )
    worker_hostname = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Hostname of worker machine"
    )
    task_started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When download task actually began execution"
    )
```

### Migration

Create migration to:
1. Add `QUEUED` to DownloadStatus choices
2. Add `worker_pid`, `worker_hostname`, `task_started_at` fields
3. Backfill existing PENDING files: keep as PENDING if no task_id, move to QUEUED if has task_id

## Implementation Details

### 1. State Verification Task

Replace `check_orphaned_downloads` with new `check_download_states` task:

```python
@shared_task
def check_download_states():
    """Verify all downloading files are in correct state.

    Runs frequently (every 30s) - no timeout needed.
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
            from .tasks import download_project_file
            task = download_project_file.delay(project_file.project.id)
            project_file.download_task_id = task.id
            project_file.download_status = ProjectFile.DownloadStatus.QUEUED
            project_file.save(update_fields=['download_task_id', 'download_status'])
            created_tasks += 1
        else:
            # Has task - should be QUEUED
            project_file.download_status = ProjectFile.DownloadStatus.QUEUED
            project_file.save(update_fields=['download_status'])

    # QUEUED: Verify task in Celery queue
    queued_files = ProjectFile.objects.filter(
        download_status=ProjectFile.DownloadStatus.QUEUED
    ).exclude(download_task_id="")

    for project_file in queued_files:
        if is_task_queued(project_file):
            verified_count += 1
        else:
            error_msg = "Task not found in Celery queue"
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
            error_msg = "Task not running (worker crashed)"
            project_file.mark_download_failed(error_msg)
            orphaned_count += 1

    logger.info(
        "State check: %d created, %d orphaned, %d verified",
        created_tasks,
        orphaned_count,
        verified_count
    )

    return {
        "status": "completed",
        "created_tasks": created_tasks,
        "orphaned": orphaned_count,
        "verified": verified_count,
    }
```

### 2. Verification Functions

**QUEUED State Verification:**

```python
def is_task_queued(project_file) -> bool:
    """Verify task is in Celery queue (reserved but not started)."""
    from celery import current_app

    task_id = project_file.download_task_id
    inspect = current_app.control.inspect()

    # Check reserved queue
    reserved = inspect.reserved()
    if reserved:
        for worker, tasks in reserved.items():
            if any(t['id'] == task_id for t in tasks):
                return True

    # Check if task started (auto-transition)
    active = inspect.active()
    if active:
        for worker, tasks in active.items():
            if any(t['id'] == task_id for t in tasks):
                # Update state to DOWNLOADING
                project_file.download_status = ProjectFile.DownloadStatus.DOWNLOADING
                project_file.save(update_fields=['download_status'])
                return True

    return False
```

**DOWNLOADING State Verification:**

```python
def is_task_actively_running(project_file) -> bool:
    """Verify task is executing AND process exists."""
    from celery import current_app
    import socket
    import psutil

    task_id = project_file.download_task_id
    inspect = current_app.control.inspect()

    # Check task in active list
    active = inspect.active()
    task_in_active = False

    if active:
        for worker, tasks in active.items():
            if any(t['id'] == task_id for t in tasks):
                task_in_active = True
                break

    if not task_in_active:
        return False

    # Verify PID exists (MANDATORY if available)
    if project_file.worker_pid and project_file.worker_hostname:
        if socket.gethostname() == project_file.worker_hostname:
            try:
                if not psutil.pid_exists(project_file.worker_pid):
                    return False

                proc = psutil.Process(project_file.worker_pid)
                cmdline = ' '.join(proc.cmdline()).lower()

                if 'celery' not in cmdline:
                    return False
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return False

    return True
```

### 3. Task Updates

**When download task starts:**

```python
@shared_task(bind=True)
def download_project_file(self, project_id):
    import os
    import socket

    project_file = get_project_file(project_id)

    # Transition QUEUED → DOWNLOADING
    # Capture worker info for verification
    project_file.download_status = ProjectFile.DownloadStatus.DOWNLOADING
    project_file.worker_pid = os.getpid()
    project_file.worker_hostname = socket.gethostname()
    project_file.task_started_at = timezone.now()
    project_file.save(update_fields=[
        'download_status',
        'worker_pid',
        'worker_hostname',
        'task_started_at'
    ])

    logger.info(
        "Download started: file=%s, PID=%s, host=%s, task_id=%s",
        project_file.id,
        project_file.worker_pid,
        project_file.worker_hostname,
        self.request.id
    )

    # Continue with download...
```

**When download completes:**

```python
# At end of successful download
project_file.download_status = ProjectFile.DownloadStatus.COMPLETED
project_file.download_completed_at = timezone.now()
project_file.save(update_fields=['download_status', 'download_completed_at'])
```

## Configuration

### Settings Updates

```python
# config/settings/base.py
# Remove old timeout-based settings
# DOWNLOAD_ORPHAN_TIMEOUT_SECONDS = 900.0  # DELETE
# DOWNLOAD_PENDING_TIMEOUT_SECONDS = 600.0  # DELETE

# New: State check frequency
DOWNLOAD_STATE_CHECK_INTERVAL_SECONDS = 60.0  # 1 minute in production

# config/settings/local.py
DOWNLOAD_STATE_CHECK_INTERVAL_SECONDS = 30.0  # 30 seconds in dev

# Celery Beat schedule
CELERY_BEAT_SCHEDULE = {
    "check-download-states": {
        "task": "wafer_space.projects.tasks.check_download_states",
        "schedule": DOWNLOAD_STATE_CHECK_INTERVAL_SECONDS,
    },
    "retry-failed-downloads": {
        "task": "wafer_space.projects.tasks.retry_failed_downloads",
        "schedule": DOWNLOAD_RETRY_CHECK_INTERVAL_SECONDS,
    },
    # Remove: "check-orphaned-downloads"
}
```

## Testing Strategy

### Test Cases

1. **PENDING → QUEUED: Auto-create task**
   - Given: File in PENDING, no task_id
   - When: check_download_states runs
   - Then: Task created, status → QUEUED

2. **QUEUED: Task in queue (verified)**
   - Given: File in QUEUED with task_id
   - When: Mock inspect.reserved() returns task
   - Then: File NOT orphaned, verified_count increments

3. **QUEUED: Task missing (orphaned)**
   - Given: File in QUEUED with task_id
   - When: Mock inspect returns empty
   - Then: File marked as FAILED (orphaned)

4. **QUEUED → DOWNLOADING: Auto-transition**
   - Given: File in QUEUED
   - When: Mock inspect.active() returns task
   - Then: Status automatically transitions to DOWNLOADING

5. **DOWNLOADING: Task running + PID exists (verified)**
   - Given: File in DOWNLOADING with worker_pid
   - When: Mock inspect.active() returns task AND PID exists
   - Then: File NOT orphaned

6. **DOWNLOADING: Task in active but PID dead (orphaned)**
   - Given: File in DOWNLOADING with worker_pid
   - When: Mock inspect.active() returns task BUT PID doesn't exist
   - Then: File marked as FAILED (worker crashed)

7. **DOWNLOADING: Task not in active (orphaned)**
   - Given: File in DOWNLOADING
   - When: Mock inspect.active() returns empty
   - Then: File marked as FAILED

8. **Integration: Full lifecycle**
   - Given: New file uploaded
   - Then: PENDING → task created → QUEUED → starts → DOWNLOADING → completes → COMPLETED

### Test Implementation Notes

- Use `@patch('wafer_space.projects.tasks.current_app.control.inspect')` for Celery mocking
- Use `@patch('psutil.pid_exists')` and `@patch('psutil.Process')` for PID verification
- Create separate test class: `DownloadStateVerificationTests`
- Follow existing pattern from `OrphanedDownloadDetectionTests`

## Migration Path

### Step 1: Database Migration
1. Add QUEUED to DownloadStatus choices
2. Add worker_pid, worker_hostname, task_started_at fields
3. Backfill: Files with task_id but PENDING status → QUEUED

### Step 2: Code Updates
1. Add new verification functions
2. Update download_project_file to capture PID/hostname
3. Replace check_orphaned_downloads with check_download_states

### Step 3: Configuration
1. Update settings files (remove timeouts, add check interval)
2. Update Celery beat schedule

### Step 4: Testing
1. Write comprehensive test suite (8 test cases)
2. Run tests to ensure 100% pass rate
3. Manual verification in dev environment

### Step 5: Deployment
1. Run migration in production
2. Deploy code changes
3. Monitor logs for "State check:" messages
4. Verify orphaned files are properly detected

## Benefits

1. **Accurate Detection**: Multi-layer verification catches all orphan cases
2. **No False Positives**: Verify actual Celery state instead of timeouts
3. **Clear States**: Explicit state machine makes debugging easier
4. **Fast Recovery**: 30-60 second check interval vs 2-15 minute timeouts
5. **Better Logging**: Clear messages about what verification failed

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| inspect API slow/unreliable | Orphans not detected | Add timeout to inspect calls, fall back to PID check |
| PID reuse (old PID reassigned) | False positive | Check process is actually Celery worker |
| Remote workers can't check PID | Missing verification layer | Skip PID check for remote hosts, trust inspect API |
| Migration backfill errors | Files stuck in wrong state | Test migration on copy of production data first |

## Future Enhancements

1. **Heartbeat System**: Tasks update heartbeat timestamp every 30s as additional verification
2. **Worker Health Monitoring**: Track worker crash patterns to predict failures
3. **Auto-scaling**: Detect queue buildup and recommend scaling workers
4. **Metrics Dashboard**: Visualize state transitions and orphan detection rate

## References

- Celery Inspect API: https://docs.celeryq.dev/en/stable/userguide/workers.html#inspecting-workers
- psutil Process Management: https://psutil.readthedocs.io/en/latest/
- Django Model Choices: https://docs.djangoproject.com/en/5.2/ref/models/fields/#choices
