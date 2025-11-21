# Download Queue and Retry Architecture

**Document Status:** Analysis of current implementation (as of 2025-01-21)
**Purpose:** Comprehensive explanation of how Celery queue and retry systems work together

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [System Components](#system-components)
3. [Download Lifecycle](#download-lifecycle)
4. [Retry Mechanisms](#retry-mechanisms)
5. [State Verification System](#state-verification-system)
6. [Celery Functionality Usage](#celery-functionality-usage)
7. [Configuration Reference](#configuration-reference)
8. [Issues and Conflicts](#issues-and-conflicts)

---

## Architecture Overview

The download system uses **three independent mechanisms** working together:

```
┌─────────────────────────────────────────────────────────────┐
│  1. Celery Task Queue (Built-in Retry)                      │
│     - Immediate retries with exponential backoff            │
│     - Max 5 retries (6 total attempts)                      │
│     - Delays: 60s, 120s, 240s, 480s, 960s                  │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  2. Auto-Retry System (Custom Re-queuing)                   │
│     - Periodic re-queue of FAILED downloads                 │
│     - Max 3 retry cycles                                    │
│     - Delays: 30s, 90s, 270s (3x exponential)              │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  3. Fallback Verification (State Consistency Check)         │
│     - Verifies tasks exist in Celery queue                  │
│     - Verifies worker processes are running                 │
│     - Re-creates missing tasks                              │
│     - Runs every 30 seconds                                 │
└─────────────────────────────────────────────────────────────┘
```

**Total Retry Attempts:** 6 (Celery) × 3 (Auto-retry) = **18 download attempts** per file

---

## System Components

### Database Models

#### ProjectFile States
```python
class DownloadStatus(models.TextChoices):
    PENDING = "pending"        # Created, no task queued yet
    QUEUED = "queued"          # Task queued in Celery
    DOWNLOADING = "downloading" # Task executing, worker running
    COMPLETED = "completed"     # Download successful
    FAILED = "failed"          # All retries exhausted
```

#### DownloadAttempt States
```python
class Status(models.TextChoices):
    PENDING = "pending"        # Attempt created, not started
    DOWNLOADING = "downloading" # Attempt in progress
    COMPLETED = "completed"     # Attempt successful
    FAILED = "failed"          # Attempt failed
```

**Relationship:**
- Each `ProjectFile` has multiple `DownloadAttempt` records (one per retry)
- Each `ProjectFile` has ONE `download_task_id` (current Celery task)
- Only ONE `ProjectFile` can be `is_active=True` per project

### Celery Components

#### Task Definition
```python
# tasks.py:1373
@shared_task(bind=True, max_retries=5, default_retry_delay=60)
def download_project_file(self, project_id):
```

**Celery Features Used:**
- `bind=True` - Access to task instance (`self`)
- `max_retries=5` - Celery's built-in retry limit
- `default_retry_delay=60` - Base retry delay (overridden by exponential backoff)
- `self.retry(exc=exc, countdown=delay)` - Trigger Celery retry
- `self.request.retries` - Current retry count
- `self.update_state()` - Update task progress

#### Periodic Tasks (Celery Beat)
```python
# settings/base.py:443
CELERY_BEAT_SCHEDULE = {
    "retry-failed-downloads": {
        "task": "wafer_space.projects.tasks.retry_failed_downloads",
        "schedule": 300.0,  # Every 5 minutes (production)
    },
    "check-download-states": {
        "task": "wafer_space.projects.tasks.check_download_states",
        "schedule": 60.0,   # Every 1 minute (production)
    },
}
```

**Development overrides:** 30 seconds for both tasks

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
    download_status=ProjectFile.DownloadStatus.PENDING,  # ← PENDING state
)

# Step 2: Queue Celery task
task = download_project_file.delay(str(project.id))

# Step 3: Store task ID and update state
project_file.download_task_id = task.id
project_file.download_status = ProjectFile.DownloadStatus.QUEUED  # ← QUEUED state
project_file.save()
```

**State Transitions:**
```
PENDING → QUEUED
```

**What happens:**
1. ProjectFile created with `is_active=True`
2. Celery task queued (task sits in PostgreSQL queue)
3. Task ID stored for tracking

---

### Phase 2: Task Execution

**Code:** `wafer_space/projects/tasks.py::download_project_file()`

```python
# Step 1: Mark as DOWNLOADING (tasks.py:886)
project_file.download_status = ProjectFile.DownloadStatus.DOWNLOADING
project_file.worker_pid = os.getpid()
project_file.worker_hostname = socket.gethostname()
project_file.save()

# Step 2: Create DownloadAttempt record (tasks.py:1428)
attempt = DownloadAttempt.objects.create(
    project_file=project_file,
    attempt_number=project_file.download_attempts.count() + 1,
    status=DownloadAttempt.Status.DOWNLOADING,
)

# Step 3: Download file with progress tracking
_download_with_progress(self, project_file, attempt, temp_path)

# Step 4: Process content (extract, validate, hash)
_process_and_save_content(project_file, attempt, content, temp_path)

# Step 5: Mark as COMPLETED
attempt.status = DownloadAttempt.Status.COMPLETED
project_file.download_status = ProjectFile.DownloadStatus.COMPLETED
```

**State Transitions:**
```
QUEUED → DOWNLOADING → COMPLETED
```

**What happens:**
1. Worker picks up task from queue
2. ProjectFile updated with worker info (PID, hostname)
3. DownloadAttempt created to track this specific attempt
4. File downloaded in chunks with progress updates
5. Content pipeline extracts/validates/hashes file
6. Both attempt and file marked COMPLETED

---

### Phase 3: Failure Handling

**Code:** `wafer_space/projects/tasks.py::download_project_file()` exception handler

```python
# tasks.py:1580-1605
except (OSError, ValueError, requests.RequestException) as exc:
    if self.request.retries < self.max_retries:
        # CELERY RETRY: Attempt N of 6
        retry_delay = 60 * (2 ** self.request.retries)  # Exponential backoff

        # Mark current attempt as failed
        attempt.status = DownloadAttempt.Status.FAILED
        attempt.save()

        # Update ProjectFile with retry info
        project_file.download_error = f"Retry {self.request.retries + 1}/{self.max_retries}: {exc}"
        project_file.save()

        # Trigger Celery retry (SAME task, same task_id)
        raise self.retry(exc=exc, countdown=retry_delay)
    else:
        # MAX CELERY RETRIES REACHED: Mark as FAILED
        _handle_download_failure(project_id, exc, temp_path, attempt)
```

**State Transitions (within Celery retry cycle):**
```
DOWNLOADING → (Celery retry delay) → DOWNLOADING (same task_id)
```

**After all Celery retries exhausted:**
```
DOWNLOADING → FAILED
```

**What happens during Celery retries:**
1. Exception caught (network error, timeout, validation failure)
2. Current DownloadAttempt marked FAILED
3. ProjectFile.download_error updated with retry info
4. Task sleeps for exponential backoff delay (60s, 120s, 240s, 480s, 960s)
5. **Same task retries** (keeps same `download_task_id`)
6. New DownloadAttempt created for retry
7. Repeat until max_retries=5 reached

**After final Celery retry fails:**
1. ProjectFile marked FAILED
2. Error notification sent to user
3. Auto-retry system (Phase 4) takes over

---

## Retry Mechanisms

### Mechanism 1: Celery Built-in Retries

**Type:** Task-level retry (Celery native functionality)
**Trigger:** Exception raised during task execution
**Configuration:** `@shared_task(bind=True, max_retries=5, default_retry_delay=60)`

**Retry Schedule (Exponential Backoff):**
```
Attempt 1: Initial (immediate)
Attempt 2: +60s   (1 minute)
Attempt 3: +120s  (2 minutes)
Attempt 4: +240s  (4 minutes)
Attempt 5: +480s  (8 minutes)
Attempt 6: +960s  (16 minutes)
────────────────────────────
Total: 6 attempts over ~31 minutes
```

**Code:** `tasks.py:1582-1600`
```python
if self.request.retries < self.max_retries:
    retry_delay = 60 * (2 ** self.request.retries)
    raise self.retry(exc=exc, countdown=retry_delay)
```

**Celery Behavior:**
- **Same task retries** - `download_task_id` does NOT change
- Task stays in "active" list during countdown
- Celery task state: `PENDING` → `STARTED` → `RETRY` → `STARTED` → `RETRY`...
- Final state: `SUCCESS` or `FAILURE`

**Key Point:** This is **CELERY FUNCTIONALITY** - we're using Celery's built-in retry mechanism, not reimplementing it.

---

### Mechanism 2: Auto-Retry System (Custom Re-queuing)

**Type:** Job-level retry (Custom implementation)
**Trigger:** Periodic task finds FAILED downloads
**Schedule:** Every 5 minutes (production), every 30 seconds (dev)

**Code:** `tasks.py:1608-1684`
```python
@shared_task
def retry_failed_downloads():
    # Find failed downloads eligible for retry
    failed_files = ProjectFile.objects.filter(
        download_status=ProjectFile.DownloadStatus.FAILED,
        is_active=True,
        auto_retry_enabled=True,
        retry_count__lt=models.F("max_retries"),  # retry_count < 3
    )

    for project_file in failed_files:
        # Increment retry counter
        project_file.retry_count += 1
        project_file.download_status = ProjectFile.DownloadStatus.PENDING

        # Queue BRAND NEW task
        task = download_project_file.delay(str(project_file.project.id))
        project_file.download_task_id = task.id  # NEW task ID!

        project_file.save()
```

**Retry Schedule (Exponential Backoff):**
```python
# models.py:429
delay_minutes = base_delay * (backoff_multiplier ** retry_count)

# Production (base_delay=5 minutes, backoff=3x):
Cycle 1: +5 minutes   (after 6 Celery attempts fail)
Cycle 2: +15 minutes  (after 6 more Celery attempts fail)
Cycle 3: +45 minutes  (after 6 more Celery attempts fail)
────────────────────────────────────────────────────────
Total: 3 cycles × 6 attempts = 18 attempts over ~96 minutes

# Development (base_delay=30 seconds, backoff=3x):
Cycle 1: +30 seconds
Cycle 2: +90 seconds
Cycle 3: +270 seconds (4.5 minutes)
────────────────────────────────────────────────────────
Total: 18 attempts over ~7 minutes
```

**Key Differences from Celery Retry:**
- **Creates NEW task** - `download_task_id` CHANGES
- **Resets state** - FAILED → PENDING → QUEUED → DOWNLOADING
- **Creates NEW DownloadAttempt** - Fresh attempt_number sequence
- **Longer delays** - Minutes instead of seconds between cycles

**Key Point:** This is **DUPLICATE FUNCTIONALITY** - we're reimplementing Celery's retry mechanism at a higher level. This causes the 18-attempt problem.

---

### Mechanism 3: Fallback Verification System

**Type:** State consistency check (Custom implementation)
**Trigger:** Periodic task runs every 30 seconds (dev) / 60 seconds (prod)
**Purpose:** Handle ephemeral queue loss and detect orphaned tasks

**Code:** `tasks.py:1687-1764`
```python
@shared_task
def check_download_states():
    # SCENARIO 1: PENDING files without tasks
    pending_files = ProjectFile.objects.filter(
        download_status=ProjectFile.DownloadStatus.PENDING,
        is_active=True,
    )
    for project_file in pending_files:
        if not project_file.download_task_id:
            # Create missing task
            task = download_project_file.delay(project_file.project.id)
            project_file.download_task_id = task.id
            project_file.download_status = ProjectFile.DownloadStatus.QUEUED
            project_file.save()

    # SCENARIO 2: QUEUED files - verify task in Celery queue
    queued_files = ProjectFile.objects.filter(
        download_status=ProjectFile.DownloadStatus.QUEUED,
        is_active=True,
    )
    for project_file in queued_files:
        if not is_task_queued(project_file):
            # Task missing from queue - mark as orphaned
            project_file.mark_download_failed("Task not found in Celery queue")

    # SCENARIO 3: DOWNLOADING files - verify worker process exists
    downloading_files = ProjectFile.objects.filter(
        download_status=ProjectFile.DownloadStatus.DOWNLOADING,
        is_active=True,
    )
    for project_file in downloading_files:
        if not is_task_actively_running(project_file):
            # Worker crashed or task disappeared
            project_file.mark_download_failed("Task not running (worker crashed)")
```

**Verification Functions:**

#### `is_task_queued()` - Code: `verification.py:15-44`
```python
def is_task_queued(project_file: ProjectFile) -> bool:
    """Verify task is in Celery queue (reserved but not started)."""
    inspect = current_app.control.inspect()

    # Check Celery's reserved queue
    reserved = inspect.reserved()
    if task_id in reserved tasks:
        return True

    # Check Celery's active queue (auto-transition to DOWNLOADING)
    active = inspect.active()
    if task_id in active tasks:
        project_file.download_status = ProjectFile.DownloadStatus.DOWNLOADING
        project_file.save()
        return True

    return False
```

**Celery API Used:**
- `current_app.control.inspect().reserved()` - Tasks queued but not started
- `current_app.control.inspect().active()` - Tasks currently executing

#### `is_task_actively_running()` - Code: `verification.py:47-88`
```python
def is_task_actively_running(project_file: ProjectFile) -> bool:
    """Verify task is executing AND process exists."""
    inspect = current_app.control.inspect()

    # Step 1: Check task in Celery active list
    active = inspect.active()
    if task_id not in active tasks:
        return False

    # Step 2: Verify worker process exists (using psutil)
    if project_file.worker_pid and project_file.worker_hostname:
        if socket.gethostname() == project_file.worker_hostname:
            if not psutil.pid_exists(project_file.worker_pid):
                return False

            proc = psutil.Process(project_file.worker_pid)
            if "celery" not in proc.cmdline():
                return False

    return True
```

**Multi-layer Verification:**
1. **Celery layer:** Task in `inspect.active()` list?
2. **OS layer:** Process ID exists on worker hostname?
3. **Process layer:** Process is actually Celery worker?

**Why This is Needed:**

Celery queues are **ephemeral** (stored in PostgreSQL database, but not durable):
- Queue can be lost if Celery worker crashes
- Queue can be lost if PostgreSQL restarts
- Queue can be lost if Celery purged manually
- Tasks can get "stuck" in active list after worker crash

This system provides **defense in depth** against queue loss.

**Key Point:** This is **CUSTOM FUNCTIONALITY** - Celery does not provide automatic queue recovery or process verification. We built this to handle ephemeral queue limitations.

---

## Celery Functionality Usage

### What We USE from Celery

| Feature | Usage | Code Location |
|---------|-------|---------------|
| **Task Queue** | Store pending download tasks | PostgreSQL via SQLAlchemy |
| **Task Execution** | Run download_project_file() | Worker pool |
| **Built-in Retry** | Retry on exception with exponential backoff | `@shared_task(max_retries=5)` |
| **Task State** | Track PENDING/STARTED/RETRY/SUCCESS/FAILURE | `self.update_state()` |
| **Progress Updates** | Update download progress during execution | `self.update_state(state='PROGRESS', meta={...})` |
| **Task Inspection** | Check if tasks queued/active | `inspect.reserved()`, `inspect.active()` |
| **Periodic Tasks** | Run retry_failed_downloads() every 5 min | Celery Beat |
| **Result Backend** | Store task results (disabled in eager mode) | django-db |

### What We DUPLICATE from Celery

| Functionality | Celery Provides | We Reimplemented | Why Duplicated |
|---------------|-----------------|------------------|----------------|
| **Retry Logic** | `max_retries=5` with exponential backoff | `retry_failed_downloads()` with `max_retries=3` | **Historical:** Wanted longer delays between retry cycles |
| **Retry Delays** | `self.retry(countdown=delay)` | `calculate_next_retry_time()` with exponential backoff | **Duplication:** Both implement exponential backoff |
| **Retry Counting** | `self.request.retries` | `ProjectFile.retry_count` | **Tracking:** Want to show user retry attempts |

**Analysis:**
The auto-retry system is **redundant** with Celery's built-in retry mechanism. It adds:
- **Complexity:** Two retry systems to maintain
- **Excessive retries:** 18 total attempts (6 × 3)
- **Inconsistent state:** Celery task state vs ProjectFile state

**Alternative:** Could use only Celery retries with `max_retries=17` (18 attempts), but would lose ability to show retry history to users.

### What We BUILT (Not in Celery)

| Feature | Purpose | Code Location |
|---------|---------|---------------|
| **Queue Verification** | Detect missing tasks, re-create if lost | `check_download_states()` |
| **Process Verification** | Verify worker PID exists, detect crashes | `is_task_actively_running()` |
| **State Auto-Transition** | QUEUED → DOWNLOADING when task starts | `is_task_queued()` line 40 |
| **Download Attempts** | Track each retry as separate DownloadAttempt | `DownloadAttempt` model |
| **Progress Tracking** | Store chunks every 5MB for performance analysis | `ProjectFileChunk` model |
| **Orphan Detection** | Find stuck/lost tasks, mark as failed | `check_download_states()` |

**These are legitimate custom features** that Celery doesn't provide.

---

## Configuration Reference

### Production Settings (`config/settings/base.py`)

```python
# Celery Task Retry Configuration
@shared_task(bind=True, max_retries=5, default_retry_delay=60)
# - 6 total attempts (1 initial + 5 retries)
# - Exponential backoff: 60s, 120s, 240s, 480s, 960s

# Auto-Retry System
DOWNLOAD_RETRY_BASE_DELAY_MINUTES = 5
DOWNLOAD_RETRY_BACKOFF_MULTIPLIER = 3
# Cycle delays: 5min, 15min, 45min

# Periodic Tasks
DOWNLOAD_RETRY_CHECK_INTERVAL_SECONDS = 300.0  # Every 5 minutes
DOWNLOAD_STATE_CHECK_INTERVAL_SECONDS = 60.0   # Every 1 minute

# Model Defaults
ProjectFile.max_retries = 3  # Maximum auto-retry cycles
ProjectFile.auto_retry_enabled = True  # Enable automatic re-queuing
```

### Development Settings (`config/settings/dev.py`)

```python
# Faster retries for development
DOWNLOAD_RETRY_BASE_DELAY_MINUTES = 30 / 60  # 30 seconds
DOWNLOAD_RETRY_CHECK_INTERVAL_SECONDS = 30.0
DOWNLOAD_STATE_CHECK_INTERVAL_SECONDS = 30.0

# Uses SQLite for Celery broker (not PostgreSQL)
CELERY_BROKER_URL = f"sqla+sqlite:///{BASE_DIR / 'db.sqlite3'}"
```

---

## Issues and Conflicts

### Issue 1: Excessive Retries (18 Attempts)

**Problem:** Two retry systems multiply instead of complement each other.

**Current Behavior:**
```
Cycle 1: 6 Celery attempts (over 31 minutes)
         ↓ all fail
         FAILED → retry_failed_downloads() → re-queue

Cycle 2: 6 Celery attempts (over 31 minutes)
         ↓ all fail
         FAILED → retry_failed_downloads() → re-queue

Cycle 3: 6 Celery attempts (over 31 minutes)
         ↓ all fail
         FAILED → permanent failure

Total: 18 attempts over ~93 minutes
```

**Expected Behavior:**
Users expect failures to retry "a few times", not 18 times.

**Recommendation:**
- **Option A:** Remove auto-retry system, use only Celery retries with `max_retries=5` (6 attempts)
- **Option B:** Reduce Celery retries to `max_retries=1` (2 attempts per cycle × 3 cycles = 6 total)
- **Option C:** Disable auto_retry_enabled by default, make it opt-in per file

---

### Issue 2: UI State Confusion (Stuck in "Retrying")

**Problem:** Three different states show conflicting information during Celery retry.

**State During Celery Retry:**
| Component | State | Display |
|-----------|-------|---------|
| `DownloadAttempt.status` | `FAILED` | "Failed" badge |
| `ProjectFile.is_active` | `True` | Shows in "File In Progress" |
| `Celery task.state` | `RETRY` | "Retrying" status from API |

**JavaScript Polling Behavior:**
```javascript
// project_detail.html:409
if (data.status === 'completed' || data.status === 'failed') {
    clearInterval(pollInterval);
    setTimeout(() => location.reload(), 1000);
}
```

**Result:**
- Polling sees `status='retrying'` from Celery API
- Shows "Retrying" badge (orange warning color)
- Does **NOT** reload page (only reloads for completed/failed)
- File stuck in "File In Progress" section
- User confused: "Is it retrying or failed?"

**Recommendation:**
Add "retrying" to reload condition:
```javascript
if (data.status === 'completed' || data.status === 'failed' || data.status === 'retrying') {
    clearInterval(pollInterval);
    setTimeout(() => location.reload(), 2000);  // Longer delay for retry
}
```

---

### Issue 3: Download Attempt History Not Visible

**Problem:** UI shows ProjectFiles, not DownloadAttempts.

**Data Created:**
- Each retry creates new `DownloadAttempt` record (attempt_number increments)
- Same `ProjectFile` (is_active=True) for all attempts
- After 18 retries: 1 ProjectFile with 18 DownloadAttempt records

**Data Displayed:**
```django
{# File History #}
{% for file in history_files %}
    <tr>
        <td>{{ file.original_filename }}</td>
        <td>{{ file.latest_attempt.get_status_display }}</td>
    </tr>
{% endfor %}
```

**Result:**
- User sees: 1 file with "Failed" status
- User expects: See all 18 retry attempts with timestamps

**Recommendation:**
Add DownloadAttempt history section in `_file_display.html`:
```django
{% if show_details and file.download_attempts.exists %}
    <details>
        <summary>Download Attempt History ({{ file.download_attempts.count }})</summary>
        <table>
            {% for attempt in file.download_attempts.all %}
                <tr>
                    <td>Attempt #{{ attempt.attempt_number }}</td>
                    <td>{{ attempt.get_status_display }}</td>
                    <td>{{ attempt.download_started_at|date:"Y-m-d H:i:s" }}</td>
                </tr>
            {% endfor %}
        </table>
    </details>
{% endif %}
```

---

### Issue 4: Retry System Duplication

**Problem:** Auto-retry system reimplements Celery functionality.

**What Auto-Retry Does:**
1. Finds FAILED downloads
2. Re-queues them after exponential delay
3. Tracks retry count
4. Gives up after max retries

**What Celery Already Does:**
1. Retries failed tasks
2. Implements exponential backoff
3. Tracks retry count (`self.request.retries`)
4. Gives up after max retries

**Why Duplication Exists:**
- **Historical:** Wanted longer delays between retry cycles (minutes vs seconds)
- **User visibility:** Want to show retry history to users
- **Configurability:** Per-file retry settings (`auto_retry_enabled`, `max_retries`)

**Recommendation:**
- **Keep:** Fallback verification system (handles queue loss, unique functionality)
- **Remove:** Auto-retry system (duplicate of Celery retries)
- **Use:** Only Celery retries with appropriate `max_retries` value
- **Add:** User-facing retry history from DownloadAttempt records

---

## Summary

**Celery Functionality We Use:**
- ✅ Task queue (PostgreSQL broker)
- ✅ Task execution (worker pool)
- ✅ Built-in retry with exponential backoff
- ✅ Task state tracking and progress updates
- ✅ Task inspection API
- ✅ Periodic tasks (Beat scheduler)

**Celery Functionality We Duplicate:**
- ❌ Retry logic (auto-retry system reimplements Celery retries)
- ❌ Exponential backoff (implemented twice)
- ❌ Retry counting (both Celery and ProjectFile track counts)

**Custom Functionality We Built:**
- ✅ Queue verification (detect missing tasks)
- ✅ Process verification (detect crashed workers)
- ✅ State auto-transition (QUEUED → DOWNLOADING)
- ✅ Download attempt tracking (DownloadAttempt model)
- ✅ Progress checkpoints (ProjectFileChunk model)
- ✅ Orphan detection (stuck task cleanup)

**Recommended Changes:**
1. **Remove auto-retry system** - Use only Celery retries
2. **Fix UI polling** - Reload on "retrying" status
3. **Show attempt history** - Display all DownloadAttempt records
4. **Keep fallback verification** - Handles ephemeral queue, unique value
