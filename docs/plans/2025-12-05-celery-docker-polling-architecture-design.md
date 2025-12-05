# Celery Docker Polling Architecture Design

## Overview

Rework the ManufacturingCheck Celery queue and Docker container management to use a stateless polling architecture instead of long-running synchronous tasks.

### Goals

1. **Celery restart resilience** - Restarting Celery workers doesn't affect running Docker checks; containers continue running and new tasks resume monitoring
2. **Fast tasks only** - All tasks are short-running (<60s) and stateless
3. **Multi-server support** - Support multiple Docker servers with priority-based selection
4. **Decoupled analysis** - Log analysis happens separately after container completion
5. **Incremental log download** - Logs fetched incrementally during container execution

### Current Problems

The existing `check_process_job` task is a long-running synchronous task (up to 12 hours) that:
- Starts the Docker container
- Waits synchronously while streaming logs
- If Celery restarts, the task is lost but the container keeps running
- Recovery relies on psutil checking worker PIDs

## State Machine

### New Status Flow

```
PENDING → DISPATCHING → STARTING → RUNNING → ANALYZING → FINISHED
    ↓          ↓            ↓          ↓          ↓
  ERROR      ERROR        ERROR      ERROR      ERROR
    ↓          ↓            ↓          ↓          ↓
 PENDING    PENDING      PENDING    PENDING    PENDING (retry)
```

### Status Definitions

| Status | Meaning |
|--------|---------|
| `PENDING` | Waiting to be dispatched to a Docker server |
| `DISPATCHING` | Server assigned, image being pulled |
| `STARTING` | Image ready, container being started |
| `RUNNING` | Container confirmed running on Docker server |
| `ANALYZING` | Container exited, logs being analyzed for results |
| `FINISHED` | Analysis complete, results stored |
| `ERROR` | Failed (retryable based on retry count) |
| `CANCELLING` | Cancellation requested |
| `CANCELLED` | Cancellation complete |

### Status Classification

```python
class Status(models.TextChoices):
    PENDING = "PENDING", "Pending"
    DISPATCHING = "DISPATCHING", "Dispatching"
    STARTING = "STARTING", "Starting"
    RUNNING = "RUNNING", "Running"
    ANALYZING = "ANALYZING", "Analyzing"
    FINISHED = "FINISHED", "Finished"
    ERROR = "ERROR", "Error"
    CANCELLING = "CANCELLING", "Cancelling"
    CANCELLED = "CANCELLED", "Cancelled"

    @classmethod
    def active(cls) -> list[str]:
        """Statuses that count toward server concurrent limit."""
        return [cls.DISPATCHING, cls.STARTING, cls.RUNNING, cls.CANCELLING]

    @classmethod
    def working(cls) -> list[str]:
        """Statuses where check is actively being processed."""
        return [cls.DISPATCHING, cls.STARTING, cls.RUNNING, cls.ANALYZING, cls.CANCELLING]

    @classmethod
    def terminal(cls) -> list[str]:
        """Statuses that represent completion (success or failure)."""
        return [cls.FINISHED, cls.CANCELLED]
```

### State Transitions with Atomic Data Updates

| Transition | Caller Provides | Method Sets Automatically |
|------------|-----------------|---------------------------|
| PENDING → DISPATCHING | `docker_server_id` | `dispatching_started_at` |
| DISPATCHING → STARTING | `docker_image`, `docker_image_digest` | `starting_started_at` |
| STARTING → RUNNING | `docker_container_id`, `docker_command` | `container_started_at` |
| RUNNING → ANALYZING | `docker_exit_code` | `container_finished_at` |
| ANALYZING → FINISHED | `is_manufacturable`, `errors`, `warnings`, `tool_versions` | `analysis_completed_at` |

## Task Architecture

### Design Principle: Beat Tasks Never Touch External Services

| Task Type | Touches Database | Touches Docker API |
|-----------|------------------|-------------------|
| Beat tasks (orchestrators) | Yes | Never |
| Work tasks (queued) | Yes | Yes |

Beat tasks run on a schedule and must be fast/reliable. All Docker API interactions are in queued work tasks.

### Design Principle: Each Beat Task Does One Thing

- Status transition beats: just transition (no queuing)
- Work-queuing beats: just queue (no transitions)
- Cleanup beats: just mark ERROR or CANCELLING

### Beat Tasks (Orchestrators)

