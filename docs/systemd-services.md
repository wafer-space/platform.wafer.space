# Systemd Services Configuration

This document describes the systemd service units for platform.wafer.space, their security configurations, and the principle of least privilege applied to each.

## Architecture Overview

The application is split into isolated services, each with minimal permissions:

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

## Service Units

### django-gunicorn.service

**Purpose:** WSGI application server serving HTTP requests via Unix socket.

| Property         | Value                            |
|------------------|----------------------------------|
| Type             | `notify`                         |
| User             | `www-data`                       |
| Group            | `www-data`                       |
| RuntimeDirectory | `platform.wafer.space-gunicorn`  |
| LogsDirectory    | `platform.wafer.space-gunicorn`  |

**Files Written:**
- `/run/platform.wafer.space-gunicorn/gunicorn.sock` - Unix socket for nginx
- `/var/log/platform.wafer.space-gunicorn/access.log` - HTTP access logs
- `/var/log/platform.wafer.space-gunicorn/error.log` - Application errors

**Security Hardening:**
| Setting         | Value                              | Purpose                       |
|-----------------|------------------------------------|-------------------------------|
| ProtectSystem   | `strict`                           | Entire filesystem read-only   |
| ReadOnlyPaths   | `/home/django/platform.wafer.space`| Application code read-only    |
| PrivateDevices  | `true`                             | No access to physical devices |
| PrivateTmp      | `true`                             | Isolated /tmp namespace       |
| NoNewPrivileges | `true`                             | Cannot gain new privileges    |

**Permissions:**
- Media write: **No** - File uploads handled by Celery workers
- Docker access: **No**
- Network: Yes (serves HTTP via socket)

---

### django-celery.service

**Purpose:** Default Celery worker handling email notifications and referral processing.

| Property         | Value                        |
|------------------|------------------------------|
| Type             | `forking`                    |
| User             | `www-data`                   |
| Group            | `www-data`                   |
| Queues           | `default`, `referrals`       |
| Hostname         | `default@%h`                 |
| RuntimeDirectory | `platform.wafer.space-celery`|
| LogsDirectory    | `platform.wafer.space-celery`|

**Tasks Handled:**
- `send_tos_update_email` - Sends TOS notification emails
- `send_bulk_tos_notifications` - Queues bulk TOS notifications
- Referral-related tasks

**Files Written:**
- `/run/platform.wafer.space-celery/worker.pid` - Process ID file
- `/var/log/platform.wafer.space-celery/worker.log` - Worker logs

**Security Hardening:**
| Setting         | Value                              | Purpose                       |
|-----------------|------------------------------------|-------------------------------|
| ProtectSystem   | `strict`                           | Entire filesystem read-only   |
| ReadOnlyPaths   | `/home/django/platform.wafer.space`| Application code read-only    |
| PrivateDevices  | `true`                             | No access to physical devices |
| PrivateTmp      | `true`                             | Isolated /tmp namespace       |
| NoNewPrivileges | `true`                             | Cannot gain new privileges    |

**Permissions:**
- Media write: **No** - Email tasks don't write files
- Docker access: **No**
- Network: Yes (SMTP for sending emails)

---

### django-celery-downloads.service

**Purpose:** Dedicated worker for downloading large files (up to 100GB) from external URLs.

| Property         | Value                                   |
|------------------|-----------------------------------------|
| Type             | `forking`                               |
| User             | `www-data`                              |
| Group            | `www-data`                              |
| Queues           | `downloads`                             |
| Hostname         | `downloads@%h`                          |
| RuntimeDirectory | `platform.wafer.space-celery-downloads` |
| LogsDirectory    | `platform.wafer.space-celery-downloads` |

**Tasks Handled:**
- `download_project_file` - Downloads files with chunked transfer, resume support, and hash verification

**Files Written:**
- `/run/platform.wafer.space-celery-downloads/worker.pid` - Process ID file
- `/var/log/platform.wafer.space-celery-downloads/worker.log` - Worker logs
- `/home/django/platform.wafer.space/wafer_space/media/**` - Downloaded project files

**Security Hardening:**
| Setting         | Value                              | Purpose                                |
|-----------------|------------------------------------|----------------------------------------|
| ProtectSystem   | `strict`                           | Entire filesystem read-only except allowed |
| ReadOnlyPaths   | `/home/django/platform.wafer.space`| Application code read-only             |
| ReadWritePaths  | `.../wafer_space/media`            | Media directory writable               |
| PrivateDevices  | `true`                             | No access to physical devices          |
| PrivateTmp      | `true`                             | Isolated /tmp namespace                |
| NoNewPrivileges | `true`                             | Cannot gain new privileges             |

**Permissions:**
- Media write: **Yes** - Saves downloaded files via `project_file.file.save()`
- Docker access: **No**
- Network: Yes (downloads from external URLs)

---

### django-celery-manufacturability.service

**Purpose:** Runs manufacturability checks in Docker containers (gf180mcu-precheck).

