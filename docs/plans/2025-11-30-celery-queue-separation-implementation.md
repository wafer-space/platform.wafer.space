# Celery Queue Separation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Separate Celery tasks into purpose-specific queues (downloads, manufacturability, maintenance, default) using explicit decorators.

**Architecture:** Remove centralized `CELERY_TASK_ROUTES` and add explicit `queue=` parameter to each task decorator. This makes queue assignment visible at the task definition site.

**Tech Stack:** Django 5.2+, Celery, Python 3.13

---

## Task 1: Add queue="downloads" to download_project_file

**Files:**
- Modify: `wafer_space/projects/tasks.py:2437-2441`

**Step 1: Modify the decorator**

Change lines 2437-2441 from:
```python
@shared_task(
    bind=True,
    max_retries=settings.DOWNLOAD_TASK_MAX_RETRIES,
    default_retry_delay=settings.DOWNLOAD_TASK_RETRY_BASE_DELAY_SECONDS,
)
```

To:
```python
@shared_task(
    bind=True,
    queue="downloads",
    max_retries=settings.DOWNLOAD_TASK_MAX_RETRIES,
    default_retry_delay=settings.DOWNLOAD_TASK_RETRY_BASE_DELAY_SECONDS,
)
```

**Step 2: Run lint**

Run: `make lint-fix && make lint`
Expected: PASS

**Step 3: Commit**

```bash
git add wafer_space/projects/tasks.py
git commit -m "feat(celery): route download_project_file to downloads queue"
```

---

## Task 2: Add queue="manufacturability" to check_project_manufacturability

**Files:**
- Modify: `wafer_space/projects/tasks.py:893-897`

**Step 1: Modify the decorator**

Change lines 893-897 from:
```python
@shared_task(
    bind=True,
    time_limit=settings.PRECHECK_TIMEOUT_SECONDS,
    soft_time_limit=settings.PRECHECK_TIMEOUT_SECONDS - 300,
)
```

To:
```python
@shared_task(
    bind=True,
    queue="manufacturability",
    time_limit=settings.PRECHECK_TIMEOUT_SECONDS,
    soft_time_limit=settings.PRECHECK_TIMEOUT_SECONDS - 300,
)
```

**Step 2: Run lint**

Run: `make lint-fix && make lint`
Expected: PASS

**Step 3: Commit**

```bash
git add wafer_space/projects/tasks.py
git commit -m "feat(celery): route check_project_manufacturability to manufacturability queue"
```

---

## Task 3: Add queue="maintenance" to orchestration tasks

**Files:**
- Modify: `wafer_space/projects/tasks.py:1008, 2707, 3116`

**Step 1: Modify cleanup_old_task_results (line 1008)**

Change:
```python
@shared_task
def cleanup_old_task_results():
```

To:
```python
@shared_task(queue="maintenance")
def cleanup_old_task_results():
```

**Step 2: Modify ensure_download_tasks_queued (line 2707)**

Change:
```python
@shared_task
def ensure_download_tasks_queued():
```

To:
```python
@shared_task(queue="maintenance")
def ensure_download_tasks_queued():
```

**Step 3: Modify process_manufacturability_check_queue (line 3116)**

Change:
```python
@shared_task
def process_manufacturability_check_queue():
```

To:
```python
@shared_task(queue="maintenance")
def process_manufacturability_check_queue():
```

**Step 4: Run lint**

Run: `make lint-fix && make lint`
Expected: PASS

**Step 5: Commit**

```bash
git add wafer_space/projects/tasks.py
git commit -m "feat(celery): route orchestration tasks to maintenance queue"
```

---

## Task 4: Delete unused update_project_status task

**Files:**
- Modify: `wafer_space/projects/tasks.py:2856-2887`

**Step 1: Delete the entire function**

Delete lines 2856-2887 (the blank line before, the decorator, and the entire function body through line 2887).

**Step 2: Run lint**

Run: `make lint-fix && make lint`
Expected: PASS

**Step 3: Run tests to verify no breakage**

