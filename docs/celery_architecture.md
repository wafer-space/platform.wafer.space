# Celery Architecture

This document describes the Celery task queue architecture used in the wafer.space platform.

## Overview

wafer.space uses Celery for asynchronous task processing with:
- **Broker:** PostgreSQL via SQLAlchemy (`sqla+postgresql://...`)
- **Result Backend:** Django database (`django-db`)
- **Scheduler:** Celery Beat for periodic tasks

> **Note:** Redis and RabbitMQ are banned. See `CLAUDE.md` for details.

---

## Queue Naming Convention

Queues follow a structured naming pattern: `<protocol>:<mode>:<function>`

### Protocol (Network/System Access)

| Protocol | Description | Example Use |
|----------|-------------|-------------|
| `none` | No external access needed | Orchestration, database-only tasks |
| `http` | HTTP/HTTPS network access | File downloads, API calls |
| `dock` | Docker daemon access | Container operations |
| `mail` | Email sending capability | SMTP operations |

### Mode (Read/Write)

| Mode | Description |
|------|-------------|
| `ro` | Read-only operations (queries, polling, monitoring) |
| `rw` | Read-write operations (creates files, modifies state) |

### Function (Purpose)

| Function | Description |
|----------|-------------|
| `default` | General-purpose tasks |
| `downloads` | File download operations |
| `checks-orch` | Manufacturability check orchestration (periodic polling) |
| `checks-fast` | Quick check operations (container start, status polling) |
| `checks-slow` | Slow operations (Docker image pulls) |
| `checks-save` | Check result persistence (file extraction, log parsing) |
| `email` | Email sending |

### Queue Examples

```text
none:ro:default      - General tasks, no external access
none:ro:checks-orch  - Check orchestration (polling)
http:rw:downloads    - File downloads (network + file writes)
dock:ro:checks-fast  - Quick Docker operations (status checks)
dock:ro:checks-slow  - Slow Docker operations (image pulls)
dock:rw:checks-save  - Docker + file writes (extract outputs)
mail:ro:email        - Email sending
```

---

## Manufacturability Check State Machine

The manufacturability checking system uses a **polling-based state machine** architecture. Celery Beat runs orchestration tasks every 15 seconds that scan for checks in specific states and queue work tasks to advance them.

### State Flow

```text
┌────────────────────────────────────────────────────────────────────────┐
│                                                                        │
│  PENDING ──► DISPATCHING ──► STARTING ──► RUNNING ──► ANALYZING       │
│     │            │              │            │             │           │
│     │            ▼              ▼            ▼             ▼           │
│     │         (pull         (create      (poll        (parse          │
│     │          image)       container)   logs)        results)        │
│     │                                                     │           │
│     │                                                     ▼           │
│     │                                                 FINISHED        │
│     │                                                     │           │
│     │      ┌──────────────────────────────────────────────┘           │
│     │      │                                                          │
│     │      ▼                                                          │
│     └──► ERROR ◄──────────────────────────────────────────────────────┤
│            │                                                          │
│            ▼                                                          │
│         (retry)                                                       │
│                                                                       │
│  CANCELLING ──► CANCELLED                                             │
│                                                                       │
└────────────────────────────────────────────────────────────────────────┘
```

### Two Task Types

#### 1. Orchestration Tasks (`@checks_task`)

Periodic tasks that poll the database for checks in a specific state and queue work tasks.

- Run every 15-60 seconds via Celery Beat
- Query database for checks needing action
- Queue work tasks for each check found
- Default queue: `none:ro:checks-orch`

```python
@checks_task()
def checks_pending() -> dict[str, int]:
    """Find PENDING checks and transition to DISPATCHING."""
    # Query for PENDING checks
    # Assign server, transition to DISPATCHING
    # Queue do_dispatching work tasks
    return {"dispatched": count}
```

#### 2. Work Tasks (`@queued_check_task`)

Tasks that perform actual operations on a single check.

- Queued by orchestration tasks
- Receive check_id, fetch ManufacturabilityCheck object
- Verify expected status before proceeding (race condition protection)
- Default queue: `dock:ro:checks-fast`

