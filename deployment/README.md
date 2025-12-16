# Production Deployment Guide

This guide covers deploying platform.wafer.space to a production server running Debian 12 (Bookworm) or Debian Trixie (testing).

## Overview

**Automated Deployment:** This project includes complete deployment automation in the `deployment/` directory. The scripts handle setup, configuration, and security hardening automatically.

### Technology Stack

- **Server OS**: Debian 12 (Bookworm) or Debian Trixie (testing)
- **Python**: 3.13.7 (managed by uv)
- **Web Server**: Nginx (reverse proxy)
- **Application Server**: Gunicorn (WSGI)
- **Database**: PostgreSQL 17+
- **Task Queue**: Celery (with PostgreSQL broker)
- **SSL/TLS**: Let's Encrypt (via certbot)
- **Process Management**: systemd
- **Security**: Privilege separation (django user owns code, www-data runs services)

### Prerequisites

- Fresh Debian 12 or Debian Trixie server with root access
- Domain name pointing to server IP (platform.wafer.space)
- Ports 22 (SSH), 80 (HTTP), and 443 (HTTPS) accessible

### Server Requirements

- **RAM**: 2GB minimum (4GB recommended)
- **Disk**: 20GB minimum
- **CPU**: 2 cores minimum

## Quick Start

For a fresh Debian server, run these commands in order:

```bash
# 1. Initial system setup
sudo apt update && sudo apt upgrade -y
sudo hostnamectl set-hostname platform.wafer.space
sudo timedatectl set-timezone UTC

# 2. Clone repository
cd /tmp
git clone https://github.com/wafer-space/platform.wafer.space.git
cd platform.wafer.space/deployment

# 3. Run initial setup scripts
sudo ./scripts/01-setup-users.sh
sudo ./scripts/02-install-dependencies.sh

# 4. Setup SSH key for django user (to access secrets repository)
sudo -u django ssh-keygen -t ed25519 -C "django@platform.wafer.space"
sudo cat /home/django/.ssh/id_ed25519.pub
# Add this public key as a deploy key to:
# https://github.com/mithro/platform.wafer.space-secrets/settings/keys

# 5. Setup application as django user
sudo -u django -i
cd /home/django
git clone https://github.com/wafer-space/platform.wafer.space.git platform.wafer.space
cd platform.wafer.space

# Install uv and create Python environment
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env
make venv

# Configure environment settings
echo 'export DJANGO_SETTINGS_MODULE=config.settings.prod' >> ~/.bashrc
source ~/.bashrc
exit

# 6. Clone secrets repository
cd /tmp/platform.wafer.space/deployment
sudo ./scripts/02a-setup-secrets.sh

# 7. Setup database (creates .env with DATABASE_URL, DJANGO_SECRET_KEY, and OAuth secrets)
sudo ./scripts/03-setup-database.sh

# 8. Verify .env file (optional - all secrets are automatically configured)
# DATABASE_URL, DJANGO_SECRET_KEY, and all API secrets are already configured
# sudo -u django nano /home/django/platform.wafer.space/.env

# 9. Run Django setup (as django user)
sudo -u django -i
cd /home/django/platform.wafer.space
export DJANGO_SETTINGS_MODULE=config.settings.prod
make migrate
make createsuperuser
make collectstatic
exit

# 10. Set permissions and install services (back as root)
cd /home/django/platform.wafer.space/deployment
sudo ./scripts/04-setup-permissions.sh

cd systemd
sudo ./install.sh

cd ../nginx
sudo ./install.sh

cd ../scripts
sudo ./05-setup-ssl.sh

# 11. Verify deployment
sudo systemctl status django-gunicorn
sudo systemctl status django-celery-none-ro-default
curl https://platform.wafer.space
```

**Done!** Your application is now running at https://platform.wafer.space

## Deployment Scripts Reference

See [scripts/README.md](./scripts/README.md) for detailed documentation of all setup and operational scripts.

## Environment Configuration

The `.env` file is automatically created by the database setup script (`03-setup-database.sh`) from the `.env.prod.template`. It includes all necessary configuration variables with helpful comments.

