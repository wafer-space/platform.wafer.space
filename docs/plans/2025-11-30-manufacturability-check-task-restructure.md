# Manufacturability Check Task Restructure

## Executive Summary

The current Celery tasks for manufacturability checks are poorly named and have mixed responsibilities. This document proposes restructuring them into single-responsibility tasks with a consistent naming scheme.

**Key decisions:**
1. Remove `ManufacturabilityService` - all state changes handled by model methods called from tasks
2. Add `CANCELLING` state to handle async cleanup before `CANCELLED`
3. Split monolithic task into single-responsibility tasks
4. Naming: `check_` (singular) for per-job tasks, `checks_` (plural) for periodic loops

---

## The Cancellation Problem

### Why This Matters

The concurrent limit controls how many Docker containers run simultaneously. If we set status to `CANCELLED` before Docker cleanup completes:

1. User cancels check → status = CANCELLED immediately
2. `checks_dispatch` counts active = DISPATCHED + RUNNING (excludes CANCELLED)
3. `checks_dispatch` sees slot available → dispatches new job
4. But cancelled check's Docker container is **still running**
5. Now we have more containers than the limit allows

### Solution: CANCELLING State

Add an intermediate state that means "cancellation requested, cleanup in progress":

```
PENDING ──┬── DISPATCHED ──┬── RUNNING ──┬── FINISHED
          │                │             │
          └────────────────┴─────────────┴──→ CANCELLING ──→ CANCELLED
```

**Flow:**
1. User cancels → `mark_cancelling(reason)` → status = CANCELLING
2. `checks_dispatch` counts DISPATCHED + RUNNING + **CANCELLING** → slot still occupied
3. `checks_cancelling` task runs:
   - Revokes Celery task
   - Stops Docker container
   - Calls `mark_cancelled()` → status = CANCELLED
4. Now `checks_dispatch` sees slot available

### Why Not a `should_cancel` Flag?

We considered adding `should_cancel = BooleanField()` instead:

| Approach | Pros | Cons |
|----------|------|------|
| **CANCELLING state** | Single source of truth, explicit state machine, simpler queries | Requires migration |
| **should_cancel flag** | No state change, preserves original status | Hidden parallel state machine, complex queries |

**Decision: Use CANCELLING state** - the state machine is the canonical way to track lifecycle.

---

## Current State

### Existing Tasks

| Task | Queue | Responsibilities |
|------|-------|------------------|
| `celery_job_run` | `manufacturability` | Runs Docker container for a single check |
| `process_manufacturability_check_queue` | `maintenance` | **Monolithic** - does 4 different things |
| `cleanup_orphaned_precheck_containers` | `maintenance` | Cleans up orphaned Docker containers |

### The Monolith: `process_manufacturability_check_queue`

This single task (`tasks.py:3097`) currently handles:

1. **DISPATCHED verification** (`_handle_dispatched_checks`):
   - Checks if DISPATCHED tasks are still in Celery queue
   - Transitions to RUNNING if task started
   - Moves back to PENDING if task lost

2. **RUNNING verification** (`_handle_running_checks`):
   - Verifies RUNNING tasks have active workers (PID exists)
   - Marks orphaned tasks as ERROR
   - Auto-retries if `can_retry()`

3. **ERROR retry** (`_handle_error_checks`):
   - Finds ERROR checks where `can_retry()` is True
   - Calls `reset_for_retry()` to move back to PENDING

4. **PENDING dispatch** (`_handle_pending_checks`):
   - Checks concurrent limit (DISPATCHED + RUNNING < limit)
   - Dispatches PENDING checks via `celery_job_run.delay()`
   - Calls `mark_dispatched()` on success

### Check Creation (Hidden in Download Task)

`_create_manufacturability_check()` (`tasks.py:2264`) is called from within `download_project_file` after hash verification. It:
- Cancels any existing checks for other files in the project
- Creates a new `ManufacturabilityCheck` in PENDING state

### Missing Functionality

Currently **nothing** handles:
- Revoking Celery tasks for CANCELLED checks (only done synchronously via `ManufacturabilityService.cancel_check`)
- Cleaning up Docker containers specifically for CANCELLED checks (handled generically by orphan cleanup)

