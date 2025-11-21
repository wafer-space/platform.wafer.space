# Download Queue and Retry Architecture

**Document Status:** Current implementation (updated 2025-01-21)
**Purpose:** Comprehensive explanation of download retry system using Celery

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [System Components](#system-components)
3. [Download Lifecycle](#download-lifecycle)
4. [Retry Mechanism](#retry-mechanism)
5. [State Management](#state-management)
6. [Configuration Reference](#configuration-reference)
7. [Changes from Previous Implementation](#changes-from-previous-implementation)

---

## Architecture Overview

The download system uses **Celery's built-in retry mechanism** with a fallback verification system:

```
┌─────────────────────────────────────────────────────────────┐
│  1. Celery Task Queue (Built-in Retry Only)                 │
│     - Automatic retries with exponential backoff            │
│     - Max 3 retries (configurable via settings)             │
│     - Delays: 5s, 30s, 2min (configurable)                  │
│     - Total: 3 attempts over ~2.5 minutes                   │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  2. Fallback Verification (State Consistency Check)         │
│     - Verifies tasks exist in Celery queue                  │
│     - Verifies worker processes are running                 │
│     - Re-creates missing tasks (queue loss recovery)        │
│     - Runs every 30 seconds                                 │
└─────────────────────────────────────────────────────────────┘
```

**Total Retry Attempts:** 3 (configurable via `DOWNLOAD_MAX_RETRIES` setting)

**Key Architectural Decisions:**
- ✅ Use Celery's native retry mechanism (not reimplemented)
- ✅ Configurable retry delays via Django settings
- ✅ Each attempt tracked in DownloadAttempt model
- ✅ Download status computed from DownloadAttempt records
- ✅ Fallback verification for queue loss recovery

---

## System Components

### Database Models

#### ProjectFile.download_status (Computed Property)

```python
@property
def download_status(self) -> str:
    """Derive status from download_task_id and DownloadAttempt records."""
    # PENDING: No task_id set
    if not self.download_task_id:
        return self.DownloadStatus.PENDING

    # Get latest attempt
    latest = self.latest_attempt
    if not latest:
        # QUEUED: Has task_id but no attempt yet
        return self.DownloadStatus.QUEUED

    # Return status from latest attempt
    return latest.status
```

**Status Values:**
- `PENDING`: File created, no Celery task queued yet
- `QUEUED`: Task queued in Celery, waiting for worker
- `DOWNLOADING`: Worker executing download (has active DownloadAttempt)
- `COMPLETED`: Download successful (latest attempt completed)
- `FAILED`: Download failed (latest attempt failed, retries exhausted)

**Key Change:** `download_status` is now a **computed property**, not a database field. It derives the status from the `download_task_id` and DownloadAttempt records.

#### DownloadAttempt States

```python
class Status(models.TextChoices):
    PENDING = "pending"        # Attempt created, not started
    DOWNLOADING = "downloading" # Attempt in progress
    COMPLETED = "completed"     # Attempt successful
    FAILED = "failed"          # Attempt failed (will retry or give up)
```

**Relationship:**
- Each `ProjectFile` has multiple `DownloadAttempt` records (one per retry)
- Each `ProjectFile` has ONE `download_task_id` (current Celery task)
- Only ONE `ProjectFile` can be `is_active=True` per project
- Worker info (PID, hostname, task_started_at) stored on DownloadAttempt

### Celery Components

#### Task Definition
```python
# tasks.py
@shared_task(
    bind=True,
    max_retries=settings.DOWNLOAD_MAX_RETRIES,  # Default: 3
    autoretry_for=(OSError, ValueError, requests.RequestException),
    retry_backoff=True,
    retry_backoff_max=settings.DOWNLOAD_RETRY_BACKOFF_MAX,  # Default: 120s
    retry_jitter=False,
)
def download_project_file(self, project_id):
```

**Celery Features Used:**
- `bind=True` - Access to task instance (`self`)
- `max_retries` - Celery's built-in retry limit (from settings)
- `autoretry_for` - Automatically retry on these exceptions
- `retry_backoff=True` - Exponential backoff (delays from settings)
- `retry_backoff_max` - Maximum retry delay
- `self.request.retries` - Current retry count (used for attempt_number)

**Retry Delays (Configurable):**
```python
# config/settings/base.py
DOWNLOAD_RETRY_DELAYS = [5, 30, 120]  # 5s, 30s, 2min
DOWNLOAD_MAX_RETRIES = 3  # Total attempts
DOWNLOAD_RETRY_BACKOFF_MAX = 120  # Max 2 minutes between retries
```

#### Periodic Tasks (Celery Beat)
```python
# settings/base.py
CELERY_BEAT_SCHEDULE = {
    "check-download-states": {
        "task": "wafer_space.projects.tasks.verify_download_states",
        "schedule": 30.0,  # Every 30 seconds
    },
}
```

**Note:** The old `retry-failed-downloads` periodic task has been **removed**. Celery handles all retries automatically.

---

## Download Lifecycle

### Phase 1: Initial Queuing

**Code:** `wafer_space/projects/services.py::ProjectFileService.submit_file_from_url()`

```python
# Step 1: Create ProjectFile record
project_file = ProjectFile.objects.create(
    project=project,
    original_url=url,
    source_url=rewritten_url,
    # No download_status field - it's a @property
)

# Step 2: Queue Celery task
task = download_project_file.delay(str(project.id))

# Step 3: Store task ID
project_file.download_task_id = task.id
project_file.save(update_fields=["download_task_id"])

# download_status property now returns "queued"
assert project_file.download_status == ProjectFile.DownloadStatus.QUEUED
```

**State Transitions:**
```
PENDING (no task_id) → QUEUED (has task_id, no attempt)
```

---

### Phase 2: Task Execution

**Code:** `wafer_space/projects/tasks.py::download_project_file()`

```python
# Step 1: Create DownloadAttempt record
attempt = DownloadAttempt.objects.create(
    project_file=project_file,
    attempt_number=self.request.retries + 1,  # 1, 2, or 3
    status=DownloadAttempt.Status.DOWNLOADING,
    worker_pid=os.getpid(),
    worker_hostname=socket.gethostname(),
    task_started_at=timezone.now(),
)

# download_status property now returns "downloading"
assert project_file.download_status == ProjectFile.DownloadStatus.DOWNLOADING

# Step 2: Download file with progress tracking
_download_with_progress(self, project_file, attempt, temp_path)

# Step 3: Process content (extract, validate, hash)
processed_content, final_md5, final_sha1 = _process_and_save_content(
    project_file, attempt, content, temp_path
)

# Step 4: Mark attempt as COMPLETED
attempt.status = DownloadAttempt.Status.COMPLETED
attempt.completed_at = timezone.now()
attempt.save()

# download_status property now returns "completed"
assert project_file.download_status == ProjectFile.DownloadStatus.COMPLETED
```

**State Transitions:**
```
QUEUED → DOWNLOADING → COMPLETED
```

**What happens:**
1. Worker picks up task from queue
2. DownloadAttempt created with worker info (PID, hostname, timestamps)
3. File downloaded in chunks with progress updates
4. Content pipeline extracts/validates/hashes file
5. Attempt marked COMPLETED
6. ProjectFile.download_status property reflects completion

---

### Phase 3: Failure and Retry Handling

**Code:** `wafer_space/projects/tasks.py::download_project_file()` exception handler

```python
# Celery auto-retry configured in @shared_task decorator
# No manual retry() call needed - Celery handles it automatically

except (OSError, ValueError, requests.RequestException) as exc:
    # Mark current attempt as failed
    latest = project_file.latest_attempt
    if latest:
        latest.status = DownloadAttempt.Status.FAILED
        latest.download_error = str(exc)
        latest.completed_at = timezone.now()
        latest.save()

    # Update ProjectFile error info
    project_file.mark_download_failed(str(exc))

    # Celery will automatically retry based on decorator config
    # - Checks self.request.retries < max_retries
    # - Applies exponential backoff from retry_delays setting
    # - Creates new execution with incremented retry count
    # - If max retries exceeded, raises exception (task fails)
```

**State Transitions:**
```
DOWNLOADING → FAILED (attempt marked failed)
            ↓
(Celery retry delay: 5s, 30s, or 2min)
            ↓
DOWNLOADING (new attempt created)
```

**After all Celery retries exhausted:**
```
DOWNLOADING → FAILED (permanent, no more retries)
```

**What happens during Celery retries:**
1. Exception caught (network error, timeout, validation failure)
2. Current DownloadAttempt marked FAILED with error message
3. ProjectFile.download_error updated
4. Celery automatically retries based on `autoretry_for` and retry settings
5. Task sleeps for configured delay (5s, 30s, or 2min)
6. **Same task retries** (keeps same `download_task_id`)
7. New DownloadAttempt created for retry (attempt_number increments)
8. Repeat until max_retries (default: 3) reached

**After final Celery retry fails:**
1. Latest DownloadAttempt remains FAILED
2. ProjectFile.download_status property returns FAILED
3. Error notification sent to user
4. No further retries (auto-retry system removed)

---

## Retry Mechanism

### Celery Built-in Retries (Only Mechanism)

**Type:** Task-level retry (Celery native functionality)
**Trigger:** Exception raised during task execution
**Configuration:** Via Django settings

**Retry Schedule:**
```python
# config/settings/base.py
DOWNLOAD_RETRY_DELAYS = [5, 30, 120]  # seconds
DOWNLOAD_MAX_RETRIES = 3
DOWNLOAD_RETRY_BACKOFF_MAX = 120  # 2 minutes max

# Actual delays:
Attempt 1: Initial (immediate)
Attempt 2: +5 seconds   (retry 1)
Attempt 3: +30 seconds  (retry 2)
Attempt 4: +120 seconds (retry 3, if max_retries=4)
────────────────────────────
Total: 3 attempts over ~2.5 minutes (default config)
```

**Celery Behavior:**
- **Same task retries** - `download_task_id` does NOT change
- Uses `autoretry_for` to automatically retry on exceptions
- Uses `retry_backoff=True` for exponential delays
- Each retry creates new DownloadAttempt with incremented attempt_number
- Final state: `SUCCESS` or `FAILURE`

**Configurable Delays:**
The retry delays are fully configurable via settings. Production may use longer delays:

```python
# Aggressive retry (fast failure):
DOWNLOAD_RETRY_DELAYS = [5, 30, 120]  # ~2.5 minutes total

# Moderate retry (balance):
DOWNLOAD_RETRY_DELAYS = [30, 300, 1800]  # ~35 minutes total

# Patient retry (maximum persistence):
DOWNLOAD_RETRY_DELAYS = [60, 600, 3600]  # ~1 hour total
```

**Key Point:** This uses **CELERY FUNCTIONALITY** - we're not reimplementing retry logic, just configuring Celery's built-in mechanism.

---

## State Management

### Computed Download Status

The `download_status` is now a **computed property**, not a database field:

```python
@property
def download_status(self) -> str:
    """Derive status from download_task_id and DownloadAttempt records.

    Status logic:
    - PENDING: No task_id set (file created but not queued)
    - QUEUED: Has task_id but no DownloadAttempt (waiting for worker)
    - DOWNLOADING/COMPLETED/FAILED: Determined by latest DownloadAttempt
    """
    if not self.download_task_id:
        return self.DownloadStatus.PENDING

    latest = self.latest_attempt
    if not latest:
        return self.DownloadStatus.QUEUED

    return latest.status
```

**Benefits:**
- Single source of truth (DownloadAttempt records)
- No state synchronization issues
- Automatic state derivation
- Clearer separation of concerns

### Worker Tracking

Worker information moved from ProjectFile to DownloadAttempt:

```python
class DownloadAttempt(models.Model):
    worker_pid = models.IntegerField(null=True, blank=True)
    worker_hostname = models.CharField(max_length=255, blank=True)
    task_started_at = models.DateTimeField(null=True, blank=True)
```

**Each attempt records:**
- Process ID of worker executing the attempt
- Hostname of worker machine
- Timestamp when Celery task started

This enables:
- Per-attempt worker tracking (useful for debugging retries)
- Process verification (detect crashed workers)
- Performance analysis across different workers

---

## Configuration Reference

### Production Settings (`config/settings/base.py`)

```python
# Celery Task Retry Configuration
DOWNLOAD_MAX_RETRIES = 3  # Total: 3 attempts
DOWNLOAD_RETRY_DELAYS = [5, 30, 120]  # 5s, 30s, 2min
DOWNLOAD_RETRY_BACKOFF_MAX = 120  # Max 2 minutes between retries

# Periodic Tasks
DOWNLOAD_STATE_CHECK_INTERVAL_SECONDS = 30.0  # Every 30 seconds

# Celery Beat Schedule
CELERY_BEAT_SCHEDULE = {
    "check-download-states": {
        "task": "wafer_space.projects.tasks.verify_download_states",
        "schedule": DOWNLOAD_STATE_CHECK_INTERVAL_SECONDS,
    },
}
```

### Development Settings (`config/settings/dev.py`)

```python
# Same as production - fast retries for quick testing
DOWNLOAD_MAX_RETRIES = 3
DOWNLOAD_RETRY_DELAYS = [5, 30, 120]  # 5s, 30s, 2min
DOWNLOAD_STATE_CHECK_INTERVAL_SECONDS = 30.0
```

### Task Decorator (Applied Automatically)

```python
@shared_task(
    bind=True,
    max_retries=settings.DOWNLOAD_MAX_RETRIES,
    autoretry_for=(OSError, ValueError, requests.RequestException),
    retry_backoff=True,
    retry_backoff_max=settings.DOWNLOAD_RETRY_BACKOFF_MAX,
    retry_jitter=False,
)
def download_project_file(self, project_id):
    """Download and process a project file with automatic retries."""
```

---

## Changes from Previous Implementation

### What Was Removed

1. **Auto-Retry System (Custom Re-queuing)**
   - ❌ Removed `retry_failed_downloads()` periodic task
   - ❌ Removed `ProjectFile.retry_count` field
   - ❌ Removed `ProjectFile.max_retries` field
   - ❌ Removed `ProjectFile.auto_retry_enabled` field
   - ❌ Removed `ProjectFile.next_retry_at` field
   - ❌ Removed 18-attempt retry (6 Celery × 3 auto-retry cycles)

2. **Database Fields**
   - ❌ Removed `ProjectFile.download_status` CharField
   - ❌ Removed `ProjectFile.worker_pid` field
   - ❌ Removed `ProjectFile.worker_hostname` field
   - ❌ Removed `ProjectFile.task_started_at` field

**Rationale:** The auto-retry system was redundant with Celery's built-in retry mechanism and caused excessive retries (18 attempts total). Celery already provides exponential backoff and retry counting.

### What Was Added

1. **Computed Download Status**
   - ✅ `ProjectFile.download_status` is now a `@property`
   - ✅ Derives status from `download_task_id` and DownloadAttempt records
   - ✅ Single source of truth (no state synchronization)

2. **Worker Tracking per Attempt**
   - ✅ `DownloadAttempt.worker_pid` - Process ID of worker
   - ✅ `DownloadAttempt.worker_hostname` - Worker machine hostname
   - ✅ `DownloadAttempt.task_started_at` - Task start timestamp
   - ✅ Enables per-attempt debugging and performance analysis

3. **Configurable Retry Delays**
   - ✅ `DOWNLOAD_RETRY_DELAYS` setting (list of delays in seconds)
   - ✅ `DOWNLOAD_MAX_RETRIES` setting (total attempts)
   - ✅ `DOWNLOAD_RETRY_BACKOFF_MAX` setting (max delay cap)
   - ✅ Production-ready defaults with easy customization

4. **UI Improvements**
   - ✅ Download attempt history displayed to users
   - ✅ Shows all retry attempts with timestamps, errors, worker info
   - ✅ Collapsible details panel (only shown when >1 attempts)

### What Was Kept

1. **Fallback Verification System**
   - ✅ `verify_download_states()` periodic task (every 30 seconds)
   - ✅ Detects missing tasks in Celery queue
   - ✅ Verifies worker processes are running
   - ✅ Re-creates tasks if queue lost (ephemeral queue recovery)
   - ✅ Essential for production reliability

2. **Download Attempt Tracking**
   - ✅ `DownloadAttempt` model tracks each retry
   - ✅ Progress checkpoints (`ProjectFileChunk`)
   - ✅ Error logging per attempt
   - ✅ Performance metrics (duration, speed, bytes downloaded)

3. **Celery Infrastructure**
   - ✅ PostgreSQL as Celery broker (via SQLAlchemy)
   - ✅ django-db result backend
   - ✅ Celery Beat for periodic tasks
   - ✅ Task inspection API (`inspect.reserved()`, `inspect.active()`)

### Migration Impact

**Database Migration Required:** Yes

The migration:
- Adds `worker_pid`, `worker_hostname`, `task_started_at` to DownloadAttempt
- Removes `download_status`, `worker_pid`, `worker_hostname`, etc. from ProjectFile
- Removes `retry_count`, `max_retries`, `auto_retry_enabled`, `next_retry_at` from ProjectFile
- **Data loss:** Existing download_status values are discarded (clean break)

**Why Clean Break:**
The old retry system tracked state differently, so migration would be complex and error-prone. A clean break ensures consistent state going forward.

**User Impact:**
- Existing in-progress downloads will restart from PENDING
- Historical retry counts are lost (fresh start)
- Benefits: Simpler system, fewer retries, better visibility

---

## Summary

**Architecture:**
- ✅ Celery-native retry mechanism (3 attempts, configurable)
- ✅ Exponential backoff (5s, 30s, 2min by default)
- ✅ Fallback verification for queue loss recovery
- ✅ Download status computed from DownloadAttempt records
- ✅ Per-attempt worker tracking for debugging

**Key Benefits:**
- 🎯 **Simplicity:** One retry system (Celery), not two
- 🎯 **Configurability:** All delays/limits via Django settings
- 🎯 **Transparency:** Users see full retry history
- 🎯 **Reliability:** Fallback verification handles queue loss
- 🎯 **Debuggability:** Per-attempt worker info for troubleshooting

**What Changed:**
- ❌ Removed auto-retry system (18 attempts → 3 attempts)
- ❌ Removed duplicate retry logic and state tracking
- ✅ Added computed download_status property
- ✅ Added per-attempt worker tracking
- ✅ Added configurable retry delays
- ✅ Added attempt history UI

**Configuration:**
```python
# Customize retry behavior via settings
DOWNLOAD_MAX_RETRIES = 3  # Number of retry attempts
DOWNLOAD_RETRY_DELAYS = [5, 30, 120]  # Delays between retries (seconds)
DOWNLOAD_RETRY_BACKOFF_MAX = 120  # Maximum delay cap (seconds)
```

The system is now **simpler**, **more configurable**, and **easier to understand** while maintaining all essential reliability features.