Run: `make test`
Expected: PASS (778 tests, function was unused)

**Step 4: Commit**

```bash
git add wafer_space/projects/tasks.py
git commit -m "refactor(celery): remove unused update_project_status task"
```

---

## Task 5: Add queue="default" to legal tasks

**Files:**
- Modify: `wafer_space/legal/tasks.py:31, 136`

**Step 1: Modify send_tos_update_email (line 31)**

Change:
```python
@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_tos_update_email(self, notification_id: int) -> dict[str, str]:
```

To:
```python
@shared_task(bind=True, queue="default", max_retries=3, default_retry_delay=300)
def send_tos_update_email(self, notification_id: int) -> dict[str, str]:
```

**Step 2: Modify send_bulk_tos_notifications (line 136)**

Change:
```python
@shared_task
def send_bulk_tos_notifications(
```

To:
```python
@shared_task(queue="default")
def send_bulk_tos_notifications(
```

**Step 3: Run lint**

Run: `make lint-fix && make lint`
Expected: PASS

**Step 4: Commit**

```bash
git add wafer_space/legal/tasks.py
git commit -m "feat(celery): route legal tasks to default queue"
```

---

## Task 6: Remove centralized CELERY_TASK_ROUTES

**Files:**
- Modify: `config/settings/base.py:423-427`

**Step 1: Delete CELERY_TASK_ROUTES**

Delete lines 423-427:
```python
CELERY_TASK_ROUTES = {
    "wafer_space.projects.tasks.*": {"queue": "manufacturability"},
    "wafer_space.referrals.tasks.*": {"queue": "referrals"},
    "wafer_space.legal.tasks.*": {"queue": "default"},
}
```

**Step 2: Run lint**

Run: `make lint-fix && make lint`
Expected: PASS

**Step 3: Commit**

```bash
git add config/settings/base.py
git commit -m "refactor(celery): remove centralized CELERY_TASK_ROUTES

Queue routing is now handled by explicit queue= parameter on each task decorator."
```

---

## Task 7: Clean up dev.py beat schedule

**Files:**
- Modify: `config/settings/dev.py:93-96`

**Step 1: Remove redundant queue option**

Change lines 93-97 from:
```python
    "cleanup-orphaned-precheck-containers": {
        "task": "wafer_space.projects.tasks.cleanup_orphaned_precheck_containers",
        "schedule": PRECHECK_CONTAINER_CLEANUP_INTERVAL_SECONDS,
        "options": {"queue": "maintenance"},
    },
```

To:
```python
    "cleanup-orphaned-precheck-containers": {
        "task": "wafer_space.projects.tasks.cleanup_orphaned_precheck_containers",
        "schedule": PRECHECK_CONTAINER_CLEANUP_INTERVAL_SECONDS,
    },
```

**Step 2: Run lint**

Run: `make lint-fix && make lint`
Expected: PASS

**Step 3: Commit**

```bash
git add config/settings/dev.py
git commit -m "refactor(celery): remove redundant queue option from beat schedule

Task decorator is now the single source of truth for queue assignment."
```

---

## Task 8: Run full test suite and type check

**Files:** None (verification only)

**Step 1: Run type check**

Run: `make type-check`
Expected: PASS

**Step 2: Run full test suite**

Run: `make test`
Expected: PASS (778 tests)

**Step 3: Verify no lint issues**

Run: `make lint`
Expected: PASS

---

## Task 9: Final commit summary

After all tasks complete, the queue routing will be:

| Task | Queue |
|------|-------|
| `download_project_file` | downloads |
| `check_project_manufacturability` | manufacturability |
| `cleanup_old_task_results` | maintenance |
| `ensure_download_tasks_queued` | maintenance |
| `process_manufacturability_check_queue` | maintenance |
| `cleanup_orphaned_precheck_containers` | maintenance |
| `send_tos_update_email` | default |
| `send_bulk_tos_notifications` | default |

Workers can now be started with specific queue filters for least-privilege deployment.