**Automatically configured:**
- `DATABASE_URL` - Generated with secure random password
- `DJANGO_SECRET_KEY` - Generated with 50-character random key
- All secrets populated from `/home/django/.secrets/` by the setup script:
  - `MAILGUN_API_KEY` - from `mailgun` file
  - `GITHUB_CLIENT_SECRET` - from `github-oauth` file
  - `GITLAB_CLIENT_SECRET` - from `gitlab-oauth` file
  - `GOOGLE_CLIENT_SECRET` - from `google-auth.json` file
  - `DISCORD_CLIENT_SECRET` - from `discord-oauth` file
  - `LINKEDIN_CLIENT_SECRET` - from `linkedin-oauth` file

**No manual secret configuration needed** - all secrets are automatically populated from the secrets repository during setup.

Edit the file as the django user:

```bash
sudo -u django nano /home/django/platform.wafer.space/.env
```

### Configuration Variables

The template includes all required variables with comments. All values are automatically configured during setup.

**Already configured automatically:**
- `DATABASE_URL` - Set by database setup script with generated password
- `DJANGO_SECRET_KEY` - Auto-generated 50-character secure random key
- `MAILGUN_API_KEY` - Populated from secrets repository (`mailgun` file)
- OAuth Client Secrets - All populated from secrets repository:
  - `GITHUB_CLIENT_SECRET` - from `github-oauth` file
  - `GITLAB_CLIENT_SECRET` - from `gitlab-oauth` file
  - `GOOGLE_CLIENT_SECRET` - from `google-auth.json` file
  - `DISCORD_CLIENT_SECRET` - from `discord-oauth` file
  - `LINKEDIN_CLIENT_SECRET` - from `linkedin-oauth` file
- OAuth Client IDs - Pre-configured in settings:
  - `GITHUB_CLIENT_ID` - Pre-configured for wafer-space organization
  - `GITLAB_CLIENT_ID` - Pre-configured for wafer-space group
  - `GOOGLE_CLIENT_ID` - Pre-configured for wafer-space project
  - `DISCORD_CLIENT_ID` - Pre-configured for wafer-space organization
  - `LINKEDIN_CLIENT_ID` - Pre-configured for wafer-space organization
- `DJANGO_SETTINGS_MODULE` - Set to `config.settings.prod`
- `DJANGO_ALLOWED_HOSTS` - Set to `platform.wafer.space`
- Security settings - All HTTPS/HSTS settings configured

**Note:** To update secrets (e.g., rotating API keys), update the secrets in the secrets repository, then run `deployment/scripts/03a-update-env-secrets.sh` and restart services.

### Template File

The template file `.env.prod.template` in the repository root contains all configuration variables with helpful comments explaining each one. The database setup script copies this to `.env` and adds the DATABASE_URL automatically.

## Systemd Services

The deployment includes 9 Celery workers plus Gunicorn, using queue naming convention `{network}:{filesystem}:{purpose}`.

**See [docs/systemd-services.md](../docs/systemd-services.md) for complete worker configuration, queue mapping, and security details.**

### Service Overview

| Service | User | Purpose |
|---------|------|---------|
| `django-gunicorn` | www-data | Web application (WSGI) |
| `django-celery-none-ro-default` | www-data | Maintenance tasks |
| `django-celery-none-ro-checks-orch` | www-data | Check orchestration |
| `django-celery-none-ro-beat` | www-data | Celery Beat scheduler |
| `django-celery-mail-ro-email` | www-data | Email via Mailgun |
| `django-celery-http-rw-downloads` | www-data | File downloads |
| `django-celery-dock-ro-checks-fast` | celery-mfg | Fast Docker ops |
| `django-celery-dock-ro-checks-slow` | celery-mfg | Slow Docker ops |
| `django-celery-dock-rw-checks-save` | celery-mfg | Save check results |

### Service Management

```bash
# Install all services
cd deployment/systemd && sudo ./install.sh

# Check status of all services
sudo systemctl status django-gunicorn
sudo systemctl status django-celery-none-ro-default
sudo systemctl status django-celery-none-ro-checks-orch

# View logs
sudo journalctl -u django-celery-none-ro-checks-orch -f

# Restart all Celery workers
sudo systemctl restart 'django-celery-*.service'
```

## Nginx Configuration

Nginx serves as a reverse proxy to Gunicorn:

