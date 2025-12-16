# Deployment Scripts

This directory contains automated deployment scripts for **both** platform.wafer.space (production) and test-platform.wafer.space (staging).

## 🔄 Environment Auto-Detection

**All deployment scripts automatically detect which environment they're running in based on the server hostname.**

- **Hostname contains "test-platform"** → Staging environment (`config.settings.stage`)
- **Hostname contains "platform"** → Production environment (`config.settings.prod`)

The scripts use **identical names** for everything (application directory, database, logs, etc.) on both servers. Only 5 environment-specific values differ:

1. Django settings module (`config.settings.stage` vs `config.settings.prod`)
2. Secrets repository (`test-platform.wafer.space-secrets` vs `platform.wafer.space-secrets`)
3. Environment template (`.env.stage.template` vs `.env.prod.template`)
4. SSL domain (`test-platform.wafer.space` vs `platform.wafer.space`)
5. Nginx server_name directive

**No manual configuration needed** - just run the same scripts on both servers.

## 📖 Full Documentation

**See [docs/production_deployment.md](../docs/production_deployment.md) for complete deployment guide.**

The full documentation includes:
- Step-by-step deployment instructions
- Detailed script explanations
- Environment configuration guide
- Security features
- Troubleshooting
- Maintenance operations

## Directory Structure

```
deployment/
├── scripts/          # Setup and maintenance scripts
│   ├── detect-environment.sh      # Auto-detect staging vs production
│   ├── 01-setup-users.sh
│   ├── 02-install-dependencies.sh
│   ├── 02a-setup-secrets.sh
│   ├── 03-setup-database.sh
│   ├── 03a-update-env-secrets.sh
│   ├── 04-setup-permissions.sh
│   ├── 05-setup-ssl.sh
│   ├── 05a-expand-ssl-cert.sh
│   ├── backup.sh
│   └── update.sh
├── systemd/          # Systemd service files (same on both servers)
│   ├── django-gunicorn.service
│   ├── django-celery-none-ro-default.service
│   ├── django-celery-none-ro-checks-orch.service
│   ├── django-celery-none-ro-beat.service
│   ├── django-celery-mail-ro-email.service
│   ├── django-celery-http-rw-downloads.service
│   ├── django-celery-dock-ro-checks-fast.service
│   ├── django-celery-dock-ro-checks-slow.service
│   ├── django-celery-dock-rw-checks-save.service
│   └── install.sh
├── nginx/            # Nginx configuration (auto-selected by environment)
│   ├── platform.wafer.space.conf        # Production config
│   ├── test-platform.wafer.space.conf   # Staging config
│   └── install.sh
└── README.md         # This file
```

## Quick Reference

### Setup Scripts (run in order)

1. **`01-setup-users.sh`** - Create django user and application directories
2. **`02-install-dependencies.sh`** - Install system packages (PostgreSQL, Nginx, etc.)
3. **`02a-setup-secrets.sh`** - Clone secrets repository from GitHub
4. **`03-setup-database.sh`** - Setup PostgreSQL database and auto-generate .env file
5. **`04-setup-permissions.sh`** - Set proper file permissions (privilege separation)
6. **`05-setup-ssl.sh`** - Obtain Let's Encrypt SSL certificate

### Maintenance Scripts

- **`backup.sh`** - Backup PostgreSQL database (cron: `0 2 * * *`)
- **`update.sh`** - Update application code and restart services
- **`03a-update-env-secrets.sh`** - Update .env file with latest secrets (run after secrets change)

### Installing Services

```bash
# Install systemd services
cd systemd && sudo ./install.sh

# Install nginx configuration
cd nginx && sudo ./install.sh
```

## Celery Worker Architecture

The platform uses **9 separate Celery workers** following a queue naming convention: `{network}:{filesystem}:{purpose}`.

**See [docs/systemd-services.md](../docs/systemd-services.md) for complete queue naming, task mapping, and security configuration.**

### Worker Overview

| Service | User | Queue | Purpose |
|---------|------|-------|---------|
| `django-celery-none-ro-default` | www-data | `none:ro:default` | Maintenance tasks |
| `django-celery-none-ro-checks-orch` | www-data | `none:ro:checks-orch` | Check orchestration |
| `django-celery-none-ro-beat` | www-data | N/A | Celery Beat scheduler |
| `django-celery-mail-ro-email` | www-data | `mail:ro:email` | Email via Mailgun |
| `django-celery-http-rw-downloads` | www-data | `http:rw:downloads` | File downloads |
| `django-celery-dock-ro-checks-fast` | celery-mfg | `dock:ro:checks-fast` | Fast Docker ops |
| `django-celery-dock-ro-checks-slow` | celery-mfg | `dock:ro:checks-slow` | Slow Docker ops |
| `django-celery-dock-rw-checks-save` | celery-mfg | `dock:rw:checks-save` | Save check results |

### Manufacturability Checking

Docker-based manufacturability checks use **remote Docker servers** over TCP (not local sockets). The `dock:*` workers:

1. Run as `celery-mfg` user (not `www-data`)
2. Connect to remote Docker servers via `IPAddressAllow` restrictions
3. Are isolated from web traffic by systemd security settings

**See [docs/systemd-services.md](../docs/systemd-services.md#docker-server-configuration) for Docker server IPs and configuration.**

## Architecture

- **Privilege Separation**: `django` user owns code, `www-data` runs web services, `celery-mfg` runs Docker workers
- **Security**: File permissions 750/640, systemd hardening (IPAddressDeny, ProtectSystem), HTTPS enforced
- **Stack**: Django 5.2+ → Gunicorn → Nginx, PostgreSQL 17+, Celery (9 workers with queue isolation)
- **Docker**: Remote Docker servers over TCP, restricted to `celery-mfg` user with IP filtering

**Detailed documentation:**

- [docs/systemd-services.md](../docs/systemd-services.md) - Complete worker configuration, queue naming, task mapping
- [docs/production_deployment.md](../docs/production_deployment.md) - Step-by-step deployment guide