| Property            | Value                                            |
|---------------------|--------------------------------------------------|
| Type                | `forking`                                        |
| User                | `celery-mfg`                                     |
| Group               | `celery-mfg`                                     |
| Queues              | `manufacturability`                              |
| Hostname            | `manufacturability@%h`                           |
| RuntimeDirectory    | `platform.wafer.space-celery-manufacturability`  |
| LogsDirectory       | `platform.wafer.space-celery-manufacturability`  |
| SupplementaryGroups | `docker`                                         |

**Tasks Handled:**
- `check_project_manufacturability` - Runs Docker containers for design rule checks

**Files Written:**
- `/run/platform.wafer.space-celery-manufacturability/worker.pid` - Process ID file
- `/var/log/platform.wafer.space-celery-manufacturability/worker.log` - Worker logs
- `/home/django/platform.wafer.space/wafer_space/media/**` - Check results:
  - `check.log_file` - Container stdout/stderr logs
  - `check.runs_archive` - Detailed run directory as tar archive

**Security Hardening:**
| Setting             | Value                              | Purpose                       |
|---------------------|------------------------------------|-------------------------------|
| ReadOnlyPaths       | `/home/django/platform.wafer.space`| Application code read-only    |
| ReadWritePaths      | `.../wafer_space/media`            | Media directory writable      |
| PrivateDevices      | `true`                             | No access to physical devices |
| PrivateTmp          | `true`                             | Isolated /tmp namespace       |
| NoNewPrivileges     | `true`                             | Cannot gain new privileges    |
| SupplementaryGroups | `docker`                           | Docker socket access          |

**Permissions:**
- Media write: **Yes** - Saves log files and run archives
- Docker access: **Yes** - Runs precheck containers
- Network: Yes (pulls Docker images)

**Note:** Docker socket access is root-equivalent. The `celery-mfg` user must be in the `docker` group.

---

### django-celery-maintenance.service

**Purpose:** Orchestration tasks that manage other tasks and clean up resources.

| Property            | Value                                      |
|---------------------|--------------------------------------------|
| Type                | `forking`                                  |
| User                | `celery-mfg`                               |
| Group               | `celery-mfg`                               |
| Queues              | `maintenance`                              |
| Hostname            | `maintenance@%h`                           |
| RuntimeDirectory    | `platform.wafer.space-celery-maintenance`  |
| LogsDirectory       | `platform.wafer.space-celery-maintenance`  |
| SupplementaryGroups | `docker`                                   |

**Tasks Handled:**
- `ensure_download_tasks_queued` - Recovers lost download tasks
- `process_manufacturability_check_queue` - Orchestrates check scheduling
- `cleanup_old_task_results` - Removes old Celery TaskResult records
- `cleanup_orphaned_precheck_containers` - Removes orphaned Docker containers

**Files Written:**
- `/run/platform.wafer.space-celery-maintenance/worker.pid` - Process ID file
- `/var/log/platform.wafer.space-celery-maintenance/worker.log` - Worker logs

**Security Hardening:**
| Setting             | Value                              | Purpose                          |
|---------------------|------------------------------------|----------------------------------|
| ReadOnlyPaths       | `/home/django/platform.wafer.space`| Application code read-only       |
| PrivateDevices      | `true`                             | No access to physical devices    |
| PrivateTmp          | `true`                             | Isolated /tmp namespace          |
| NoNewPrivileges     | `true`                             | Cannot gain new privileges       |
| SupplementaryGroups | `docker`                           | Docker socket access for cleanup |

**Permissions:**
- Media write: **No** - Only orchestrates other tasks and cleans up
- Docker access: **Yes** - Stops and removes orphaned containers
- Network: Database only

---

### django-celery-beat.service

**Purpose:** Celery Beat scheduler that triggers periodic tasks.

| Property         | Value                              |
|------------------|----------------------------------- |
| Type             | `simple`                           |
| User             | `www-data`                         |
| Group            | `www-data`                         |
| RuntimeDirectory | `platform.wafer.space-celery-beat` |
| LogsDirectory    | `platform.wafer.space-celery-beat` |

**Files Written:**
- `/run/platform.wafer.space-celery-beat/beat.pid` - Process ID file
- `/run/platform.wafer.space-celery-beat/celerybeat-schedule` - Schedule database
- `/var/log/platform.wafer.space-celery-beat/beat.log` - Scheduler logs

**Security Hardening:**
| Setting         | Value                              | Purpose                       |
|-----------------|------------------------------------|-------------------------------|
| ProtectSystem   | `strict`                           | Entire filesystem read-only   |
| ReadOnlyPaths   | `/home/django/platform.wafer.space`| Application code read-only    |
| PrivateDevices  | `true`                             | No access to physical devices |
| PrivateTmp      | `true`                             | Isolated /tmp namespace       |
| NoNewPrivileges | `true`                             | Cannot gain new privileges    |