---

## Proposed Structure

### Naming Convention

- **`check_`** (singular): Per-job task, takes `check_id` parameter
- **`checks_`** (plural): Periodic task that loops over multiple checks

### Updated State Machine

```python
class Status(models.TextChoices):
    PENDING = "pending", "Pending"          # Waiting for capacity
    DISPATCHED = "dispatched", "Dispatched"  # Job sent to Celery
    RUNNING = "running", "Running"          # Docker container executing
    FINISHED = "finished", "Finished"       # Analysis complete (terminal)
    ERROR = "error", "Error"                # System failure, can retry
    CANCELLING = "cancelling", "Cancelling"  # NEW: Cleanup in progress
    CANCELLED = "cancelled", "Cancelled"    # Cleanup complete (terminal)

ALLOWED_TRANSITIONS = {
    Status.PENDING: {Status.DISPATCHED, Status.ERROR, Status.CANCELLING},
    Status.DISPATCHED: {Status.RUNNING, Status.ERROR, Status.CANCELLING},
    Status.RUNNING: {Status.FINISHED, Status.ERROR, Status.CANCELLING},
    Status.FINISHED: set(),  # Terminal
    Status.ERROR: {Status.PENDING},  # Can retry
    Status.CANCELLING: {Status.CANCELLED},  # Only cleanup task can complete
    Status.CANCELLED: set(),  # Terminal
}
```

### New Task Breakdown

| Task Name | Queue | Type | Docker? | Single Responsibility |
|-----------|-------|------|:-------:|----------------------|
| `check_process_job` | `docker-persistent` | Per-job | Yes | Run Docker container for one check |
| `checks_dispatch` | `default` | Periodic | No | Dispatch PENDING checks (respecting limit) |
| `checks_retry` | `default` | Periodic | No | Move retryable ERROR checks to PENDING |
| `checks_create` | `default` | Periodic | No | Create checks for verified downloads |
| `checks_cancelling` | `docker-ephemeral` | Periodic | Yes | Complete CANCELLING → CANCELLED transition |
| `checks_cleanup_orphaned_dispatch` | `default` | Periodic | No | Mark lost DISPATCHED as ERROR |
| `checks_cleanup_orphaned_processing` | `default` | Periodic | No | Mark dead RUNNING as ERROR |
| `checks_cleanup_orphaned_docker` | `docker-ephemeral` | Periodic | Yes | Remove unlinked Docker containers |

**Queue assignment rationale:**
- `docker-persistent` — Runs long-lived Docker containers (precheck jobs taking minutes to hours)
- `docker-ephemeral` — Quick Docker operations (stop/remove containers, seconds)
- `default` — Database-only tasks, no Docker needed, runs on `www-data` user

Both `docker-*` queues run on the `celery-mfg` user with Docker socket access. They're separated so quick cleanup tasks don't get stuck behind long-running jobs.

**Important: Worker headroom for cancellation**

The `docker-persistent` queue should always have one worker free to handle new jobs quickly. If all workers are busy with long-running Docker jobs, a cancelled job's slot won't be filled until an existing job completes.

**Rule:** Set `PRECHECK_CONCURRENT_LIMIT = N - 1` where N is the number of `docker-persistent` workers.

Example with 4 workers:
- `PRECHECK_CONCURRENT_LIMIT = 3`
- At most 3 Docker jobs running simultaneously
- 1 worker always free to pick up new jobs immediately after cancellation completes

This ensures that when `checks_cancelling` completes and releases a slot, `checks_dispatch` can dispatch a new job that gets picked up immediately rather than waiting for an existing job to finish.

**Note:** Previous `checks_cleanup_cancel_jobs` and `checks_cleanup_cancel_docker` are merged into `checks_cancelling` since they must happen atomically before transitioning to CANCELLED.

### Detailed Specifications

#### 1. `check_process_job(check_id)` — Per-Job

**Current:** `celery_job_run`

**Change:** Rename only. Logic stays the same.

```python
@shared_task(bind=True, queue="docker-persistent", ...)
def check_process_job(self, check_id):
    """Run manufacturability check in Docker container for a single check."""
    # Existing implementation - runs Docker, calls model methods directly
```

---

