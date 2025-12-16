# Systemd Services Configuration

This document describes the systemd service units for platform.wafer.space, their security configurations, and the principle of least privilege applied to each.

## Queue Naming Convention

Queue names follow the pattern: `{network}:{fs}:{purpose}`

### Network Access (`{network}`)

| Value  | Description                         | Systemd Restriction             |
|--------|-------------------------------------|---------------------------------|
| `none` | Database only (via Unix socket)     | `IPAddressDeny=any`             |
| `mail` | Mailgun API (HTTPS)                 | None (dynamic API IPs)          |
| `http` | HTTP/HTTPS traffic                  | None (arbitrary URLs)           |
| `dock` | Docker server IPs only              | `IPAddressAllow` + `IPAddressDeny=any` |

**Note:** PostgreSQL connections via Unix socket (`/var/run/postgresql/.s.PGSQL.5432`) are not affected by `IPAddressDeny` since it only filters IP traffic (AF_INET/AF_INET6), not Unix sockets (AF_UNIX).

### Filesystem Access (`{fs}`)

| Value | Description                        | Systemd Restriction             |
|-------|------------------------------------|---------------------------------|
| `ro`  | Read-only application access       | `ReadOnlyPaths=...`             |
| `rw`  | Media directory read/write         | `ReadWritePaths=.../media`      |

