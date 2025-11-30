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
- **ProtectSystem=strict** - Entire filesystem mounted read-only (except allowed paths)
- **ReadOnlyPaths=/home/django/platform.wafer.space** - Application code read-only

RuntimeDirectory and LogsDirectory are automatically excluded from ProtectSystem restrictions.

### Users

| User       | Services                                        | Docker Access |
|------------|-------------------------------------------------|:-------------:|
| www-data   | gunicorn, celery, celery-downloads, celery-beat | No            |
| celery-mfg | celery-manufacturability, celery-maintenance    | Yes           |

### Docker Socket Access

Services needing Docker access use:
- `SupplementaryGroups=docker` - Group permission on the socket
- `BindPaths=/var/run/docker.sock` - Makes socket accessible despite ProtectSystem=strict

Note: Docker socket access is root-equivalent. The `celery-mfg` user must be in the `docker` group.

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

`send_tos_update_email` - Send TOS notification email
- Defined: `wafer_space/legal/tasks.py:31`
- Called from: `wafer_space/legal/tasks.py:199` (bulk notifications), `wafer_space/legal/admin.py:251` (admin action)

`send_bulk_tos_notifications` - Queue bulk TOS notifications
- Defined: `wafer_space/legal/tasks.py:136`
- Called from: Django admin interface

---

### django-celery-downloads.service

Dedicated worker for downloading large files (up to 100GB) from external URLs.

- **Type:** forking
- **Queues:** downloads
- **Hostname:** downloads@%h
- **ProtectSystem:** strict
- **ReadWritePaths:** `.../wafer_space/media` (for saving downloaded files)

**Tasks:**

`download_project_file` - Chunked transfer with resume support and hash verification
- Defined: `wafer_space/projects/tasks.py:2440`
- Called from: `wafer_space/projects/services.py:417` (queue_download_task), `wafer_space/projects/tasks.py:2741` and `:2832` (ensure_download_tasks_queued recovery)
- Writes: `project_file.file.save()` saves downloaded files to media

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

`check_project_manufacturability` - Run gf180mcu-precheck in Docker container
- Defined: `wafer_space/projects/tasks.py:893`
- Called from: `wafer_space/projects/services.py:649` (queue_manufacturability_check), `wafer_space/projects/tasks.py:3075` (process_manufacturability_check_queue)
- Writes: `check.log_file` (container logs), `check.runs_archive` (run directory tar)

---

### django-celery-maintenance.service

Orchestration tasks that manage other tasks and clean up resources.

- **Type:** forking
- **User:** celery-mfg
- **Queues:** maintenance
- **Hostname:** maintenance@%h
- **SupplementaryGroups:** docker

**Tasks:**

`ensure_download_tasks_queued` - Recover lost download tasks
- Defined: `wafer_space/projects/tasks.py:2711`
- Called from: Celery Beat scheduler (periodic)

`process_manufacturability_check_queue` - Orchestrate check scheduling
- Defined: `wafer_space/projects/tasks.py:3088`
- Called from: Celery Beat scheduler (periodic)

`cleanup_old_task_results` - Remove old Celery TaskResult records
- Defined: `wafer_space/projects/tasks.py:1011`
- Called from: Celery Beat scheduler (periodic)

`cleanup_orphaned_precheck_containers` - Remove orphaned Docker containers
- Defined: `wafer_space/projects/tasks.py:3155`
- Called from: Celery Beat scheduler (periodic)

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