| Beat Task | Interval | Finds | Action |
|-----------|----------|-------|--------|
| `checks_pending` | 15s | PENDING | Marks DISPATCHING (assigns server) |
| `checks_dispatching` | 15s | DISPATCHING | Queues `do_dispatching` |
| `checks_starting` | 15s | STARTING | Queues `do_starting` |
| `checks_running` | 15s | RUNNING | Queues `do_running` |
| `checks_analyzing` | 15s | ANALYZING | Queues `do_analyzing` |
| `checks_cancelling` | 15s | CANCELLING | Queues `do_cancelling` |
| `checks_retry` | 60s | ERROR (can_retry) | Sets status → PENDING |
| `checks_cleanup_orphaned_dispatching` | 60s | Stale DISPATCHING | Sets status → ERROR |
| `checks_cleanup_orphaned_starting` | 60s | Stale STARTING | Sets status → ERROR |
| `checks_cleanup_orphaned_running` | 60s | RUNNING, container gone | Sets status → ERROR |
| `checks_cleanup_orphaned_docker` | 60s | Untracked containers | Queues `do_cleanup_orphaned_docker` |
| `checks_cleanup_stale_files` | 60s | Active checks on inactive files | Sets status → CANCELLING |

### Work Tasks (docker-ephemeral queue)

| Work Task | What It Does | Transition |
|-----------|--------------|------------|
| `do_dispatching` | Pull Docker image, verify digest | DISPATCHING → STARTING |
| `do_starting` | Create container, start, wait for confirmed running | STARTING → RUNNING |
| `do_running` | Poll container status, download logs incrementally | RUNNING → ANALYZING (if exited) |
| `do_analyzing` | Parse logs, extract results, save archives | ANALYZING → FINISHED/ERROR |
| `do_cancelling` | Stop and remove container | CANCELLING → CANCELLED |
| `do_cleanup_orphaned_docker` | Remove orphaned container | (no transition) |

### Naming Pattern

| Type | Pattern | Example |
|------|---------|---------|
| Beat task | `checks_{status}` or `checks_{action}` | `checks_running`, `checks_retry` |
| Work task | `do_{status}` or `do_{action}` | `do_running`, `do_cleanup_orphaned_docker` |

## Task Deduplication

### ManufacturingCheckTask Model

A separate table tracks pending/running Celery tasks to prevent duplicate queuing:

```python
class ManufacturingCheckTask(models.Model):
    """Tracks pending/running Celery tasks for manufacturing checks.

    Ephemeral - rows are deleted when tasks complete.
    """
    check = models.OneToOneField(
        ManufacturingCheck,
        on_delete=models.CASCADE,
        related_name="pending_task",
    )
    task_id = models.CharField(max_length=255)
    task_name = models.CharField(max_length=255)
    queued_at = models.DateTimeField(auto_now_add=True)
```

The `OneToOneField` enforces only one pending task per check at the database level.

### Beat Task Pattern

```python
def checks_running():
    # Only checks without a pending task
    running_checks = ManufacturingCheck.objects.filter(
        status=ManufacturingCheck.Status.RUNNING,
    ).exclude(
        pending_task__isnull=False
    )

    for check in running_checks:
        result = do_running.delay(check.id)
        ManufacturingCheckTask.objects.create(
            check=check,
            task_id=result.id,
            task_name="do_running",
        )
```

### Work Task Pattern with Context Manager

```python
@contextmanager
def track_task(check_id: int):
    """Delete task tracking row when work completes."""
    try:
        yield
    finally:
        ManufacturingCheckTask.objects.filter(check_id=check_id).delete()


@shared_task
def do_running(check_id: int) -> None:
    with track_task(check_id):
        check = ManufacturingCheck.objects.get(id=check_id)

        if check.status != ManufacturingCheck.Status.RUNNING:
            return  # State changed, nothing to do

        # ... do work
```

### External State Checks (Defense in Depth)

Each task also checks external state before doing work:

| Task | External State Check |
|------|---------------------|
| `do_dispatching` | Check if image with expected digest already present on server |
| `do_starting` | Check if container with `wafer.space.check_id={id}` label already exists |
| `do_running` | Idempotent - safe to run multiple times |
| `do_analyzing` | Check if `analysis_completed_at` already set |
| `do_cancelling` | Check if container exists, if not just mark cancelled |

### Future Enhancement: Stale Task Cleanup

A cleanup task to clear `ManufacturingCheckTask` rows for tasks that no longer exist in Celery will be added in a future iteration.

## Multi-Server Support

### Server Configuration (Django Settings)

```python
DOCKER_SERVERS = [
    {
        "id": "local",
        "url": "unix:///var/run/docker.sock",
        "max_concurrent": 4,
        "priority": 1,  # highest priority (used first)
    },
    {
        "id": "remote-1",
        "url": "tcp://192.168.1.10:2375",
        "max_concurrent": 2,
        "priority": 2,
    },
]
```

### Server Selection Logic

In `checks_pending` beat task:

1. Sort servers by priority (ascending)
2. For each server:
   - Count checks in `Status.active()` statuses assigned to this server
   - If count < max_concurrent, server has capacity
3. Assign PENDING check to first server with capacity
4. Transition check: PENDING → DISPATCHING with `docker_server_id`

### Server Capacity Check

