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

| Property | Value |
|----------|-------|
| Type | `notify` |
| User | `www-data` |
| Group | `www-data` |
| RuntimeDirectory | `platform.wafer.space-gunicorn` |
| LogsDirectory | `platform.wafer.space-gunicorn` |

**Files Written:**
- `/run/platform.wafer.space-gunicorn/gunicorn.sock` - Unix socket for nginx
- `/var/log/platform.wafer.space-gunicorn/access.log` - HTTP access logs
- `/var/log/platform.wafer.space-gunicorn/error.log` - Application errors

**Security Hardening:**
| Setting | Value | Purpose |
|---------|-------|---------|
| ProtectSystem | `strict` | Entire filesystem read-only |
| ReadOnlyPaths | `/home/django/platform.wafer.space` | Application code read-only |
| PrivateDevices | `true` | No access to physical devices |
| PrivateTmp | `true` | Isolated /tmp namespace |
| NoNewPrivileges | `true` | Cannot gain new privileges |

**Permissions:**
- Media write: **No** - File uploads handled by Celery workers
- Docker access: **No**
- Network: Yes (serves HTTP via socket)

---

### django-celery.service

**Purpose:** Default Celery worker handling email notifications and referral processing.

| Property | Value |
|----------|-------|
| Type | `forking` |
| User | `www-data` |
| Group | `www-data` |
| Queues | `default`, `referrals` |
| Hostname | `default@%h` |
| RuntimeDirectory | `platform.wafer.space-celery` |
| LogsDirectory | `platform.wafer.space-celery` |

**Tasks Handled:**
- `send_tos_update_email` - Sends TOS notification emails
- `send_bulk_tos_notifications` - Queues bulk TOS notifications
- Referral-related tasks

**Files Written:**
- `/run/platform.wafer.space-celery/worker.pid` - Process ID file
- `/var/log/platform.wafer.space-celery/worker.log` - Worker logs

**Security Hardening:**
| Setting | Value | Purpose |
|---------|-------|---------|
| ProtectSystem | `strict` | Entire filesystem read-only |
| ReadOnlyPaths | `/home/django/platform.wafer.space` | Application code read-only |
| PrivateDevices | `true` | No access to physical devices |
| PrivateTmp | `true` | Isolated /tmp namespace |
| NoNewPrivileges | `true` | Cannot gain new privileges |

**Permissions:**
- Media write: **No** - Email tasks don't write files
- Docker access: **No**
- Network: Yes (SMTP for sending emails)

---

### django-celery-downloads.service

**Purpose:** Dedicated worker for downloading large files (up to 100GB) from external URLs.

| Property | Value |
|----------|-------|
| Type | `forking` |
| User | `www-data` |
| Group | `www-data` |
| Queues | `downloads` |
| Hostname | `downloads@%h` |
| RuntimeDirectory | `platform.wafer.space-celery-downloads` |
| LogsDirectory | `platform.wafer.space-celery-downloads` |

**Tasks Handled:**
- `download_project_file` - Downloads files with chunked transfer, resume support, and hash verification

**Files Written:**
- `/run/platform.wafer.space-celery-downloads/worker.pid` - Process ID file
- `/var/log/platform.wafer.space-celery-downloads/worker.log` - Worker logs
- `/home/django/platform.wafer.space/wafer_space/media/**` - Downloaded project files

**Security Hardening:**
| Setting | Value | Purpose |
|---------|-------|---------|
| ProtectSystem | `strict` | Entire filesystem read-only except allowed |
| ReadOnlyPaths | `/home/django/platform.wafer.space` | Application code read-only |
| ReadWritePaths | `.../wafer_space/media` | Media directory writable |
| PrivateDevices | `true` | No access to physical devices |
| PrivateTmp | `true` | Isolated /tmp namespace |
| NoNewPrivileges | `true` | Cannot gain new privileges |

**Permissions:**
- Media write: **Yes** - Saves downloaded files via `project_file.file.save()`
- Docker access: **No**
- Network: Yes (downloads from external URLs)

---

### django-celery-manufacturability.service

**Purpose:** Runs manufacturability checks in Docker containers (gf180mcu-precheck).

| Property | Value |
|----------|-------|
| Type | `forking` |
| User | `celery-mfg` |
| Group | `celery-mfg` |
| Queues | `manufacturability` |
| Hostname | `manufacturability@%h` |
| RuntimeDirectory | `platform.wafer.space-celery-manufacturability` |
| LogsDirectory | `platform.wafer.space-celery-manufacturability` |
| SupplementaryGroups | `docker` |

**Tasks Handled:**
- `check_project_manufacturability` - Runs Docker containers for design rule checks

