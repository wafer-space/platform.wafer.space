# Systemd Services Configuration

This document describes the systemd service units for platform.wafer.space, their security configurations, and the principle of least privilege applied to each.

## Architecture Overview

```
                                    +-----------------+
                                    |    PostgreSQL   |
                                    +-----------------+
                                           |
          +--------------------------------+--------------------------------+
          |                |               |               |                |
+---------v----+  +--------v-------+  +----v----+  +------v------+  +------v------+
|   Gunicorn   |  | Celery Default |  | Celery  |  |   Celery    |  |   Celery    |
| (Web Server) |  |   (Email)      |  |Downloads|  |Manufacturab.|  | Maintenance |
+--------------+  +----------------+  +---------+  +-------------+  +-------------+
                                           |              |               |
                                           v              v               v
                                      +--------+    +--------+       +--------+
                                      | Media  |    | Docker |       | Docker |
                                      | Files  |    | Socket |       | Socket |
                                      +--------+    +--------+       +--------+
```

## Common Configuration

All services share these security hardening settings:

- **NoNewPrivileges=true** - Process cannot gain new privileges
- **PrivateDevices=true** - Isolated /dev with only pseudo-devices (null, zero, random)
- **PrivateTmp=true** - Isolated /tmp namespace
- **ReadOnlyPaths=/home/django/platform.wafer.space** - Application code read-only

RuntimeDirectory and LogsDirectory are automatically excluded from ProtectSystem restrictions.

### Users

| User       | Services                                | Docker Access |
|------------|----------------------------------------|:-------------:|
| www-data   | gunicorn, celery, celery-downloads, celery-beat | No      |
| celery-mfg | celery-manufacturability, celery-maintenance    | Yes     |

The `celery-mfg` user requires `SupplementaryGroups=docker` for Docker socket access at `/var/run/docker.sock`. Note: Docker socket access is root-equivalent.

### Environment Variables

Systemd provides these variables to all services:

- `$RUNTIME_DIRECTORY` - e.g., `/run/platform.wafer.space-celery`
- `$LOGS_DIRECTORY` - e.g., `/var/log/platform.wafer.space-celery`

---

## Service Details

### django-gunicorn.service

WSGI application server serving HTTP requests via Unix socket.

- **Type:** notify
- **Queues:** -
- **ProtectSystem:** strict

**Files:**
- `$RUNTIME_DIRECTORY/gunicorn.sock` - Unix socket for nginx
- `$LOGS_DIRECTORY/access.log`, `$LOGS_DIRECTORY/error.log`

---

### django-celery.service

Default Celery worker for email notifications and referral processing.

- **Type:** forking
- **Queues:** default, referrals
- **Hostname:** default@%h
- **ProtectSystem:** strict

**Tasks:**
- `send_tos_update_email` - Send TOS notification email
- `send_bulk_tos_notifications` - Queue bulk TOS notifications

---

### django-celery-downloads.service

Dedicated worker for downloading large files (up to 100GB) from external URLs.

- **Type:** forking
- **Queues:** downloads
- **Hostname:** downloads@%h
- **ProtectSystem:** strict
- **ReadWritePaths:** `.../wafer_space/media` (for saving downloaded files)

**Tasks:**
- `download_project_file` - Chunked transfer with resume support and hash verification

**Media files written:** `project_file.file.save()` saves downloaded files

---

### django-celery-manufacturability.service

Runs manufacturability checks in Docker containers (gf180mcu-precheck).

- **Type:** forking
- **User:** celery-mfg
- **Queues:** manufacturability
- **Hostname:** manufacturability@%h
- **SupplementaryGroups:** docker
- **ReadWritePaths:** `.../wafer_space/media` (for saving check results)

**Tasks:**
- `check_project_manufacturability` - Run gf180mcu-precheck in Docker container

**Media files written:**
- `check.log_file` - Container stdout/stderr logs
- `check.runs_archive` - Detailed run directory as tar archive

---

### django-celery-maintenance.service

Orchestration tasks that manage other tasks and clean up resources.

- **Type:** forking
- **User:** celery-mfg
- **Queues:** maintenance
- **Hostname:** maintenance@%h
- **SupplementaryGroups:** docker

**Tasks:**
- `ensure_download_tasks_queued` - Recover lost download tasks
- `process_manufacturability_check_queue` - Orchestrate check scheduling
- `cleanup_old_task_results` - Remove old Celery TaskResult records
- `cleanup_orphaned_precheck_containers` - Remove orphaned Docker containers

---

### django-celery-beat.service

Celery Beat scheduler that triggers periodic tasks.

- **Type:** simple
- **ProtectSystem:** strict

**Files:**
- `$RUNTIME_DIRECTORY/beat.pid`
- `$RUNTIME_DIRECTORY/celerybeat-schedule` - Schedule database
- `$LOGS_DIRECTORY/beat.log`

---

## Summary Tables

### Services Overview

