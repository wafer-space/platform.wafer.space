# Celery Tasks Reference

Complete reference of all Celery tasks in the wafer.space platform.

For architecture details, see [Celery Architecture](celery_architecture.md).

---

## Download Tasks

**Location:** `wafer_space/projects/tasks_download.py`

| Task | Queue | Description | Retry |
|------|-------|-------------|-------|
| `cleanup_old_task_results` | `none:ro:default` | Remove task results older than 24 hours | No |
| `download_project_file` | `http:rw:downloads` | Download file with chunking, hash verification, resume support | Yes (2 retries, 60s base, 2x backoff) |
| `ensure_download_tasks_queued` | `none:ro:default` | Recovery: detect orphaned downloads and requeue | No |

### download_project_file

Main download task with comprehensive features:
- Chunked downloading (up to 100GB)
- Resume capability via HTTP Range requests
- Hash verification (MD5, SHA1, SHA256)
- GitHub artifact authentication support
- Content pipeline (extraction, decompression)
- Top cell extraction from GDS/OASIS files
- Progress tracking via Celery task state

---

## Manufacturability Check Tasks

**Location:** `wafer_space/projects/tasks_checks.py`

### Orchestration Tasks

These tasks run periodically via Celery Beat to poll for checks needing action.

| Task | Queue | Schedule | Description |
|------|-------|----------|-------------|
| `checks_create` | `none:ro:checks-orch` | 15s | Create checks for verified downloads |
| `checks_pending` | `none:ro:checks-orch` | 15s | PENDING → DISPATCHING transition |
| `checks_dispatching` | `none:ro:checks-orch` | 15s | Queue `do_dispatching` work tasks |
| `checks_starting` | `none:ro:checks-orch` | 15s | Queue `do_starting` work tasks |
| `checks_running` | `none:ro:checks-orch` | 15s | Queue `do_running` work tasks |
| `checks_analyzing` | `none:ro:checks-orch` | 15s | Queue `do_analyzing` work tasks |
| `checks_cancelling` | `none:ro:checks-orch` | 15s | CANCELLING → CANCELLED transition |
| `checks_retry` | `none:ro:checks-orch` | 60s | Create retry checks for ERROR state |
| `checks_cleanup_stale_files` | `none:ro:checks-orch` | 60s | Cancel checks on inactive files |
| `checks_cleanup_stale_pending_tasks` | `none:ro:checks-orch` | 60s | Remove orphaned task tracking records |
| `checks_cleanup` | `none:ro:checks-orch` | - | Combined cleanup operations |

### Work Tasks

These tasks perform actual operations on individual checks.

| Task | Queue | Expected Status | Description |
|------|-------|-----------------|-------------|
| `do_dispatching` | `dock:ro:checks-slow` | DISPATCHING | Pull Docker image |
| `do_starting` | `dock:ro:checks-fast` | STARTING | Create and start container |
| `do_running` | `dock:ro:checks-fast` | RUNNING | Poll container, download logs |
| `do_analyzing` | `dock:rw:checks-save` | ANALYZING | Extract outputs, parse logs, determine results |

### Cleanup Tasks

| Task | Queue | Schedule | Description |
|------|-------|----------|-------------|
| `checks_cleanup_orphaned_docker` | `dock:ro:checks-fast` | 60s | Remove Docker containers not linked to active checks |

---

## Legal Tasks

**Location:** `wafer_space/legal/tasks.py`

| Task | Queue | Description | Retry |
|------|-------|-------------|-------|
| `send_tos_update_email` | `mail:ro:email` | Send TOS update notification to a user | Yes (3 retries, 5min delay) |
| `send_bulk_tos_notifications` | `mail:ro:email` | Create and queue notifications for multiple users | No |

---

## Debug Tasks

**Location:** `config/celery.py`

| Task | Queue | Description |
|------|-------|-------------|
| `debug_task` | default | Test task for verifying Celery configuration |

---

## Task Count Summary

| Category | Count |
|----------|-------|
| Download tasks | 3 |
| Check orchestration tasks | 11 |
| Check work tasks | 4 |
| Check cleanup tasks | 1 |
| Legal tasks | 2 |
| Debug tasks | 1 |
| **Total** | **22** |

---

## Queue Summary

| Queue | Task Count | Purpose |
|-------|------------|---------|
| `none:ro:default` | 2 | General tasks, no external access |
| `none:ro:checks-orch` | 11 | Check orchestration (polling) |
| `http:rw:downloads` | 1 | File downloads |
| `dock:ro:checks-fast` | 3 | Quick Docker operations |
| `dock:ro:checks-slow` | 1 | Slow Docker operations (image pulls) |
| `dock:rw:checks-save` | 1 | Docker + file persistence |
| `mail:ro:email` | 2 | Email sending |
| default | 1 | Debug/test tasks |

---

## Beat Schedule Summary

All periodic tasks are defined in `CELERY_BEAT_SCHEDULE` in `config/settings/base.py`.

| Interval | Tasks |
|----------|-------|
| 15 seconds | Check lifecycle (create, pending, dispatching, starting, running, analyzing, cancelling) |
| 60 seconds | Cleanup (retry, orphaned docker, stale files, stale pending tasks), download recovery |
