# Deployment Scripts

This directory contains scripts for deploying and managing the platform.wafer.space application.

## Quick Reference

### Common Operations

```bash
# Restart all services (as django user after sudoers setup)
make restart
# OR
./deployment/scripts/restart.sh

# Reset/clear log files (requires sudo)
sudo make reset-logs
# OR
sudo ./deployment/scripts/reset-logs.sh

# Update application
sudo ./deployment/scripts/update.sh

# Backup database
sudo ./deployment/scripts/backup.sh
```

### First-Time Setup

After initial deployment, configure passwordless sudo for the django user:

```bash
sudo ./deployment/scripts/06-setup-sudoers.sh
```

This allows the django user to restart services without entering a password.

## Setup Scripts (Run once during initial deployment)

### 1. User Setup
```bash
sudo ./01-setup-users.sh
```
Creates the `django` user and sets up the home directory structure.

### 2. Install Dependencies
```bash
sudo ./02-install-dependencies.sh
```
Installs system packages (Python, PostgreSQL, Nginx, etc.).

#### 2a. Setup Secrets (Optional)
```bash
sudo ./02a-setup-secrets.sh
```
Sets up the secrets repository for secure credential management.

### 3. Database Setup
```bash
sudo ./03-setup-database.sh
```
Creates PostgreSQL database, user, and configures the `.env` file.

#### 3a. Update Environment Secrets
```bash
sudo ./03a-update-env-secrets.sh
```
Updates `.env` with secrets from the secrets repository (called by `03-setup-database.sh`).

### 4. Permissions Setup
```bash
sudo ./04-setup-permissions.sh
```
Sets correct file permissions for the application and logs.

### 5. SSL Setup
```bash
sudo ./05-setup-ssl.sh
```
Configures SSL certificates with Let's Encrypt for all domains.

**Domains included:**
- `platform.wafer.space` (main domain)
- All Thousand Parsec domains (39 total):
  - Base: `thousandparsec.{com,net,org}`
  - Common: `www.`, `old.`, `git.`, `mail.`
  - Historical infrastructure: `code.`, `darcs.`, `forums.`, `metaserver.`, `packages.`, `schemepy.`, `svn.`, `test.`

**Note:** For new installations, this script will obtain a certificate covering all domains. For existing installations where the certificate already exists, use `05a-expand-ssl-cert.sh` instead.

#### 5a. Expand SSL Certificate (Optional - Only if certificate already exists)
```bash
sudo ./05a-expand-ssl-cert.sh
```
Expands existing SSL certificate to include Thousand Parsec domains.

**Use when:**
- You already have an SSL certificate for platform.wafer.space
- You want to add Thousand Parsec domains to the existing certificate
- You need to eliminate SSL certificate warnings for Thousand Parsec domains

### 6. Sudoers Setup (Optional but Recommended)
```bash
sudo ./06-setup-sudoers.sh
```
Configures passwordless sudo for the django user to manage services.

**What it does:**
- Installs sudoers configuration to `/etc/sudoers.d/django-services`
- Allows django user to run systemctl commands without password
- Enables `make restart` and `./restart.sh` without sudo

**After this setup, django user can:**
- Run `make restart` without sudo
- Run `./restart.sh` without sudo
- Manage services: `sudo systemctl restart django-gunicorn.service` (no password)

### 7. Systemd Services Setup
```bash
sudo ../systemd/install.sh
```
Installs and restarts systemd services for the application.

**What it does:**
- Copies service files to `/etc/systemd/system/`
- Enables services to start on boot
- Reloads systemd daemon
- Restarts all services
- Logs installation markers to journal
- Shows service status

**Services managed:**

See [../systemd/](../systemd/) for the full list of 9 Celery workers plus Gunicorn, and [docs/systemd-services.md](../../docs/systemd-services.md) for complete configuration details.

**Note:** Run this after database setup and permissions are configured. The script will automatically restart services after updating service files.

## Operational Scripts

### Restart Services
```bash
# After sudoers setup (recommended)
./restart.sh
# OR
make restart

# Without sudoers setup
sudo ./restart.sh
```
**What it does:**
- Stops all services (Gunicorn, Celery, Celery Beat) in reverse order
- Starts all services in proper order
- Checks status of all services
- Logs to `/var/log/platform.wafer.space/restart.log`

**Use when:**
- After configuration changes
- After code updates (use `update.sh` instead for full updates)
- When services are misbehaving
- After environment variable changes