### HTTP Server (Port 80)
- Serves Let's Encrypt challenge files from `/var/www/certbot`
- Redirects all other traffic to HTTPS

### HTTPS Server (Port 443)
- TLS 1.2 and 1.3 only
- Strong cipher suites (Mozilla Intermediate profile)
- HTTP/2 enabled
- Security headers (HSTS, X-Frame-Options, CSP, etc.)
- Proxies to Gunicorn Unix socket
- Serves media files directly from `/home/django/platform.wafer.space/wafer_space/media/`

### Configuration Files

- `/etc/nginx/sites-available/platform.wafer.space` - Main config
- `/etc/nginx/sites-enabled/platform.wafer.space` - Symlink to enable
- Logs: `/var/log/nginx/platform.wafer.space-{access,error}.log`

## Security Features

The deployment implements multiple layers of security:

### 1. Privilege Separation
- Code owned by `django` user (deployment only)
- Services run as `www-data` user (cannot modify code)
- Compromised service cannot modify application code

### 2. File Permissions
- Application: `750/640` (owner rwx/rw, group rx/r, others none)
- `.env` file: `640` (secrets protected)
- Media directory: `755` (www-data can write uploads)

### 3. Systemd Hardening
- `NoNewPrivileges`: Prevents privilege escalation
- `PrivateDevices`: No access to devices
- `ProtectSystem=strict`: Read-only filesystem except specified paths
- `ProtectHome=true`: No access to home directories
- `ReadWritePaths`: Limited to logs, media, and runtime directories

### 4. Network Security
- UFW firewall: Only ports 22, 80, 443 open
- SSL/TLS: Let's Encrypt with automatic renewal
- HTTPS enforced with HSTS (31536000 seconds / 1 year)
- Security headers prevent XSS, clickjacking, MIME sniffing

### 5. Database Security
- PostgreSQL listens only on localhost
- Secure password (32-character random)
- Connection via Unix socket (better than TCP for local connections)

## Firewall Configuration

```bash
# UFW should be configured during setup, but verify:
sudo ufw status

# Should show:
# Status: active
# To                         Action      From
# --                         ------      ----
# 22/tcp                     ALLOW       Anywhere
# 80/tcp                     ALLOW       Anywhere
# 443/tcp                    ALLOW       Anywhere
```

## Maintenance Operations

### Updates and Deployments

Use the automated update script:

```bash
# As django user
sudo -u django /home/django/platform.wafer.space/deployment/scripts/update.sh
```

The update script:
1. Pulls latest code from git
2. Updates Python dependencies (`make venv`)
3. Runs database migrations (`make migrate`)
4. Collects static files (`make collectstatic`)
5. Resets file permissions
6. Restarts Gunicorn and Celery services

### Updating Secrets

When secrets change in the secrets repository (e.g., rotating API keys), update the production `.env` file:

```bash
# Pull latest secrets from repository
cd /home/django/platform.wafer.space/deployment
sudo ./scripts/02a-setup-secrets.sh

# Update .env file with new secrets
sudo ./scripts/03a-update-env-secrets.sh

# Restart services to load new secrets
sudo systemctl restart django-gunicorn
sudo systemctl restart 'django-celery-*.service'
```

This updates only the secrets in `.env` without touching the database or other configuration.

### Database Backups

Use the automated backup script:

```bash
# Manual backup
sudo -u django /home/django/platform.wafer.space/deployment/scripts/backup.sh

# Automated daily backups (add to crontab)
sudo -u django crontab -e
# Add:
0 2 * * * /home/django/platform.wafer.space/deployment/scripts/backup.sh
```

Backups are stored in `/home/django/backups/` and kept for 30 days.

### Log Rotation

Logs are automatically rotated by systemd journal. Application logs in `/var/log/platform.wafer.space/` are rotated by the system.

### SSL Certificate Renewal

Certbot automatically renews certificates via systemd timer:

```bash
# Check renewal timer status
sudo systemctl status certbot.timer

# Manual renewal test
sudo certbot renew --dry-run
```

## Monitoring

### Service Health

```bash
# Check all services
sudo systemctl status django-gunicorn django-celery-none-ro-default nginx postgresql

# Check all Celery workers
sudo systemctl status 'django-celery-*.service'

# Check resource usage
htop

# Check disk space
df -h

# Check memory usage
free -h
```

