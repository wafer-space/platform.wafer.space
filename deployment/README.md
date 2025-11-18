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
│   ├── django-celery.service
│   ├── django-celery-beat.service
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

## Architecture

- **Privilege Separation**: `django` user owns code, `www-data` runs services
- **Security**: File permissions 750/640, systemd hardening, HTTPS enforced
- **Stack**: Django 5.2+ → Gunicorn → Nginx, PostgreSQL 17+, Celery workers
