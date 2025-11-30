# Systemd Services Configuration

This document describes the systemd service units for platform.wafer.space, their security configurations, and the principle of least privilege applied to each.

## Services Overview

| Service                      | User       | Queue(s)           | Media | Docker |
|------------------------------|------------|--------------------|:-----:|:------:|
| **gunicorn**                 | www-data   | -                  | -     | -      |
| **celery**                   | www-data   | default, referrals | -     | -      |
| **celery-downloads**         | www-data   | downloads          | W     | -      |
| **celery-docker-persistent** | celery-mfg | docker-persistent  | W     | Y      |
| **celery-docker-ephemeral**  | celery-mfg | docker-ephemeral   | -     | Y      |
| **celery-beat**              | www-data   | -                  | -     | -      |

**Legend:** W = Write, Y = Yes, - = None

## Task to Queue Mapping

| Queue             | Task                                | Description                                               |
|-------------------|-------------------------------------|-----------------------------------------------------------|
| default           | `send_tos_update_email`             | Send TOS notification email to user                       |
| default           | `send_bulk_tos_notifications`       | Queue bulk TOS notifications                              |
| default           | `checks_create`                     | Create new checks from ready files                        |
| default           | `checks_dispatch`                   | Dispatch PENDING checks to docker-persistent queue        |
| default           | `checks_retry`                      | Retry ERROR checks within limit                           |
| default           | `checks_cleanup_orphaned_dispatch`  | Detect and reset stuck DISPATCHED checks                  |
| default           | `checks_cleanup_orphaned_processing` | Detect and reset stuck PROCESSING checks                  |
| downloads         | `download_project_file`             | Download with chunked transfer, resume, hash verification |
| docker-persistent | `check_process_job`                 | Run gf180mcu-precheck in Docker container                 |
| docker-ephemeral  | `ensure_download_tasks_queued`      | Recover lost download tasks                               |
| docker-ephemeral  | `cleanup_old_task_results`          | Remove old Celery TaskResult records                      |
| docker-ephemeral  | `checks_cancelling`                 | Complete cancellation of CANCELLING checks                |
| docker-ephemeral  | `checks_cleanup_orphaned_docker`    | Remove orphaned Docker containers                         |

---

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
| (Web Server) |  | (Orchestrat.)  |  |Downloads|  |Docker-Persist|  |Docker-Ephem.|
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

Default Celery worker for email notifications and check orchestration tasks.

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

`checks_create` - Create checks from ready files
- Defined: `wafer_space/projects/tasks.py:3093`
- Called from: Celery Beat scheduler (periodic, every 30s)

`checks_dispatch` - Dispatch PENDING checks to docker-persistent
- Defined: `wafer_space/projects/tasks.py:3033`
- Called from: Celery Beat scheduler (periodic, every 30s)

`checks_retry` - Retry ERROR checks within limit
- Defined: `wafer_space/projects/tasks.py:3070`
- Called from: Celery Beat scheduler (periodic, every 60s)

`checks_cleanup_orphaned_dispatch` - Reset stuck DISPATCHED checks
- Defined: `wafer_space/projects/tasks.py:3121`
- Called from: Celery Beat scheduler (periodic, every 60s)

`checks_cleanup_orphaned_processing` - Reset stuck PROCESSING checks
- Defined: `wafer_space/projects/tasks.py:3153`
- Called from: Celery Beat scheduler (periodic, every 60s)

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
- Defined: `wafer_space/projects/tasks.py:2460`
- Called from: `wafer_space/projects/services.py` (queue_download_task), `wafer_space/projects/tasks.py:2726` (ensure_download_tasks_queued recovery)
- Writes: `project_file.file.save()` saves downloaded files to media

---

### django-celery-docker-persistent.service

Runs long-running Docker jobs (manufacturability checks via gf180mcu-precheck).

- **Type:** forking
- **User:** celery-mfg
- **Queues:** docker-persistent
- **Hostname:** docker-persistent@%h
- **SupplementaryGroups:** docker
- **ReadWritePaths:** `.../wafer_space/media` (for saving check results)

**Tasks:**

`check_process_job` - Run gf180mcu-precheck in Docker container
- Defined: `wafer_space/projects/tasks.py:903`
- Called from: `wafer_space/projects/tasks.py:3033` (checks_dispatch dispatches PENDING checks)
- Writes: `check.log_file` (container logs), `check.runs_archive` (run directory tar)

**State Machine:** ManufacturabilityCheck uses a state machine with transitions:
- PENDING → DISPATCHED → PROCESSING → FINISHED/ERROR
- CANCELLING → CANCELLED is a terminal state (cannot be restarted)
- ERROR checks can be retried up to 3 times

---

### django-celery-docker-ephemeral.service

Quick Docker operations and cleanup tasks (no long-running containers).

- **Type:** forking
- **User:** celery-mfg
- **Queues:** docker-ephemeral
- **Hostname:** docker-ephemeral@%h
- **SupplementaryGroups:** docker

**Tasks:**

`ensure_download_tasks_queued` - Recover lost download tasks
- Defined: `wafer_space/projects/tasks.py:2726`
- Called from: Celery Beat scheduler (periodic)

`cleanup_old_task_results` - Remove old Celery TaskResult records
- Defined: `wafer_space/projects/tasks.py:1024`
- Called from: Celery Beat scheduler (periodic)

`checks_cancelling` - Complete cancellation of CANCELLING checks
- Defined: `wafer_space/projects/tasks.py:3188`
- Called from: Celery Beat scheduler (periodic, every 15s)
- Handles: CANCELLING → CANCELLED transitions, stops containers

`checks_cleanup_orphaned_docker` - Remove orphaned Docker containers
- Defined: `wafer_space/projects/tasks.py:2935`
- Called from: Celery Beat scheduler (periodic, every 5min)

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
sudo systemctl status django-celery-docker-persistent
sudo systemctl status django-celery-docker-ephemeral
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