```python
@queued_check_task(expected_status="DISPATCHING", queue="dock:ro:checks-slow")
def do_dispatching(check: ManufacturabilityCheck) -> dict[str, str]:
    """Pull Docker image for the check."""
    # Pull image
    # Transition to STARTING
    return {"image": image_name}
```

### Task Tracking Model

The `ManufacturabilityCheckTask` model prevents duplicate task queuing:

```python
# Before queuing a work task:
task, created = ManufacturabilityCheckTask.objects.get_or_create(
    check=check,
    task_name="do_dispatching",
)
if created:
    do_dispatching.delay(check.id)
```

The `@queued_check_task` decorator automatically cleans up task records in a `finally` block, allowing re-queuing on the next orchestration cycle if needed.

---

## Beat Schedule

Periodic tasks are configured in `config/settings/base.py`:

### Check Lifecycle (15-second intervals)

| Task | Purpose |
|------|---------|
| `checks-create` | Create checks for verified downloads |
| `checks-pending` | PENDING → DISPATCHING transition |
| `checks-dispatching` | Queue `do_dispatching` work tasks |
| `checks-starting` | Queue `do_starting` work tasks |
| `checks-running` | Queue `do_running` work tasks |
| `checks-analyzing` | Queue `do_analyzing` work tasks |
| `checks-cancelling` | CANCELLING → CANCELLED transition |

### Cleanup & Recovery (60-second intervals)

| Task | Purpose |
|------|---------|
| `checks-retry` | Create retry checks for ERROR state |
| `checks-cleanup-orphaned-docker` | Remove orphaned containers |
| `checks-cleanup-stale-files` | Cancel checks on inactive files |
| `checks-cleanup-stale-pending-tasks` | Remove orphaned task tracking records |
| `ensure-download-tasks-queued` | Recovery for orphaned downloads |

---

## Task Decorators

### `@checks_task(**celery_kwargs)`

For orchestration tasks (periodic polling).

**Features:**
- Wraps with `@shared_task`
- Automatic start/complete logging
- Default queue: `none:ro:checks-orch`

**Usage:**
```python
@checks_task()
def checks_pending() -> dict[str, int]:
    ...
```

### `@queued_check_task(expected_status=None, **celery_kwargs)`

For work tasks that operate on a single check.

**Features:**
- Wraps with `@shared_task`
- Auto-fetches ManufacturabilityCheck from check_id
- Status verification (skips if status changed)
- Auto-cleanup of ManufacturabilityCheckTask records
- Converts `TaskExecutionError` to `check.mark_error()`
- Default queue: `dock:ro:checks-fast`

**Usage:**
```python
@queued_check_task(expected_status="RUNNING", queue="dock:ro:checks-fast")
def do_running(check: ManufacturabilityCheck) -> dict[str, Any]:
    ...
```

---

## Worker Configuration

Workers should be configured to consume specific queues based on their capabilities:

| Worker Type | Queues | Requirements |
|-------------|--------|--------------|
| Default | `none:ro:*` | Database access only |
| Downloads | `http:rw:downloads` | Network + filesystem |
| Docker Fast | `dock:ro:checks-fast`, `dock:rw:checks-save` | Docker daemon |
| Docker Slow | `dock:ro:checks-slow` | Docker daemon (image pulls) |
| Email | `mail:ro:email` | SMTP access |

### Development (Procfile)

See `Procfile` for local development worker configuration.

> **Note:** The Procfile queue names may differ from actual task queue assignments. See GitHub issue for alignment work.

### Production (systemd)

See `docs/systemd-services.md` for production worker configuration.

---

## Configuration Reference

Key Celery settings in `config/settings/base.py`:

```python
CELERY_BROKER_URL = "sqla+postgresql://..."  # PostgreSQL broker
CELERY_RESULT_BACKEND = "django-db"          # Django ORM results
CELERY_TASK_TIME_LIMIT = 30 * 60             # 30 min hard limit
CELERY_TASK_SOFT_TIME_LIMIT = 25 * 60        # 25 min soft limit
CELERY_RESULT_EXPIRES = 3600                 # 1 hour result retention
```

---

## Related Documentation

- [Celery Tasks Reference](celery_tasks_reference.md) - Complete task listing
- [systemd Services](systemd-services.md) - Production worker configuration
- [Settings Catalog](settings.md) - All configuration options
