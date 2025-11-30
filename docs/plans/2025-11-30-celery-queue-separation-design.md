# Celery Queue Separation Design

**Date:** 2025-11-30
**Status:** Approved

## Overview

Separate Celery tasks into purpose-specific queues to enable:
- Independent scaling of workers per workload type
- Least-privilege worker deployment
- Isolation of long-running tasks from orchestration tasks

## Queue Architecture

| Queue | Purpose | Permissions Required |
|-------|---------|---------------------|
| `downloads` | File download operations | Filesystem write |
| `manufacturability` | Long-running precheck containers | Docker socket access |
| `maintenance` | Orchestration & cleanup tasks | DB read/write only |
| `default` | General tasks (email) | DB read/write + SMTP |

## Task Assignment

### Downloads Queue
- `download_project_file` - Downloads files up to 100GB with chunked transfer

### Manufacturability Queue
- `check_project_manufacturability` - Runs Docker containers for design checks

### Maintenance Queue
- `ensure_download_tasks_queued` - Orchestrates download task recovery
- `process_manufacturability_check_queue` - Orchestrates check task scheduling
- `cleanup_old_task_results` - Cleans up old Celery task results
- `cleanup_orphaned_precheck_containers` - Cleans up orphaned Docker containers

### Default Queue
- `send_tos_update_email` - Sends TOS update notification emails
- `send_bulk_tos_notifications` - Queues bulk TOS notifications

## Implementation Approach

**Use explicit `queue=` decorators** on each task instead of centralized `CELERY_TASK_ROUTES`.

Rationale:
- Queue assignment is visible at task definition site
- No hidden routing rules to remember
- Single source of truth (decorator, not settings)

## Changes Required

### 1. Remove Centralized Routing (`config/settings/base.py`)

Delete `CELERY_TASK_ROUTES` entirely:
```python
# DELETE THIS:
CELERY_TASK_ROUTES = {
    "wafer_space.projects.tasks.*": {"queue": "manufacturability"},
    "wafer_space.referrals.tasks.*": {"queue": "referrals"},
    "wafer_space.legal.tasks.*": {"queue": "default"},
}
```

### 2. Update Project Tasks (`wafer_space/projects/tasks.py`)

Add explicit queue to each task decorator:

```python
@shared_task(bind=True, queue="downloads", ...)
def download_project_file(self, ...):

@shared_task(bind=True, queue="manufacturability", ...)
def check_project_manufacturability(self, ...):

@shared_task(queue="maintenance")
def ensure_download_tasks_queued():

@shared_task(queue="maintenance")
def process_manufacturability_check_queue():

@shared_task(queue="maintenance")
def cleanup_old_task_results():

# Already has queue="maintenance":
@shared_task(bind=True, queue="maintenance")
def cleanup_orphaned_precheck_containers(self):
```

### 3. Delete Unused Task

Remove `update_project_status` - defined but never called.

### 4. Update Legal Tasks (`wafer_space/legal/tasks.py`)

```python
@shared_task(bind=True, queue="default", ...)
def send_tos_update_email(self, ...):

@shared_task(queue="default")
def send_bulk_tos_notifications(...):
```

### 5. Clean Up Beat Schedule (`config/settings/dev.py`)

Remove redundant `options: {"queue": ...}` from beat schedule entries.
The task decorator is now the single source of truth for queue assignment.

## Worker Deployment Notes

Workers can be started with specific queue filters:

```bash
# Downloads worker (needs filesystem write)
celery -A config worker -Q downloads

# Manufacturability worker (needs Docker)
celery -A config worker -Q manufacturability

# Maintenance worker (minimal permissions)
celery -A config worker -Q maintenance

# Default worker (needs SMTP)
celery -A config worker -Q default

# All queues (development)
celery -A config worker -Q downloads,manufacturability,maintenance,default
```

## Testing

- Verify tasks route to correct queues in test environment
- Ensure beat-scheduled tasks still execute correctly
- Confirm no regressions in task execution
