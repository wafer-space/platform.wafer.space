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

# 3. Run setup scripts
sudo ./scripts/01-setup-users.sh
sudo ./scripts/02-install-dependencies.sh
sudo ./scripts/03-setup-database.sh

# 4. Setup application as django user
sudo -u django -i
cd /home/django
git clone https://github.com/wafer-space/platform.wafer.space.git platform.wafer.space
cd platform.wafer.space

# Install uv and create Python environment
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env
make venv

# Configure environment settings
echo 'export DJANGO_SETTINGS_MODULE=config.settings.production' >> ~/.bashrc
source ~/.bashrc

# 5. Edit .env file (auto-created by database setup script with DATABASE_URL)
# See Environment Configuration section below for what to edit
nano .env

# 6. Run Django setup
make migrate
make createsuperuser
make collectstatic
exit

# 7. Set permissions and install services (back as root)
cd /home/django/platform.wafer.space/deployment
sudo ./scripts/04-setup-permissions.sh /home/django/platform.wafer.space

cd systemd
sudo ./install.sh

cd ../nginx
sudo ./install.sh

cd ../scripts
sudo ./05-setup-ssl.sh platform.wafer.space bot@wafer.space

# 8. Start services
sudo systemctl start django-gunicorn.service
sudo systemctl start django-celery.service