| Service                      | User       | Queue(s)           | Media | Docker |
|------------------------------|------------|--------------------|:-----:|:------:|
| **gunicorn**                 | www-data   | -                  | -     | -      |
| **celery**                   | www-data   | default, referrals | -     | -      |
| **celery-downloads**         | www-data   | downloads          | W     | -      |
| **celery-manufacturability** | celery-mfg | manufacturability  | W     | Y      |
| **celery-maintenance**       | celery-mfg | maintenance        | -     | Y      |
| **celery-beat**              | www-data   | -                  | -     | -      |

**Legend:** W = Write, Y = Yes, - = None

### Task to Queue Mapping

| Queue             | Task                                    | Description                                               |
|-------------------|-----------------------------------------|-----------------------------------------------------------|
| default           | `send_tos_update_email`                 | Send TOS notification email to user                       |
| default           | `send_bulk_tos_notifications`           | Queue bulk TOS notifications                              |
| downloads         | `download_project_file`                 | Download with chunked transfer, resume, hash verification |
| manufacturability | `check_project_manufacturability`       | Run gf180mcu-precheck in Docker container                 |
| maintenance       | `ensure_download_tasks_queued`          | Recover lost download tasks                               |
| maintenance       | `process_manufacturability_check_queue` | Orchestrate check scheduling                              |
| maintenance       | `cleanup_old_task_results`              | Remove old Celery TaskResult records                      |
| maintenance       | `cleanup_orphaned_precheck_containers`  | Remove orphaned Docker containers                         |

---

## Code References

### Default Queue Tasks

**`send_tos_update_email`**
- **Defined:** `wafer_space/legal/tasks.py:31`
- **Called from:**
  - `wafer_space/legal/tasks.py:199` - `send_bulk_tos_notifications()` queues individual emails
  - `wafer_space/legal/admin.py:251` - Admin action to resend TOS notification

**`send_bulk_tos_notifications`**
- **Defined:** `wafer_space/legal/tasks.py:136`
- **Called from:** Admin actions via Django admin interface

### Downloads Queue Tasks

**`download_project_file`**
- **Defined:** `wafer_space/projects/tasks.py:2440`
- **Called from:**
  - `wafer_space/projects/services.py:417` - `queue_download_task()` service function
  - `wafer_space/projects/tasks.py:2741` - `ensure_download_tasks_queued()` recovery task
  - `wafer_space/projects/tasks.py:2832` - `ensure_download_tasks_queued()` recovery task (different code path)

### Manufacturability Queue Tasks

**`check_project_manufacturability`**
- **Defined:** `wafer_space/projects/tasks.py:893`
- **Called from:**
  - `wafer_space/projects/services.py:649` - `queue_manufacturability_check()` service function
  - `wafer_space/projects/tasks.py:3075` - `process_manufacturability_check_queue()` orchestration task

### Maintenance Queue Tasks

**`cleanup_old_task_results`**
- **Defined:** `wafer_space/projects/tasks.py:1011`
- **Called from:** Celery Beat scheduler (periodic task)

**`ensure_download_tasks_queued`**
- **Defined:** `wafer_space/projects/tasks.py:2711`
- **Called from:** Celery Beat scheduler (periodic task)

**`process_manufacturability_check_queue`**
- **Defined:** `wafer_space/projects/tasks.py:3088`
- **Called from:** Celery Beat scheduler (periodic task)

**`cleanup_orphaned_precheck_containers`**
- **Defined:** `wafer_space/projects/tasks.py:3155`
- **Called from:** Celery Beat scheduler (periodic task)

---

## Directory Structure

```text
/run/
├── platform.wafer.space-gunicorn/
│   └── gunicorn.sock
├── platform.wafer.space-celery/
│   └── worker.pid
├── platform.wafer.space-celery-downloads/
│   └── worker.pid
├── platform.wafer.space-celery-manufacturability/
│   └── worker.pid
├── platform.wafer.space-celery-maintenance/
│   └── worker.pid
└── platform.wafer.space-celery-beat/
    ├── beat.pid
    └── celerybeat-schedule

/var/log/
├── platform.wafer.space-gunicorn/
│   ├── access.log
│   └── error.log
├── platform.wafer.space-celery/
│   └── worker.log
├── platform.wafer.space-celery-downloads/
│   └── worker.log
├── platform.wafer.space-celery-manufacturability/
│   └── worker.log
├── platform.wafer.space-celery-maintenance/
│   └── worker.log
└── platform.wafer.space-celery-beat/
    └── beat.log
```

---

## Installation

```bash
cd deployment/systemd
sudo ./install.sh
```

This will:
1. Copy service files to `/etc/systemd/system/`
2. Reload systemd daemon
3. Enable all services
4. Restart all services

## Monitoring

```bash
# Check status
sudo systemctl status django-gunicorn
sudo systemctl status django-celery
sudo systemctl status django-celery-downloads
sudo systemctl status django-celery-manufacturability
sudo systemctl status django-celery-maintenance
sudo systemctl status django-celery-beat

# View logs via journalctl
sudo journalctl -u django-celery -f

# View logs via log files
sudo tail -f /var/log/platform.wafer.space-celery/worker.log
```

## User Setup

The `celery-mfg` user must be created and added to the `docker` group:

```bash
sudo useradd -r -s /bin/false celery-mfg
sudo usermod -aG docker celery-mfg
```
