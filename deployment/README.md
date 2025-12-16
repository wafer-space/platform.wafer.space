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

The `.env` file is automatically created by the database setup script (`03-setup-database.sh`) from `.env.prod.template`. All secrets are populated automatically from the secrets repository (`/home/django/.secrets/`).

**See [docs/settings.md](../docs/settings.md) for complete environment configuration details, including all settings across dev/pytest/stage/prod environments.**

To update secrets after rotation, run `deployment/scripts/03a-update-env-secrets.sh` and restart services.

## Systemd Services

The deployment includes Gunicorn plus 9 Celery workers using queue naming convention `{network}:{filesystem}:{purpose}`.

**See [docs/systemd-services.md](../docs/systemd-services.md) for complete worker configuration, queue mapping, service management commands, and security details.**

Install services with:

```bash
cd deployment/systemd && sudo ./install.sh
```

## Nginx Configuration

See [nginx/README.md](./nginx/README.md) for Nginx configuration details.

## Security Features

The deployment implements multiple layers of security:

- **Privilege Separation**: Code owned by `django` user, services run as `www-data`
- **File Permissions**: Application `750/640`, `.env` file `640`
- **Network Security**: UFW firewall (ports 22, 80, 443), Let's Encrypt SSL, HSTS
- **Database Security**: PostgreSQL on localhost via Unix socket

**See [docs/systemd-services.md](../docs/systemd-services.md) for systemd hardening details (NoNewPrivileges, ProtectSystem, etc.).**

## Operations

See [scripts/README.md](./scripts/README.md) for:

- **Maintenance** - Updates, secrets rotation, backups, log management
- **Monitoring** - Service health checks, viewing logs
- **Troubleshooting** - Common issues and solutions
- **Performance Tuning** - Gunicorn, Celery, and PostgreSQL optimization

## Additional Resources

- [docs/settings.md](../docs/settings.md) - Complete settings catalog for all environments
- [docs/systemd-services.md](../docs/systemd-services.md) - Celery worker configuration and security
- [docs/oauth_secret_rotation.md](../docs/oauth_secret_rotation.md) - Secret rotation procedures
- [docs/developer_onboarding.md](../docs/developer_onboarding.md) - Development environment setup