# 9. Verify deployment
sudo systemctl status django-gunicorn.service
sudo systemctl status django-celery.service
curl https://platform.wafer.space
```

**Done!** Your application is now running at https://platform.wafer.space

## Deployment Scripts Reference

### 01-setup-users.sh

Creates system users with privilege separation for security:

- **django user**: Owns application code, deploys updates (no service execution)
- **www-data user**: Runs services (read-only access to code)

Creates directories:
- `/var/log/platform.wafer.space` (logs, owned by www-data)
- `/var/run/platform.wafer.space` (Unix sockets, owned by www-data)

### 02-install-dependencies.sh

Installs all system packages required for the application:

- Build tools (gcc, make, etc.)
- Python development headers
- PostgreSQL client libraries
- Nginx web server
- Certbot (Let's Encrypt)
- UFW firewall
- Image processing libraries (for Pillow)

### 03-setup-database.sh

Sets up PostgreSQL database and creates `.env` file automatically:

1. Generates secure 32-character random password
2. Creates `platform_wafer_space` database
3. Creates `platform_wafer_space` user with generated password
4. Configures PostgreSQL user settings (encoding, timezone, etc.)
5. Creates `.env` from `.env.production.template` (if .env doesn't exist)
6. Adds/updates `DATABASE_URL` in `.env` file
7. Sets proper file permissions (640, owner django:django)

**Non-interactive**: Runs completely automatically with no prompts.

**What you need to do after**: Edit `.env` to add secrets (DJANGO_SECRET_KEY, MAILGUN_API_KEY, OAuth credentials).

### 04-setup-permissions.sh

Implements privilege separation security model:

- Sets ownership: `django:www-data` on all application files
- Directories: `750` (owner rwx, group rx, others none)
- Files: `640` (owner rw, group r, others none)
- Special: `/wafer_space/media/` owned by `www-data:www-data` with `755` (needs write access)

This prevents a compromised service from modifying application code.

### 05-setup-ssl.sh

Automates SSL certificate setup:

1. Verifies nginx configuration is valid
2. Starts nginx if not running
3. Obtains Let's Encrypt certificate for `platform.wafer.space`
4. Uncomments HTTPS server block in nginx config
5. Reloads nginx with SSL enabled

**Auto-renewal**: Certbot installs a systemd timer for automatic certificate renewal.

## Environment Configuration

The `.env` file is automatically created by the database setup script (`03-setup-database.sh`) from the `.env.production.template`. It includes all necessary configuration variables with helpful comments.

**The DATABASE_URL is automatically configured** - you just need to add the other secrets.

Edit the file as the django user:

```bash
sudo -u django nano /home/django/platform.wafer.space/.env
```

### Configuration Variables

The template includes all required variables with comments. You need to edit these values:

**Required changes:**

1. **DJANGO_SECRET_KEY** - Generate a new secret key:
   ```bash
   uv run python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
   ```

2. **MAILGUN_API_KEY** - Get from [Mailgun dashboard](https://www.mailgun.com/)

3. **OAuth Credentials** - Create OAuth applications:
   - **GitHub**: [Developer settings](https://github.com/settings/developers)
     - Homepage: `https://platform.wafer.space`
     - Callback: `https://platform.wafer.space/accounts/github/login/callback/`
   - **GitLab**: [Applications](https://gitlab.com/-/profile/applications)
     - Redirect URI: `https://platform.wafer.space/accounts/gitlab/login/callback/`
   - **Google**: [Credentials](https://console.cloud.google.com/apis/credentials)
     - Redirect URI: `https://platform.wafer.space/accounts/google/login/callback/`

**Already configured automatically:**
- `DATABASE_URL` - Set by database setup script with generated password
- `DJANGO_SETTINGS_MODULE` - Set to `config.settings.production`
- `DJANGO_ALLOWED_HOSTS` - Set to `platform.wafer.space`
- Security settings - All HTTPS/HSTS settings configured

### Template File

The template file `.env.production.template` in the repository root contains all configuration variables with helpful comments explaining each one. The database setup script copies this to `.env` and adds the DATABASE_URL automatically.

## Systemd Services

The deployment includes three systemd services:

### django-gunicorn.service

Runs Gunicorn WSGI server:
- User: `www-data`
- Socket: `/var/run/platform.wafer.space/gunicorn.sock`
- Workers: 4 (adjust based on CPU cores: 2-4 × CPU cores)
- Timeout: 120 seconds
- Security: `NoNewPrivileges`, `PrivateDevices`, `ProtectSystem=strict`

### django-celery.service

Runs Celery worker for background tasks:
- User: `www-data`
- Queues: `manufacturability`, `referrals`
- Concurrency: 4 workers
- Security: Same hardening as Gunicorn

### django-celery-beat.service (Optional)

Runs Celery Beat scheduler for periodic tasks:
- Only needed if you have scheduled tasks
- Not started by default

### Service Management

```bash
# Start services
sudo systemctl start django-gunicorn.service
sudo systemctl start django-celery.service

# Enable services (auto-start on boot)
sudo systemctl enable django-gunicorn.service
sudo systemctl enable django-celery.service

# Check status
sudo systemctl status django-gunicorn.service
sudo systemctl status django-celery.service

# View logs
sudo journalctl -u django-gunicorn.service -f
sudo journalctl -u django-celery.service -f
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
sudo systemctl status django-gunicorn.service django-celery.service nginx postgresql

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
sudo journalctl -u django-gunicorn.service -f

# Celery logs
sudo journalctl -u django-celery.service -f

# Nginx access logs
sudo tail -f /var/log/nginx/platform.wafer.space-access.log

# Nginx error logs
sudo tail -f /var/log/nginx/platform.wafer.space-error.log

# Application logs (if configured)
sudo tail -f /var/log/platform.wafer.space/*.log
```

## Troubleshooting

### Service Won't Start

```bash
# Check service status and logs
sudo systemctl status django-gunicorn.service
sudo journalctl -u django-gunicorn.service -n 50

# Common issues:
# - Check DATABASE_URL in .env
# - Check file permissions (should be django:www-data)
# - Check Gunicorn socket exists
# - Run: make venv (update dependencies)
```

### 502 Bad Gateway

```bash
# Gunicorn not running or socket issues
sudo systemctl restart django-gunicorn.service
sudo systemctl reload nginx

# Check socket exists
ls -la /var/run/platform.wafer.space/gunicorn.sock
```

### Static Files Not Loading

```bash
# Recollect static files
sudo -u django -i
cd /home/django/platform.wafer.space
export DJANGO_SETTINGS_MODULE=config.settings.production
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
export DJANGO_SETTINGS_MODULE=config.settings.production
make shell
# In shell: from django.db import connection; connection.ensure_connection()
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

Adjust concurrency in `/etc/systemd/system/django-celery.service`:

```
Default: 4 workers
High load: increase to 8-16 workers
```

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

- [deployment/README.md](../deployment/README.md) - Automated scripts documentation
- [deployment/scripts/](../deployment/scripts/) - Setup scripts
- [deployment/systemd/](../deployment/systemd/) - Service files
- [deployment/nginx/](../deployment/nginx/) - Nginx configuration
- [Developer Onboarding](developer_onboarding.md) - Development environment setup
- [CLAUDE.md](../CLAUDE.md) - Development guidelines