**Permissions:**
- Media write: **No** - Only schedules tasks
- Docker access: **No**
- Network: Database only (to queue tasks)

---

## Summary Table

| Service                      | User       | Queue(s)           | Purpose                              | Media | Docker |
|------------------------------|------------|--------------------|--------------------------------------|:-----:|:------:|
| **gunicorn**                 | www-data   | -                  | WSGI server (HTTP requests via socket) | -   | -      |
| **celery**                   | www-data   | default, referrals | Email notifications (TOS updates)    | -     | -      |
| **celery-downloads**         | www-data   | downloads          | File downloads (up to 100GB, chunked)| W     | -      |
| **celery-manufacturability** | celery-mfg | manufacturability  | Design rule checks (Docker containers)| W    | Y      |
| **celery-maintenance**       | celery-mfg | maintenance        | Orchestration and cleanup tasks      | -     | Y      |
| **celery-beat**              | www-data   | -                  | Periodic task scheduler              | -     | -      |

**Legend:** W = Write, Y = Yes, - = None

## Task Assignment

| Queue             | Task                                    | Description                                        |
|-------------------|-----------------------------------------|----------------------------------------------------|
| default           | `send_tos_update_email`                 | Send TOS notification email to user                |
| default           | `send_bulk_tos_notifications`           | Queue bulk TOS notifications                       |
| downloads         | `download_project_file`                 | Download with chunked transfer, resume, hash verification |
| manufacturability | `check_project_manufacturability`       | Run gf180mcu-precheck in Docker container          |
| maintenance       | `ensure_download_tasks_queued`          | Recover lost download tasks                        |
| maintenance       | `process_manufacturability_check_queue` | Orchestrate check scheduling                       |
| maintenance       | `cleanup_old_task_results`              | Remove old Celery TaskResult records               |
| maintenance       | `cleanup_orphaned_precheck_containers`  | Remove orphaned Docker containers                  |

## Code References

This section maps each Celery task to its source code location (where the task is defined) and the callers (where the task is queued).

### Default Queue Tasks

**`send_tos_update_email`**
- **Defined:** `wafer_space/legal/tasks.py:31`
- **Called from:**
  - `wafer_space/legal/tasks.py:199` - `send_bulk_tos_notifications()` queues individual emails
  - `wafer_space/legal/admin.py:251` - Admin action to resend TOS notification

**`send_bulk_tos_notifications`**
- **Defined:** `wafer_space/legal/tasks.py:136`
- **Called from:**
  - Admin actions via Django admin interface

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
- **Called from:**
  - Celery Beat scheduler (periodic task)

**`ensure_download_tasks_queued`**
- **Defined:** `wafer_space/projects/tasks.py:2711`
- **Called from:**
  - Celery Beat scheduler (periodic task)

**`process_manufacturability_check_queue`**
- **Defined:** `wafer_space/projects/tasks.py:3088`
- **Called from:**
  - Celery Beat scheduler (periodic task)

**`cleanup_orphaned_precheck_containers`**
- **Defined:** `wafer_space/projects/tasks.py:3155`
- **Called from:**
  - Celery Beat scheduler (periodic task)

## Detailed Permission Matrix

| Service                  | PrivateDevices | PrivateTmp | NoNewPrivileges | ReadOnlyPaths | ReadWritePaths |
|--------------------------|----------------|------------|-----------------|---------------|----------------|
| gunicorn                 | Yes            | Yes        | Yes             | App code      | -              |
| celery                   | Yes            | Yes        | Yes             | App code      | -              |
| celery-downloads         | Yes            | Yes        | Yes             | App code      | Media          |
| celery-manufacturability | Yes            | Yes        | Yes             | App code      | Media          |
| celery-maintenance       | Yes            | Yes        | Yes             | App code      | -              |
| celery-beat              | Yes            | Yes        | Yes             | App code      | -              |

## Directory Structure

```
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

## Environment Variables

Each service has access to these systemd-provided environment variables:

| Variable             | Source              | Example Value                        |
|----------------------|---------------------|--------------------------------------|
| `$RUNTIME_DIRECTORY` | `RuntimeDirectory=` | `/run/platform.wafer.space-celery`   |
| `$LOGS_DIRECTORY`    | `LogsDirectory=`    | `/var/log/platform.wafer.space-celery`|

These are used in command-line arguments to avoid hardcoding paths.

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

Check service status:
```bash
sudo systemctl status django-gunicorn
sudo systemctl status django-celery
sudo systemctl status django-celery-downloads
sudo systemctl status django-celery-manufacturability
sudo systemctl status django-celery-maintenance
sudo systemctl status django-celery-beat
```

View logs:
```bash
# Via journalctl
sudo journalctl -u django-celery -f

# Via log files
sudo tail -f /var/log/platform.wafer.space-celery/worker.log
```

## User Setup

The `celery-mfg` user must be created and added to the `docker` group:

```bash
sudo useradd -r -s /bin/false celery-mfg
sudo usermod -aG docker celery-mfg
```