**Files Written:**
- `/run/platform.wafer.space-celery-manufacturability/worker.pid` - Process ID file
- `/var/log/platform.wafer.space-celery-manufacturability/worker.log` - Worker logs
- `/home/django/platform.wafer.space/wafer_space/media/**` - Check results:
  - `check.log_file` - Container stdout/stderr logs
  - `check.runs_archive` - Detailed run directory as tar archive

**Security Hardening:**
| Setting | Value | Purpose |
|---------|-------|---------|
| ReadOnlyPaths | `/home/django/platform.wafer.space` | Application code read-only |
| ReadWritePaths | `.../wafer_space/media` | Media directory writable |
| PrivateTmp | `true` | Isolated /tmp namespace |
| NoNewPrivileges | `true` | Cannot gain new privileges |
| SupplementaryGroups | `docker` | Docker socket access |

**Permissions:**
- Media write: **Yes** - Saves log files and run archives
- Docker access: **Yes** - Runs precheck containers
- Network: Yes (pulls Docker images)

**Note:** Docker socket access is root-equivalent. The `celery-mfg` user must be in the `docker` group.

---

### django-celery-maintenance.service

**Purpose:** Orchestration tasks that manage other tasks and clean up resources.

| Property | Value |
|----------|-------|
| Type | `forking` |
| User | `celery-mfg` |
| Group | `celery-mfg` |
| Queues | `maintenance` |
| Hostname | `maintenance@%h` |
| RuntimeDirectory | `platform.wafer.space-celery-maintenance` |
| LogsDirectory | `platform.wafer.space-celery-maintenance` |
| SupplementaryGroups | `docker` |

**Tasks Handled:**
- `ensure_download_tasks_queued` - Recovers lost download tasks
- `process_manufacturability_check_queue` - Orchestrates check scheduling
- `cleanup_old_task_results` - Removes old Celery TaskResult records
- `cleanup_orphaned_precheck_containers` - Removes orphaned Docker containers

**Files Written:**
- `/run/platform.wafer.space-celery-maintenance/worker.pid` - Process ID file
- `/var/log/platform.wafer.space-celery-maintenance/worker.log` - Worker logs

**Security Hardening:**
| Setting | Value | Purpose |
|---------|-------|---------|
| ReadOnlyPaths | `/home/django/platform.wafer.space` | Application code read-only |
| PrivateTmp | `true` | Isolated /tmp namespace |
| NoNewPrivileges | `true` | Cannot gain new privileges |
| SupplementaryGroups | `docker` | Docker socket access for cleanup |

**Permissions:**
- Media write: **No** - Only orchestrates other tasks and cleans up
- Docker access: **Yes** - Stops and removes orphaned containers
- Network: Database only

---

### django-celery-beat.service

**Purpose:** Celery Beat scheduler that triggers periodic tasks.

| Property | Value |
|----------|-------|
| Type | `simple` |
| User | `www-data` |
| Group | `www-data` |
| RuntimeDirectory | `platform.wafer.space-celery-beat` |
| LogsDirectory | `platform.wafer.space-celery-beat` |

**Files Written:**
- `/run/platform.wafer.space-celery-beat/beat.pid` - Process ID file
- `/run/platform.wafer.space-celery-beat/celerybeat-schedule` - Schedule database
- `/var/log/platform.wafer.space-celery-beat/beat.log` - Scheduler logs

**Security Hardening:**
| Setting | Value | Purpose |
|---------|-------|---------|
| ProtectSystem | `strict` | Entire filesystem read-only |
| ReadOnlyPaths | `/home/django/platform.wafer.space` | Application code read-only |
| PrivateDevices | `true` | No access to physical devices |
| PrivateTmp | `true` | Isolated /tmp namespace |
| NoNewPrivileges | `true` | Cannot gain new privileges |

**Permissions:**
- Media write: **No** - Only schedules tasks
- Docker access: **No**
- Network: Database only (to queue tasks)

---

## Permission Matrix

| Service | User | Media | Docker | ProtectSystem |
|---------|------|-------|--------|---------------|
| gunicorn | www-data | No | No | strict |
| celery (default) | www-data | No | No | strict |
| celery-downloads | www-data | **Yes** | No | strict |
| celery-manufacturability | celery-mfg | **Yes** | **Yes** | - |
| celery-maintenance | celery-mfg | No | **Yes** | - |
| celery-beat | www-data | No | No | strict |

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

| Variable | Source | Example Value |
|----------|--------|---------------|
| `$RUNTIME_DIRECTORY` | `RuntimeDirectory=` | `/run/platform.wafer.space-celery` |
| `$LOGS_DIRECTORY` | `LogsDirectory=` | `/var/log/platform.wafer.space-celery` |

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