### Application Logs

```bash
# Gunicorn logs
sudo journalctl -u django-gunicorn -f

# Celery worker logs (pick specific worker)
sudo journalctl -u django-celery-none-ro-checks-orch -f

# All Celery logs
sudo journalctl -u 'django-celery-*' -f

# Nginx access logs
sudo tail -f /var/log/nginx/platform.wafer.space-access.log

# Nginx error logs
sudo tail -f /var/log/nginx/platform.wafer.space-error.log
```

## Troubleshooting

### Service Won't Start

```bash
# Check service status and logs
sudo systemctl status django-gunicorn
sudo journalctl -u django-gunicorn -n 50

# Common issues:
# - Check DATABASE_URL in .env
# - Check file permissions (should be django:www-data)
# - Check Gunicorn socket exists
# - Run: make venv (update dependencies)
```

### 502 Bad Gateway

```bash
# Gunicorn not running or socket issues
sudo systemctl restart django-gunicorn
sudo systemctl reload nginx

# Check socket exists
ls -la /run/platform.wafer.space/gunicorn.sock
```

### Static Files Not Loading

```bash
# Recollect static files
sudo -u django -i
cd /home/django/platform.wafer.space
export DJANGO_SETTINGS_MODULE=config.settings.prod
make collectstatic
exit

# Check nginx config
sudo nginx -t
sudo systemctl reload nginx
```

### Database Connection Issues

```bash
# Check PostgreSQL is running
sudo systemctl status postgresql

# Check DATABASE_URL in .env
sudo -u django cat /home/django/platform.wafer.space/.env | grep DATABASE_URL

# Test connection
sudo -u django -i
cd /home/django/platform.wafer.space
export DJANGO_SETTINGS_MODULE=config.settings.prod
make shell
# In shell: from django.db import connection; connection.ensure_connection()
```

### Database Operations (Drop/Reset)

**IMPORTANT**: You must stop all services before performing database operations like dropping or recreating the database. Active connections will prevent these operations.

```bash
# Stop all services first
sudo systemctl stop django-gunicorn
sudo systemctl stop 'django-celery-*.service'

# Now you can perform database operations
sudo -u postgres psql -c "DROP DATABASE platform_wafer_space;"
sudo -u postgres psql -c "DROP USER platform_wafer_space;"

# Recreate database
cd /home/django/platform.wafer.space/deployment
sudo ./scripts/03-setup-database.sh

# Restart services
sudo systemctl start django-gunicorn
sudo systemctl start 'django-celery-*.service'
```

### SSL Certificate Issues

```bash
# Check certificate
sudo certbot certificates

# Test renewal
sudo certbot renew --dry-run

# Force renewal
sudo certbot renew --force-renewal

# Check nginx SSL config
sudo nginx -t
```

## Performance Tuning

### Gunicorn Workers

Adjust worker count in `/etc/systemd/system/django-gunicorn.service`:

```
Rule of thumb: (2-4) × CPU_CORES
2 CPU cores = 4-8 workers
4 CPU cores = 8-16 workers
```

### Celery Concurrency

Adjust concurrency in individual worker service files (e.g., `/etc/systemd/system/django-celery-none-ro-default.service`).

See [docs/systemd-services.md](../docs/systemd-services.md) for worker-specific tuning recommendations.

### PostgreSQL

For production workload, tune PostgreSQL in `/etc/postgresql/17/main/postgresql.conf`:

```
shared_buffers = 256MB (25% of RAM)
effective_cache_size = 1GB (50-75% of RAM)
maintenance_work_mem = 128MB
work_mem = 16MB
```

After changes:
```bash
sudo systemctl restart postgresql
```

## Additional Resources

- [docs/systemd-services.md](../docs/systemd-services.md) - Complete Celery worker configuration
- [scripts/](./scripts/) - Setup and maintenance scripts
- [systemd/](./systemd/) - Systemd service files
- [nginx/](./nginx/) - Nginx configuration
- [docs/developer_onboarding.md](../docs/developer_onboarding.md) - Development environment setup
- [CLAUDE.md](../CLAUDE.md) - Development guidelines