**Note:** See [issue #210](https://github.com/wafer-space/platform.wafer.space/issues/210) for future granularity between "no media access" and "read-only media access".

### Port Filtering (Future)

Systemd's `IPAddressAllow`/`IPAddressDeny` do not support port filtering. Port-level restrictions would require iptables/nftables - tracked in [issue #209](https://github.com/wafer-space/platform.wafer.space/issues/209).

## Services Overview

| Service                             | User       | Queue                  | Network | FS | Purpose                        |
|-------------------------------------|------------|------------------------|---------|----|---------------------------------|
| **gunicorn**                        | www-data   | -                      | -       | ro | Web application                 |
| **celery-none-ro-default**          | www-data   | `none:ro:default`      | none    | ro | Catch-all for unassigned tasks  |
| **celery-none-ro-checks-orch**      | www-data   | `none:ro:checks-orch`  | none    | ro | Check orchestration (DB only)   |
| **celery-none-ro-beat**             | www-data   | `none:ro:beat`         | none    | ro | Celery Beat scheduler           |
| **celery-mail-ro-email**            | www-data   | `mail:ro:email`        | mail    | ro | Email via Mailgun               |
| **celery-http-ro-metadata**         | www-data   | `http:ro:metadata`     | http    | ro | GHCR metadata fetch             |
| **celery-http-rw-downloads**        | www-data   | `http:rw:downloads`    | http    | rw | File downloads                  |
| **celery-dock-ro-checks-fast**      | celery-mfg | `dock:ro:checks-fast`  | dock    | ro | Fast Docker ops (<30s)          |
| **celery-dock-ro-checks-slow**      | celery-mfg | `dock:ro:checks-slow`  | dock    | ro | Slow Docker ops (minutes)       |
| **celery-dock-rw-checks-save**      | celery-mfg | `dock:rw:checks-save`  | dock    | rw | Docker ops with media write     |

## Task to Queue Mapping

| Queue                  | Task                              | Description                                |
|------------------------|-----------------------------------|--------------------------------------------|
| `none:ro:checks-orch`  | `checks_create`                   | Create new checks from ready files         |
| `none:ro:checks-orch`  | `checks_pending`                  | Transition PENDING → DISPATCHING           |
| `none:ro:checks-orch`  | `checks_dispatching`              | Poll DISPATCHING checks                    |
| `none:ro:checks-orch`  | `checks_starting`                 | Poll STARTING checks                       |
| `none:ro:checks-orch`  | `checks_running`                  | Poll RUNNING checks                        |
| `none:ro:checks-orch`  | `checks_analyzing`                | Poll ANALYZING checks                      |
| `none:ro:checks-orch`  | `checks_cancelling`               | Poll CANCELLING checks                     |
| `none:ro:checks-orch`  | `checks_retry`                    | Retry ERROR checks within limit            |
| `none:ro:checks-orch`  | `checks_cleanup_stale_files`      | Cleanup stale files                        |
| `none:ro:checks-orch`  | `checks_cleanup_stale_pending_tasks` | Cleanup stale pending tasks             |
| `none:ro:default`      | `cleanup_old_task_results`        | Remove old Celery TaskResult records       |
| `none:ro:default`      | `ensure_download_tasks_queued`    | Recover lost download tasks                |
| `mail:ro:email`        | `send_tos_update_email`           | Send TOS notification email                |
| `mail:ro:email`        | `send_bulk_tos_notifications`     | Queue bulk TOS notifications               |
| `http:ro:metadata`     | `do_revision_fetch`               | Fetch precheck image metadata from GHCR    |
| `http:rw:downloads`    | `download_project_file`           | Chunked download with resume and hashing   |
| `dock:ro:checks-fast`  | `do_starting`                     | Start Docker container                     |
| `dock:ro:checks-fast`  | `do_running`                      | Poll running container                     |
| `dock:ro:checks-fast`  | `checks_cleanup_orphaned_docker`  | Remove orphaned Docker containers          |
| `dock:ro:checks-slow`  | `do_dispatching`                  | Create and configure Docker container      |
| `dock:rw:checks-save`  | `do_analyzing`                    | Extract results and save to media          |

## Docker Server Configuration

The `dock:*` queues connect to remote Docker servers via TCP (not local socket). These are the allowed Docker server IPs:

| IP           | Hostname | Environment           |
|--------------|----------|-----------------------|
| 10.3.27.44   | harken   | Production            |
| 10.4.27.44   | micky    | Staging/Production    |
| 10.3.27.45   | buddy    | Reserved              |
| 10.4.27.45   | doc      | Reserved              |

Docker API ports: 2375 (unencrypted), 2376 (TLS)

**Important:** The `dock:*` services use `IPAddressAllow` to restrict network access to only these Docker server IPs, then `IPAddressDeny=any` to block all other IP traffic.

---

## Architecture Overview

```text
                                       +-----------------+
                                       |    PostgreSQL   |
                                       | (Unix Socket)   |
                                       +-----------------+
                                              |
    +-----------------------------------------+------------------------------------------+
    |              |              |                |              |              |       |
+---v---+   +------v------+  +----v----+  +--------v--------+  +--v---+  +------v------+  +--------v--------+
|Gunicorn|  |none:ro:*    |  |mail:ro: |  |http:ro:         |  |http: |  |dock:ro:*    |  |dock:rw:         |
|(Web)  |  |(checks-orch,|  |email    |  |metadata         |  |rw:   |  |(fast,slow)  |  |checks-save      |
|       |  | default,beat)|  |         |  |                 |  |down- |  |             |  |                 |
+-------+  +-------------+  +---------+  +--------+--------+  |loads |  +------+------+  +--------+--------+
                                                  |           +--+---+         |                  |
                                                  v              |             v                  v
                                             +--------+          v        +----------+       +--------+
                                             | GHCR   |     +--------+    | Docker   |       | Media  |
                                             | (Read) |     | Media  |    | Servers  |       | (Write)|
                                             +--------+     | (Write)|    +----------+       +--------+
                                                            +--------+
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

| User       | Services                                                    | Docker Access |
|------------|-------------------------------------------------------------|:-------------:|
| www-data   | gunicorn, none:ro:*, mail:ro:*, http:rw:*                   | No            |
| celery-mfg | dock:ro:*, dock:rw:*                                        | Remote only   |

**Note:** The `celery-mfg` user no longer needs local Docker socket access. All Docker operations use remote API over TCP.

### Environment Variables

Systemd provides these variables to all services:

- `$RUNTIME_DIRECTORY` - e.g., `/run/platform.wafer.space-celery-none-ro-default`
- `$LOGS_DIRECTORY` - e.g., `/var/log/platform.wafer.space-celery-none-ro-default`

---

## Service Details

### django-gunicorn.service

WSGI application server serving HTTP requests via Unix socket.

- **Type:** notify
- **Network:** None (reverse proxy via Unix socket)
- **ProtectSystem:** strict

**Files:**
- `$RUNTIME_DIRECTORY/gunicorn.sock` - Unix socket for nginx
- `$LOGS_DIRECTORY/access.log`, `$LOGS_DIRECTORY/error.log`

---

### django-celery-none-ro-default.service

Catch-all worker for unassigned tasks and maintenance tasks.

- **Type:** forking
- **Queue:** `none:ro:default`
- **Hostname:** none-ro-default@%h
- **Network:** `IPAddressDeny=any` (DB via Unix socket only)
- **ProtectSystem:** strict

**Tasks:**

- `cleanup_old_task_results` - Remove old Celery TaskResult records (periodic)
- `ensure_download_tasks_queued` - Recover lost download tasks (periodic)

---

### django-celery-none-ro-checks-orch.service

Orchestration worker for manufacturability check state machine. All tasks are DB-only operations that poll checks in specific states and queue work tasks.

- **Type:** forking
- **Queue:** `none:ro:checks-orch`
- **Hostname:** none-ro-checks-orch@%h
- **Network:** `IPAddressDeny=any` (DB via Unix socket only)
- **ProtectSystem:** strict

**Tasks:**

- `checks_create` - Create checks from verified files
- `checks_pending` - Transition PENDING → DISPATCHING
- `checks_dispatching` - Poll DISPATCHING, queue `do_dispatching`
- `checks_starting` - Poll STARTING, queue `do_starting`
- `checks_running` - Poll RUNNING, queue `do_running`
- `checks_analyzing` - Poll ANALYZING, queue `do_analyzing`
- `checks_cancelling` - Poll CANCELLING, handle cancellation
- `checks_retry` - Retry ERROR checks within limit
- `checks_cleanup_stale_files` - Cleanup stale files
- `checks_cleanup_stale_pending_tasks` - Cleanup stale pending tasks

---

### django-celery-none-ro-beat.service

Celery Beat scheduler that triggers periodic tasks.

- **Type:** simple
- **Queue:** N/A (scheduler, not worker)
- **Network:** `IPAddressDeny=any` (DB via Unix socket only)
- **ProtectSystem:** strict

**Files:**
- `$RUNTIME_DIRECTORY/beat.pid`
- `$RUNTIME_DIRECTORY/celerybeat-schedule` - Schedule database
- `$LOGS_DIRECTORY/beat.log`

---

### django-celery-mail-ro-email.service

Worker for email tasks via Mailgun API.

- **Type:** forking
- **Queue:** `mail:ro:email`
- **Hostname:** mail-ro-email@%h
- **Network:** No restrictions (Mailgun doesn't publish static API IPs)
- **ProtectSystem:** strict

**Tasks:**

- `send_tos_update_email` - Send TOS notification email to user
- `send_bulk_tos_notifications` - Queue bulk TOS notifications

---

### django-celery-http-ro-metadata.service

Worker for fetching precheck container image metadata from GitHub Container Registry (GHCR).

- **Type:** forking
- **Queue:** `http:ro:metadata`
- **Hostname:** http-ro-metadata@%h
- **Network:** No restrictions (HTTPS to ghcr.io)
- **ProtectSystem:** strict

**Tasks:**

- `do_revision_fetch` - Fetch image metadata (version, commit SHA, labels) from GHCR for a given digest

---

### django-celery-http-rw-downloads.service

Worker for downloading large files (up to 100GB) from external URLs.

- **Type:** forking
- **Queue:** `http:rw:downloads`
- **Hostname:** http-rw-downloads@%h
- **Network:** No restrictions (downloads from arbitrary URLs)
- **ReadWritePaths:** `.../wafer_space/media` (for saving downloaded files)

**Tasks:**

- `download_project_file` - Chunked transfer with resume support and hash verification

---

### django-celery-dock-ro-checks-fast.service

Fast Docker operations (<30s) - container start, status polling, cleanup.

- **Type:** forking
- **User:** celery-mfg
- **Queue:** `dock:ro:checks-fast`
- **Hostname:** dock-ro-checks-fast@%h
- **Network:** `IPAddressAllow=<Docker IPs>` + `IPAddressDeny=any`
- **ProtectSystem:** strict

**Tasks:**

- `do_starting` - Start Docker container (STARTING state)
- `do_running` - Poll running container (RUNNING state)
- `checks_cleanup_orphaned_docker` - Remove orphaned Docker containers

---

### django-celery-dock-ro-checks-slow.service

Slow Docker operations (minutes) - container creation and configuration.

- **Type:** forking
- **User:** celery-mfg
- **Queue:** `dock:ro:checks-slow`
- **Hostname:** dock-ro-checks-slow@%h
- **Network:** `IPAddressAllow=<Docker IPs>` + `IPAddressDeny=any`
- **ProtectSystem:** strict

**Tasks:**

- `do_dispatching` - Create and configure Docker container (DISPATCHING state)

---

### django-celery-dock-rw-checks-save.service

Docker operations that save results to media directory.

- **Type:** forking
- **User:** celery-mfg
- **Queue:** `dock:rw:checks-save`
- **Hostname:** dock-rw-checks-save@%h
- **Network:** `IPAddressAllow=<Docker IPs>` + `IPAddressDeny=any`
- **ReadWritePaths:** `.../wafer_space/media` (for saving check results)

**Tasks:**

- `do_analyzing` - Extract results from container and save to media (ANALYZING state)

---

## Installation

```bash
cd deployment/systemd
sudo ./install.sh
```

This will:
1. Stop and remove old services (migration)
2. Copy new service files to `/etc/systemd/system/`
3. Reload systemd daemon
4. Enable all services
5. Restart all services

## Monitoring

```bash
# Check status of all services
sudo systemctl status django-gunicorn
sudo systemctl status django-celery-none-ro-default
sudo systemctl status django-celery-none-ro-checks-orch
sudo systemctl status django-celery-none-ro-beat
sudo systemctl status django-celery-mail-ro-email
sudo systemctl status django-celery-http-ro-metadata
sudo systemctl status django-celery-http-rw-downloads
sudo systemctl status django-celery-dock-ro-checks-fast
sudo systemctl status django-celery-dock-ro-checks-slow
sudo systemctl status django-celery-dock-rw-checks-save

# View logs via journalctl
sudo journalctl -u django-celery-none-ro-checks-orch -f

# View logs via log files
sudo tail -f /var/log/platform.wafer.space-celery-*/worker.log
```

## User Setup

### Create Required Users and Groups

```bash
# Create platform-media group for shared media directory access
sudo groupadd platform-media

# Create celery-mfg system user
sudo useradd -r -s /bin/false celery-mfg

# Add celery-mfg to platform-media group (for media directory write)
# Note: No longer needs docker group - uses remote Docker API
sudo usermod -aG platform-media celery-mfg

# Add www-data to platform-media group (for downloads)
sudo usermod -aG platform-media www-data

# Verify group memberships
groups celery-mfg
# Expected output: celery-mfg : celery-mfg platform-media

groups www-data
# Expected output: www-data : www-data platform-media
```

**Important**: After adding users to groups, restart all services for group membership to take effect.

### Permission Summary

| User/Group | Purpose                              | Should NOT Have Access To    |
|------------|--------------------------------------|------------------------------|
| django     | Application code owner               | Media files                  |
| www-data   | Web server + download files          | Application code             |
| celery-mfg | Run Docker checks + write outputs    | Application code, downloads  |
| platform-media | Shared group for media directory | Application code             |

## Migration from Old Services

The install script automatically handles migration from old service names:

| Old Service                      | New Service                        |
|----------------------------------|------------------------------------|
| django-celery.service            | django-celery-none-ro-default.service |
| django-celery-beat.service       | django-celery-none-ro-beat.service |
| django-celery-downloads.service  | django-celery-http-rw-downloads.service |
| django-celery-docker-ephemeral.service | django-celery-dock-ro-checks-fast.service |
| django-celery-docker-persistent.service | django-celery-dock-rw-checks-save.service |

New services added:
- `django-celery-none-ro-checks-orch.service` (checks orchestration)
- `django-celery-mail-ro-email.service` (email tasks)
- `django-celery-dock-ro-checks-slow.service` (slow Docker operations)

---

## Related Documentation

- [Celery Architecture](celery_architecture.md) - Task decorators, state machine, queue naming rationale
- [Celery Tasks Reference](celery_tasks_reference.md) - Complete task listing with queues and retry config
- [Settings Catalog](settings.md) - CELERY_BEAT_SCHEDULE and other Celery settings
