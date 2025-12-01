# Systemd Services Configuration

This document describes the systemd service units for platform.wafer.space, their security configurations, and the principle of least privilege applied to each.

## Services Overview

| Service                      | User       | Queue(s)           | Media | Docker | Security Model                    |
|------------------------------|------------|--------------------|:-----:|:------:|-----------------------------------|
| **gunicorn**                 | www-data   | -                  | -     | -      | No filesystem writes              |
| **celery**                   | www-data   | default, referrals | -     | -      | No filesystem writes              |
| **celery-downloads**         | www-data   | downloads          | W¹    | -      | Write downloads only (append-only)|
| **celery-docker-persistent** | celery-mfg | docker-persistent  | W²    | Y      | Write outputs/logs only           |
| **celery-docker-ephemeral**  | celery-mfg | docker-ephemeral   | -     | Y      | Read-only, Docker cleanup         |
| **celery-beat**              | www-data   | -                  | -     | -      | No filesystem writes              |

**Legend:**
- W = Write access to media directory
- Y = Docker socket access
- \- = None

**Security Notes:**
1. **celery-downloads**: Write-once for downloaded files. Cannot modify existing files.
2. **celery-docker-persistent**: Writes check outputs (logs, archives). Cannot modify downloads.

**Principle of Least Privilege:**
- **gunicorn** and **celery** (default): NO filesystem writes. Database and email only.
- **celery-downloads**: Can ONLY write new download files. Cannot modify/delete existing files.
- **celery-docker-persistent**: Can ONLY write manufacturability check outputs. Cannot modify downloads.
- **celery-docker-ephemeral**: Read-only filesystem access. Docker API for cleanup only.

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

| User       | Services                                                  | Docker Access |
|------------|-----------------------------------------------------------|:-------------:|
| www-data   | gunicorn, celery, celery-downloads, celery-beat           | No            |
| celery-mfg | celery-docker-persistent, celery-docker-ephemeral         | Yes           |

### Filesystem Permissions

The media directory structure must support the principle of least privilege:

```
/mnt/user-files/                     root:root              drwxr-xr-x
├── docker/                          root:docker            drwxr-x---  (Docker daemon storage ONLY)
├── projects/                        root:platform-media    drwxrwxr-x
│   ├── <uuid>/                      root:platform-media    drwxrwxr-x
│   │   ├── downloads/               www-data:platform-media drwxrwxr-x  (celery-downloads writes here)
│   │   └── outputs/                 celery-mfg:platform-media drwxrwxr-x  (celery-docker-persistent writes here)
├── designs/                         root:platform-media    drwxrwxr-x
├── temp/                            root:platform-media    drwxrwxr-x
└── uploads/                         root:platform-media    drwxrwxr-x
```

**Key Requirements:**

1. **docker/** directory:
   - **Owner**: `root:docker`
   - **Permissions**: `drwxr-x---` (750) - ONLY Docker daemon can write
   - **WHY**: Docker storage must not be accessible to www-data or other services

2. **projects/<uuid>/downloads/** subdirectory:
   - **Owner**: `www-data:platform-media`
   - **Permissions**: `drwxrwxr-x` (775) - www-data creates, platform-media group can read
   - **WHY**: celery-downloads (www-data) saves downloaded GDS files

3. **projects/<uuid>/outputs/** subdirectory:
   - **Owner**: `celery-mfg:platform-media`
   - **Permissions**: `drwxrwxr-x` (775) - celery-mfg creates, platform-media group can read
   - **WHY**: celery-docker-persistent saves check logs and outputs

4. **Application code** (`/home/django/platform.wafer.space/`):
   - **Owner**: `django:django`
   - **Permissions**: Read-only for all services (enforced by systemd `ReadOnlyPaths`)
   - **WHY**: Code must never be modified by services

**Setup Script:**

```bash
# Create platform-media group for shared media access
sudo groupadd platform-media

# Add users to platform-media group
sudo usermod -aG platform-media www-data
sudo usermod -aG platform-media celery-mfg

# Set up media directory structure
sudo mkdir -p /mnt/user-files/{docker,projects,designs,temp,uploads}

# Docker storage - root:docker only (NO www-data access)
sudo chown root:docker /mnt/user-files/docker
sudo chmod 750 /mnt/user-files/docker

# Media directories - root:platform-media with group write
sudo chown -R root:platform-media /mnt/user-files/{projects,designs,temp,uploads}
sudo chmod -R 775 /mnt/user-files/{projects,designs,temp,uploads}

# Set setgid bit so new files inherit group
sudo chmod g+s /mnt/user-files/{projects,designs,temp,uploads}

# Verify permissions
ls -la /mnt/user-files/
```

**User Group Memberships:**

| User       | Primary Group | Supplementary Groups    | Purpose                               |
|------------|---------------|-------------------------|---------------------------------------|
| django     | django        | -                       | Owns application code (read-only)     |
| www-data   | www-data      | platform-media          | Web server + write downloads          |
| celery-mfg | celery-mfg    | docker, platform-media  | Docker access + write check outputs   |

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

### Create Required Users and Groups

```bash
# Create platform-media group for shared media directory access
sudo groupadd platform-media

# Create celery-mfg system user
sudo useradd -r -s /bin/false celery-mfg

# Add celery-mfg to required groups
sudo usermod -aG docker celery-mfg           # Docker socket access
sudo usermod -aG platform-media celery-mfg   # Media directory write access

# Add www-data to platform-media group (for celery-downloads)
sudo usermod -aG platform-media www-data

# Verify group memberships
groups celery-mfg
# Expected output: celery-mfg : celery-mfg docker platform-media

groups www-data
# Expected output: www-data : www-data platform-media
```

**Important**: After adding users to groups, restart all services for group membership to take effect:

```bash
sudo systemctl restart django-gunicorn
sudo systemctl restart django-celery
sudo systemctl restart django-celery-downloads
sudo systemctl restart django-celery-docker-persistent
sudo systemctl restart django-celery-docker-ephemeral
sudo systemctl restart django-celery-beat
```

### Permission Summary

| User/Group | Purpose                              | Should NOT Have Access To    |
|------------|--------------------------------------|------------------------------|
| django     | Application code owner               | Media files, Docker          |
| www-data   | Web server + download files          | Application code, Docker     |
| celery-mfg | Run Docker checks + write outputs    | Application code, downloads  |
| platform-media | Shared group for media directory | Application code             |

See the [Filesystem Permissions](#filesystem-permissions) section above for complete media directory setup instructions.
