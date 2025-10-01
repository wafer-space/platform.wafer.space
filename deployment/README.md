# Deployment Scripts

This directory contains automated deployment scripts for platform.wafer.space.

## Directory Structure

```
deployment/
├── scripts/          # Setup and maintenance scripts
├── systemd/          # Systemd service files
├── nginx/            # Nginx configuration
└── README.md         # This file
```

## Quick Start

For a fresh Debian 12 server, run scripts in order:

```bash
# 1. Setup users (privilege separation)
sudo ./scripts/01-setup-users.sh

# 2. Install system dependencies
sudo ./scripts/02-install-dependencies.sh

# 3. Setup PostgreSQL database
sudo ./scripts/03-setup-database.sh

# 4. Clone repository as django user
sudo -u django -i
cd /home/django
git clone https://github.com/wafer-space/platform.wafer.space.git platform.wafer.space
cd platform.wafer.space

# 5. Install uv and setup Python environment
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env
make venv

# 6. Edit .env file (auto-created by database setup script)
# Configure secrets: DJANGO_SECRET_KEY, MAILGUN_API_KEY, OAuth credentials
nano .env

# 7. Configure production settings
echo 'export DJANGO_SETTINGS_MODULE=config.settings.production' >> ~/.bashrc
source ~/.bashrc

# 8. Run migrations
make migrate
make createsuperuser

# 9. Collect static files
make collectstatic

# 10. Set permissions (exit django user, back to root/sudo)
exit
sudo ./scripts/04-setup-permissions.sh /home/django/platform.wafer.space

# 11. Install systemd services
cd systemd
sudo ./install.sh

# 12. Install nginx configuration
cd ../nginx
sudo ./install.sh

# 13. Setup SSL certificate
cd ../scripts
sudo ./05-setup-ssl.sh platform.wafer.space bot@wafer.space

# 14. Start services
sudo systemctl start django-gunicorn.service
sudo systemctl start django-celery.service
```

## Scripts Reference

### Setup Scripts

**`01-setup-users.sh`**
- Creates `django` user (code owner, deployment)
- Verifies `www-data` user exists (service runner)
- Creates application directories

**`02-install-dependencies.sh`**
- Installs system packages
- PostgreSQL, Nginx, Python build dependencies
- Security tools (UFW)

**`03-setup-database.sh`**
- Creates PostgreSQL database and user
- Configures database settings
- Tests connection
- Prompts for database password

**`04-setup-permissions.sh [APP_DIR]`**
- Sets file ownership: `django:www-data`
- Sets permissions: 750/640 (privilege separation)
- Configures media directory for www-data

**`05-setup-ssl.sh [DOMAIN] [EMAIL]`**
- Obtains Let's Encrypt SSL certificate
- Configures auto-renewal
- Reloads nginx with SSL

### Maintenance Scripts

**`backup.sh`**
- Backs up PostgreSQL database
- Compresses with gzip
- Keeps last 30 days of backups
- Install as cron job: `0 2 * * * /home/django/deployment/scripts/backup.sh`

**`update.sh`**
- Pulls latest code from git
- Updates dependencies
- Runs migrations
- Collects static files
- Resets permissions
- Restarts services

## Systemd Services

Service files in `systemd/`:
- `django-gunicorn.service` - Gunicorn WSGI server
- `django-celery.service` - Celery worker
- `django-celery-beat.service` - Celery beat scheduler (optional)

Install with: `cd systemd && sudo ./install.sh`

## Nginx Configuration

Configuration file: `nginx/platform.wafer.space.conf`

Features:
- HTTP to HTTPS redirect
- SSL/TLS with Mozilla Intermediate profile
- Security headers (HSTS, CSP, etc.)
- Proxy to Gunicorn Unix socket
- Media file serving

Install with: `cd nginx && sudo ./install.sh`

## Security Features

These scripts implement security best practices:

1. **Privilege Separation**
   - Code owned by `django` user
   - Services run as `www-data` (read-only access)
   - Prevents compromised app from modifying code

2. **File Permissions**
   - 750 for directories (owner rwx, group rx)
   - 640 for files (owner rw, group r)
   - 640 for .env (secrets protected)

3. **Systemd Hardening**
   - NoNewPrivileges
   - PrivateDevices
   - ProtectSystem
   - ProtectHome
   - ReadWritePaths limited to logs/media only

## See Also

- [Production Deployment Guide](../docs/production_deployment.md) - Full documentation
- [Developer Onboarding](../docs/developer_onboarding.md) - Development setup
- [Troubleshooting](../docs/troubleshooting.md) - Common issues