#### 2. `checks_dispatch()` — Periodic

**Current:** Part of `_handle_pending_checks` in monolith

**Responsibility:**
- Count active checks (DISPATCHED + RUNNING + **CANCELLING**)
- If under limit, dispatch PENDING checks via `check_process_job.delay()`
- Call `check.mark_dispatched(celery_job_id=task.id)`

**Critical:** CANCELLING checks count toward the limit because their Docker containers may still be running.

```python
@shared_task(queue="default")
def checks_dispatch():
    """Dispatch PENDING checks to Celery queue (respecting concurrent limit)."""
    concurrent_limit = settings.PRECHECK_CONCURRENT_LIMIT

    # CANCELLING counts because Docker container may still be running
    active_count = ManufacturabilityCheck.objects.filter(
        status__in=[Status.DISPATCHED, Status.RUNNING, Status.CANCELLING]
    ).count()

    pending = ManufacturabilityCheck.objects.filter(
        status=Status.PENDING
    ).order_by("celery_job_dispatched_at")

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

---

#### 3. `checks_retry()` — Periodic

**Current:** Part of `_handle_error_checks` in monolith

**Responsibility:**
- Find ERROR checks where `can_retry()` is True
- Call `check.reset_for_retry(reason="...")` to move back to PENDING

```python
@shared_task(queue="default")
def checks_retry():
    """Move retryable ERROR checks back to PENDING state."""
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

---

#### 4. `checks_create()` — Periodic

**Current:** `_create_manufacturability_check()` called inline from `download_project_file`

**Change:** Extract to separate periodic task for resilience.

**Responsibility:**
- Find ProjectFiles with `is_active=True`, `hash_verified=True`, no ManufacturabilityCheck
- Create ManufacturabilityCheck in PENDING state

**Why separate task:**
- More resilient to failures (check creation can be retried)
- Cleaner separation of concerns
- Download task becomes simpler

```python
@shared_task(queue="default")
def checks_create():
    """Create ManufacturabilityChecks for verified downloads that need them."""
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
            status=Status.PENDING,
        )
        created += 1

    return {"created": created}
```

---

#### 5. `checks_cancelling()` — Periodic

**Current:** Partially in `ManufacturabilityService.cancel_check()` (synchronous), rest missing

**This is the KEY task for safe cancellation.**

**Responsibility:**
1. Find all checks in CANCELLING state
2. Revoke Celery task (if exists)
3. Stop and remove Docker container (if exists)
4. Call `check.mark_cancelled()` to complete transition

**Only this task can transition CANCELLING → CANCELLED**, ensuring cleanup is complete before the slot is released.

```python
@shared_task(queue="docker-ephemeral")
def checks_cancelling():
    """Complete cancellation for checks in CANCELLING state.

    This task performs all cleanup before transitioning to CANCELLED,
    ensuring Docker containers are stopped before releasing the slot.
    """
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

---

#### 6. `checks_cleanup_orphaned_docker()` — Periodic

**Current:** `cleanup_orphaned_precheck_containers`

**Change:** Rename. Start from Docker (source of truth), not database.

**Responsibility:**
- List all Docker containers with label `wafer.space.service=manufacturability-check`
- For each container, check if its associated ManufacturabilityCheck is in an active state
- Remove containers where check is missing, FINISHED, ERROR, or CANCELLED

**Why start from Docker:** Docker is the source of truth for what's actually consuming resources. A container might exist even if the database record is gone or corrupted.

```python
@shared_task(queue="docker-ephemeral")
def checks_cleanup_orphaned_docker():
    """Remove Docker containers not linked to active checks (fallback cleanup).

    Starts from Docker (source of truth) and validates against database.
    """
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
            _stop_and_remove(container)
            removed += 1
            continue

        # Look up the check
        try:
            check = ManufacturabilityCheck.objects.get(id=check_id)
        except ManufacturabilityCheck.DoesNotExist:
            # Check deleted = orphaned
            _stop_and_remove(container)
            removed += 1
            continue

        # Check exists - is it in an active state?
        # CANCELLING containers are handled by checks_cleanup_cancelling, not here
        if check.status not in [Status.DISPATCHED, Status.RUNNING, Status.CANCELLING]:
            # Check is FINISHED/ERROR/CANCELLED but container still exists
            _stop_and_remove(container)
            removed += 1

    return {"containers_scanned": len(containers), "removed": removed}
