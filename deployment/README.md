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

See [nginx/README.md](./nginx/README.md) for Nginx configuration details.

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

## Operations

See [scripts/README.md](./scripts/README.md) for:

- **Maintenance** - Updates, secrets rotation, backups, log management
- **Monitoring** - Service health checks, viewing logs
- **Troubleshooting** - Common issues and solutions
- **Performance Tuning** - Gunicorn, Celery, and PostgreSQL optimization

## Additional Resources

- [docs/systemd-services.md](../docs/systemd-services.md) - Complete Celery worker configuration
- [scripts/](./scripts/) - Setup and maintenance scripts
- [systemd/](./systemd/) - Systemd service files
- [nginx/](./nginx/) - Nginx configuration
- [docs/developer_onboarding.md](../docs/developer_onboarding.md) - Development environment setup
- [CLAUDE.md](../CLAUDE.md) - Development guidelines