### Reset Log Files
```bash
# Must be run as root
sudo ./reset-logs.sh
# OR
sudo make reset-logs

# With options
sudo ./reset-logs.sh --no-backup    # Don't backup before reset
sudo ./reset-logs.sh --force        # Don't ask for confirmation
sudo ./reset-logs.sh --help         # Show help
```
**What it does:**
- Lists all log files in `/var/log/platform.wafer.space/`
- Shows file sizes and total disk usage
- Creates backup archive (unless `--no-backup`)
- Truncates log files to 0 bytes (preserves permissions)
- Saves backups to `/var/backups/platform.wafer.space/logs/`
- Resets systemd journal logs for all django services (with confirmation)

**Use when:**
- Log files are growing too large
- Debugging and need clean logs
- After resolving issues to start fresh
- Regular maintenance

**Log locations:**
- Application logs: `/var/log/platform.wafer.space/*.log`
- Systemd journal: Automatically reset by script
- Backup archives: `/var/backups/platform.wafer.space/logs/`

**Services with journal logs:**

All `django-gunicorn` and `django-celery-*` services. See [docs/systemd-services.md](../../docs/systemd-services.md) for the complete list.

**Manual systemd journal commands:**
```bash
# View journal disk usage
sudo journalctl --disk-usage

# View logs for specific service
sudo journalctl -u django-gunicorn.service -n 100

# Clear all systemd journal logs manually
sudo journalctl --rotate
sudo journalctl --vacuum-time=1d  # Keep last day
sudo journalctl --vacuum-size=100M  # Keep max 100MB
```

### Update Application
```bash
sudo ./update.sh
```
**What it does:**
- Pulls latest code from git
- Updates secrets repository
- Updates dependencies (`make venv`)
- Runs database migrations
- Collects static files
- Fixes permissions
- Restarts services

**Use when:**
- Deploying new code
- After git commits to main branch

### Backup Database
```bash
sudo ./backup.sh
```
**What it does:**
- Creates timestamped PostgreSQL dump
- Saves to `/var/backups/platform.wafer.space/`
- Can be run manually or via cron

**Use when:**
- Before major updates
- Regular scheduled backups (via cron)
- Before risky operations

## Utility Scripts

### Load Environment Variables
```bash
source ./load-env.sh
```
Loads environment variables from `.env` file (used by other scripts).

## Service Management

The platform runs 9 Celery workers plus Gunicorn. See [docs/systemd-services.md](../../docs/systemd-services.md) for complete details.

### Manual Service Commands

```bash
# Check status
sudo systemctl status django-gunicorn
sudo systemctl status django-celery-none-ro-default
sudo systemctl status 'django-celery-*.service'

# View logs
sudo journalctl -u django-gunicorn -f
sudo journalctl -u django-celery-none-ro-checks-orch -f

# Restart all Celery workers
sudo systemctl restart 'django-celery-*.service'
```

## Logs

Application logs are stored in `/var/log/platform.wafer.space/`:
- `restart.log` - Service restart logs
- `update.log` - Update operation logs
- Other application-specific logs

## Makefile Integration

The restart script can also be run via make:

```bash
# From project root
sudo make restart
```

This provides a consistent interface with other development commands.

## Security Notes

- All scripts should be run with `sudo` as they require elevated privileges
- The `.env` file contains sensitive credentials (mode 640, owner django:django)
- Database passwords are randomly generated and stored securely
- Secrets repository (if used) should be a private git repository

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

### Services won't start

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

### Update fails

1. Check git status: `cd /home/django/platform.wafer.space && git status`
2. Verify dependencies: `make venv`
3. Check migrations: `make migrate`
4. Review update log: `sudo tail -f /var/log/platform.wafer.space/update.log`

### Permission errors

1. Run: `sudo ./04-setup-permissions.sh`
2. Verify django user: `id django`
3. Check file ownership: `ls -la /home/django/platform.wafer.space/`

## Performance Tuning

### Gunicorn Workers

Adjust worker count in `/etc/systemd/system/django-gunicorn.service`:

```text
Rule of thumb: (2-4) × CPU_CORES
2 CPU cores = 4-8 workers
4 CPU cores = 8-16 workers
```

### Celery Concurrency

Adjust concurrency in individual worker service files (e.g., `/etc/systemd/system/django-celery-none-ro-default.service`).

See [docs/systemd-services.md](../../docs/systemd-services.md) for worker-specific tuning recommendations.

### PostgreSQL

For production workload, tune PostgreSQL in `/etc/postgresql/17/main/postgresql.conf`:

```text
shared_buffers = 256MB (25% of RAM)
effective_cache_size = 1GB (50-75% of RAM)
maintenance_work_mem = 128MB
work_mem = 16MB
```

After changes:

```bash
sudo systemctl restart postgresql
```

## Development vs Production

These scripts are for **production deployment** only. For local development:

```bash
# Use Makefile commands instead
make runserver     # Development server
make celery        # Celery worker
make test          # Run tests
```

See the main project README for development setup instructions.