```

---

#### 7. `checks_cleanup_orphaned_dispatch()` — Periodic

**Current:** Part of `_handle_dispatched_checks` in monolith (the "lost task" branch)

**Responsibility:**
- Find DISPATCHED checks where Celery task is no longer in queue
- Mark as ERROR (let `checks_retry` handle retry logic)

**Change from current:** Currently moves lost tasks directly to PENDING. New behavior marks as ERROR for single responsibility.

```python
@shared_task(queue="default")
def checks_cleanup_orphaned_dispatch():
    """Mark DISPATCHED checks with lost Celery tasks as ERROR."""
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

---

#### 8. `checks_cleanup_orphaned_processing()` — Periodic

**Current:** Part of `_handle_running_checks` in monolith

**Responsibility:**
- Find RUNNING checks where worker PID is dead or task not in active list
- Mark as ERROR (let `checks_retry` handle retry logic)

```python
@shared_task(queue="default")
def checks_cleanup_orphaned_processing():
    """Mark RUNNING checks with dead workers as ERROR."""
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

---

## Migration Plan

### Phase 1: Add New Tasks (Parallel)

1. Create new tasks alongside existing ones
2. Test new tasks in isolation
3. Keep old tasks running in Celery Beat

### Phase 2: Switch Celery Beat

1. Update `CELERY_BEAT_SCHEDULE` to use new task names
2. Remove old monolith from schedule
3. Monitor for issues

### Phase 3: Cleanup

1. Remove old `process_manufacturability_check_queue`
2. Remove old `cleanup_orphaned_precheck_containers`
3. Remove backwards-compatibility alias `scan_and_queue_manufacturability_checks`

### Phase 4: Deployment Updates

Update all deployment/infrastructure files for new queue names:

**Systemd service files** (`deployment/systemd/`):
- Rename `django-celery-manufacturability.service` → `django-celery-docker-persistent.service`
- Rename `django-celery-maintenance.service` → `django-celery-docker-ephemeral.service`
- Update `--queues` argument in each service file

**Documentation** (`docs/`):
- Update `docs/systemd-services.md` with new queue names and task mappings
- Update any architecture diagrams

**Settings** (`config/settings/`):
- Update `CELERY_BEAT_SCHEDULE` task paths
- Update any queue-related settings

**Scripts** (`deployment/scripts/`):
- Update any deployment scripts that reference queue names
- Update health check scripts if they monitor specific queues

### Migration Principles

**No backwards compatibility shims.** Do not add:
- Aliases mapping old function names to new ones
- Wrapper functions that call the new implementation
- Re-exports of renamed functions

Why: Backwards compatibility hides things that should be updated. If something references the old name, it should fail loudly so it gets fixed, not silently work and accumulate tech debt.

**Delete obsolete tests.** When removing old functionality:
- Delete test classes/methods that test the old implementation
- Do not keep tests "just in case" — they test code that no longer exists
- Write new tests for the new implementation from scratch

Example:
```python
# DELETE this entire class when removing process_manufacturability_check_queue
class TestProcessManufacturabilityCheckQueue:
    ...

