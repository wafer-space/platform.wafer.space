# Deployment Scripts

This directory contains automated deployment scripts for platform.wafer.space.

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
│   ├── 01-setup-users.sh
│   ├── 02-install-dependencies.sh
│   ├── 03-setup-database.sh
│   ├── 04-setup-permissions.sh
│   ├── 05-setup-ssl.sh
│   ├── backup.sh
│   └── update.sh
├── systemd/          # Systemd service files
│   ├── django-gunicorn.service
│   ├── django-celery.service
│   ├── django-celery-beat.service
│   └── install.sh
├── nginx/            # Nginx configuration
│   ├── platform.wafer.space.conf
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