```python
def checks_pending():
    for server in DOCKER_SERVERS:
        active_count = ManufacturingCheck.objects.filter(
            docker_server_id=server["id"],
            status__in=ManufacturingCheck.Status.active(),
        ).count()

        available_slots = server["max_concurrent"] - active_count

        if available_slots > 0:
            pending_checks = ManufacturingCheck.objects.filter(
                status=ManufacturingCheck.Status.PENDING
            )[:available_slots]

            for check in pending_checks:
                check.mark_dispatching(server["id"])
```

### Concurrent Limits Are Per-Server

If server A has `max_concurrent=4` and server B has `max_concurrent=2`, the system can run 6 checks total (4 on A, 2 on B).

## Incremental Log Download

### Timestamp-Based Fetching

Logs are fetched using Docker's `since` parameter with parsed timestamps to avoid gaps or duplicates.

### Model Field

```python
logs_downloaded_until = models.FloatField(null=True, blank=True)  # Unix timestamp with nanoseconds
```

### Timestamp Parsing

Docker returns RFC3339Nano timestamps. We parse to float to preserve nanosecond precision:

```python
import re
from datetime import datetime, timezone

DOCKER_TIMESTAMP_PATTERN = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})\.(\d+)Z")

def parse_docker_timestamp_float(line: str) -> float | None:
    """Extract timestamp from Docker log line as Unix float with nanoseconds."""
    match = DOCKER_TIMESTAMP_PATTERN.match(line)
    if not match:
        return None

    year, month, day, hour, minute, second, nanos = match.groups()

    dt = datetime(
        int(year), int(month), int(day),
        int(hour), int(minute), int(second),
        tzinfo=timezone.utc,
    )

    unix_seconds = dt.timestamp()
    nano_fraction = int(nanos) / (10 ** len(nanos))

    return unix_seconds + nano_fraction
```

### In do_running Task

```python
since = check.logs_downloaded_until or check.container_started_at.timestamp()
raw_logs = container.logs(
    stdout=True,
    stderr=True,
    since=since,
    timestamps=True,
)

if raw_logs:
    logs_str = raw_logs.decode("utf-8", errors="replace")
    lines = logs_str.strip().split("\n")

    # Parse timestamp from last line for next fetch
    last_timestamp = parse_docker_timestamp_float(lines[-1])

    # Strip timestamps for clean storage
    clean_logs = strip_docker_timestamps(logs_str)

    check.append_logs(clean_logs, last_timestamp)
```

## Model Changes Summary

### New Model: ManufacturingCheckTask

```python
class ManufacturingCheckTask(models.Model):
    check = models.OneToOneField(ManufacturingCheck, on_delete=models.CASCADE)
    task_id = models.CharField(max_length=255)
    task_name = models.CharField(max_length=255)
    queued_at = models.DateTimeField(auto_now_add=True)
```

### ManufacturingCheck: Add Fields

| Field | Type | Purpose |
|-------|------|---------|
| `docker_server_id` | CharField | Which server runs this check |
| `docker_exit_code` | IntegerField | Container exit code |
| `dispatching_started_at` | DateTimeField | When DISPATCHING started |
| `starting_started_at` | DateTimeField | When STARTING started |
| `container_started_at` | DateTimeField | When container confirmed running |
| `container_finished_at` | DateTimeField | When container exited |
| `analysis_completed_at` | DateTimeField | When analysis finished |
| `logs_downloaded_until` | FloatField | Unix timestamp for incremental log fetch |

### ManufacturingCheck: Add Status Values

- `DISPATCHING`
- `STARTING`
- `ANALYZING`

### ManufacturingCheck: Add Status Classification Methods

- `Status.active()` - statuses counting toward server concurrent limit
- `Status.working()` - statuses where check is actively being processed
- `Status.terminal()` - statuses representing completion

### ManufacturingCheck: Remove Fields

| Field | Reason |
|-------|--------|
| `celery_job_id` | Replaced by ManufacturingCheckTask |
| `celery_job_started_at` | Replaced by granular timestamps |
| `celery_job_finished_at` | Replaced by granular timestamps |
| `celery_worker_pid` | No longer tracking long-running jobs |
| `celery_worker_hostname` | No longer tracking long-running jobs |

## Tasks Changes Summary

### Remove

- `check_process_job` - the long-running synchronous task

### Add Beat Tasks

- `checks_pending` (15s)
- `checks_dispatching` (15s)
- `checks_starting` (15s)
- `checks_running` (15s)
- `checks_analyzing` (15s)
- `checks_cancelling` (15s)

### Add Work Tasks

- `do_dispatching`
- `do_starting`
- `do_running`
- `do_analyzing`
- `do_cancelling`
- `do_cleanup_orphaned_docker`

## Settings Changes

### Add

```python
DOCKER_SERVERS = [
    {
        "id": "local",
        "url": "unix:///var/run/docker.sock",
        "max_concurrent": 4,
        "priority": 1,
    },
]
```

### Remove/Deprecate

- `PRECHECK_CONCURRENT_LIMIT` - replaced by per-server `max_concurrent`