# DELETE - do not rename to TestChecksDispatch
# Write fresh tests for checks_dispatch instead
```

---

## Celery Beat Schedule (Proposed)

```python
CELERY_BEAT_SCHEDULE = {
    # Core lifecycle - run frequently
    "checks-dispatch": {
        "task": "wafer_space.projects.tasks.checks_dispatch",
        "schedule": 30.0,  # Every 30 seconds
    },
    "checks-retry": {
        "task": "wafer_space.projects.tasks.checks_retry",
        "schedule": 60.0,  # Every minute
    },
    "checks-create": {
        "task": "wafer_space.projects.tasks.checks_create",
        "schedule": 30.0,  # Every 30 seconds
    },

    # Cancellation cleanup - run frequently (critical for releasing slots)
    "checks-cancelling": {
        "task": "wafer_space.projects.tasks.checks_cancelling",
        "schedule": 15.0,  # Every 15 seconds - fast cancellation matters
    },

    # Orphan detection - run less frequently
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
        "schedule": 300.0,  # Every 5 minutes (expensive Docker API calls)
    },
}
```

---

## Removing ManufacturabilityService

**Decision:** Delete `ManufacturabilityService` entirely. All state changes go through model methods called from views or tasks.

### Current Flow (with service)

```
View → ManufacturabilityService.cancel_check() → model.mark_cancelled() + celery revoke
```

### New Flow (direct model access)

```
View → model.mark_cancelling() → [user sees "Cancelling..."]
Task → checks_cancelling() → revoke + docker stop + model.mark_cancelled()
```

### Changes Required

1. **Delete** `wafer_space/projects/services.py` class `ManufacturabilityService`

2. **Update** `ManufacturabilityCheckCancelView` (`views.py:460`):
   ```python
   # Before:
   if ManufacturabilityService.cancel_check(check, reason="Cancelled by user"):
       messages.success(request, "Manufacturability check cancelled.")

   # After:
   try:
       check.mark_cancelling(reason="Cancelled by user")
       messages.success(request, "Cancellation requested. Cleanup in progress...")
   except InvalidStateTransitionError:
       messages.warning(request, "Check cannot be cancelled (already finished or failed).")
   ```

3. **Update** `ProjectFileService._deactivate_current_file()` (`services.py:354`):
   ```python
   # Before:
   if check.is_cancellable:
       ManufacturabilityService.cancel_check(check, reason="...")

   # After:
   if check.is_cancellable:
       check.mark_cancelling(reason="Cancelled: new file submitted")
   ```

4. **Add model method** `mark_cancelling(reason)`:
   ```python
   def mark_cancelling(self, *, reason: str) -> None:
       """Request cancellation - transitions to CANCELLING state.

       Cleanup task will complete the transition to CANCELLED after
       revoking Celery task and stopping Docker container.
       """
       if not self.can_transition_to(self.Status.CANCELLING):
           raise InvalidStateTransitionError(...)

       self.status = self.Status.CANCELLING
       if self.processing_logs:
           self.processing_logs += f"\n\nCANCELLATION REQUESTED: {reason}"
       else:
           self.processing_logs = f"CANCELLATION REQUESTED: {reason}"
       self.save()
   ```

5. **Simplify** `mark_cancelled()` - only callable from cleanup task:
   ```python
   def mark_cancelled(self) -> None:
       """Complete cancellation - only called by cleanup task after cleanup is done."""
       if not self.can_transition_to(self.Status.CANCELLED):
           raise InvalidStateTransitionError(...)

       self.status = self.Status.CANCELLED
       self.celery_job_finished_at = timezone.now()
       self.save()
   ```

---

## Model Method Summary

After restructure, the model has these state transition methods:

| Method | Transition | Called By |
|--------|------------|-----------|
| `mark_dispatched(celery_job_id)` | PENDING → DISPATCHED | `checks_dispatch` task |
| `mark_running(...)` | DISPATCHED → RUNNING | `check_process_job` task |
| `mark_finished(...)` | RUNNING → FINISHED | `check_process_job` task |
| `mark_error(...)` | PENDING/DISPATCHED/RUNNING → ERROR | `check_process_job`, `checks_cleanup_orphaned_*` |
| `mark_cancelling(reason)` | PENDING/DISPATCHED/RUNNING → CANCELLING | View, ProjectFileService |
| `mark_cancelled()` | CANCELLING → CANCELLED | `checks_cancelling` task only |
| `reset_for_retry(reason)` | ERROR → PENDING | `checks_retry` task |

---

## Resolved Decisions

| Question | Decision |
|----------|----------|
| `checks_create` inline vs separate? | **Separate task** - more resilient |
| Orphan handling: ERROR vs PENDING? | **ERROR** - let retry task handle retries |
| Naming prefix? | **`check_`/`checks_`** - singular for per-job, plural for periodic |
| Queue separation? | **By Docker access/duration**: `default` (no Docker), `docker-ephemeral` (quick Docker ops), `docker-persistent` (long Docker jobs) |
| Cancellation mechanism? | **CANCELLING state** - cleanup before CANCELLED |
