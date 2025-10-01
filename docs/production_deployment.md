# Production Deployment Guide - Debian Linux

This guide provides step-by-step instructions for deploying the platform.wafer.space application on a stock Debian 12 (Bookworm) stable Linux server.

**Quick Start:** Automated deployment scripts are available in the [`deployment/`](../deployment/) directory. See the [deployment README](../deployment/README.md) for automated installation.

## Table of Contents

- [System Requirements](#system-requirements)
- [Initial Server Setup](#initial-server-setup)
- [Install System Dependencies](#install-system-dependencies)
- [PostgreSQL Setup](#postgresql-setup)
- [Application User Setup](#application-user-setup)
- [Application Installation](#application-installation)
- [Environment Configuration](#environment-configuration)
- [Database Migration](#database-migration)
- [Static Files Collection](#static-files-collection)
- [Systemd Services](#systemd-services)
- [Nginx Configuration](#nginx-configuration)
- [SSL/HTTPS Setup](#sslhttps-setup)
- [Security Hardening](#security-hardening)
- [Monitoring and Maintenance](#monitoring-and-maintenance)
- [Troubleshooting](#troubleshooting)

## System Requirements

### Hardware Requirements
- **CPU**: 2+ cores recommended
- **RAM**: 2GB minimum, 4GB+ recommended
- **Disk**: 20GB minimum, SSD recommended
- **Network**: Public IP address with ports 80/443 accessible

### Software Requirements
- **OS**: Debian 12 (Bookworm) stable
- **Python**: 3.13 (will be installed)
- **PostgreSQL**: 15+ (available in Debian 12)
- **Nginx**: Latest stable (available in Debian 12)

## Initial Server Setup

### 1. Update System Packages

```bash
sudo apt update
sudo apt upgrade -y
```

### 2. Set Hostname and Timezone

```bash
# Set hostname
sudo hostnamectl set-hostname platform.wafer.space

# Set timezone to UTC (recommended for production)
sudo timerctl set-timezone UTC

# Verify
hostnamectl
timedatectl
```

### 3. Create Swap Space (if not present)

```bash
# Check if swap exists
sudo swapon --show

# If no swap, create 2GB swap file
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Make swap permanent
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## Install System Dependencies

### 1. Install Core Dependencies

```bash
# Install essential build tools and libraries
sudo apt install -y \
    build-essential \
    curl \
    git \
    libpq-dev \
    python3-dev \
    python3-pip \
    python3-venv \
    software-properties-common \
    wget \
    certbot \
    python3-certbot-nginx
```

### 2. Install Python 3.13

Debian 12 ships with Python 3.11, so we need to install Python 3.13:

```bash
# Add deadsnakes PPA (for newer Python versions)
# Note: For Debian, we may need to build from source or use pyenv
# Alternative: Use pyenv for Python version management

# Install pyenv dependencies
sudo apt install -y \
    libbz2-dev \
    libffi-dev \
    liblzma-dev \
    libncursesw5-dev \
    libreadline-dev \
    libsqlite3-dev \
    libssl-dev \
    libxml2-dev \
    libxmlsec1-dev \
    tk-dev \
    xz-utils \
    zlib1g-dev

# Install pyenv as root (for system-wide Python)
curl https://pyenv.run | bash

# Add pyenv to PATH (for current session)
export PATH="/root/.pyenv/bin:$PATH"
eval "$(pyenv init -)"

# Install Python 3.13
pyenv install 3.13.7
pyenv global 3.13.7

# Verify
python3 --version  # Should show Python 3.13.7
```

**Alternative: Use uv to manage Python versions**

```bash
# Install uv (handles Python versions automatically)
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env

# uv will automatically download and use Python 3.13 when needed
```

### 3. Install PostgreSQL

```bash
# Install PostgreSQL 15 (available in Debian 12)
sudo apt install -y postgresql postgresql-contrib

# Start and enable PostgreSQL
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Verify installation
sudo systemctl status postgresql
```

### 4. Install Nginx

```bash
# Install Nginx
sudo apt install -y nginx

# Start and enable Nginx
sudo systemctl start nginx
sudo systemctl enable nginx

# Verify installation
sudo systemctl status nginx
```

## PostgreSQL Setup

### 1. Create Database and User

```bash
# Switch to postgres user
sudo -u postgres psql

# In PostgreSQL prompt:
CREATE DATABASE platform_wafer_space;
CREATE USER platform_wafer_space WITH PASSWORD 'your_secure_password_here';
ALTER ROLE platform_wafer_space SET client_encoding TO 'utf8';
ALTER ROLE platform_wafer_space SET default_transaction_isolation TO 'read committed';
ALTER ROLE platform_wafer_space SET timezone TO 'UTC';
GRANT ALL PRIVILEGES ON DATABASE platform_wafer_space TO platform_wafer_space;

# Exit PostgreSQL
\q
```

### 2. Configure PostgreSQL for Local Connections

Edit `/etc/postgresql/15/main/pg_hba.conf`:

```bash
sudo nano /etc/postgresql/15/main/pg_hba.conf
```

Ensure this line exists (should be default):
```
# TYPE  DATABASE        USER            ADDRESS                 METHOD
local   all             all                                     peer
host    all             all             127.0.0.1/32            md5
host    all             all             ::1/128                 md5
```

Restart PostgreSQL:
```bash
sudo systemctl restart postgresql
```

### 3. Test Database Connection

```bash
psql -h localhost -U platform_wafer_space -d platform_wafer_space -W
# Enter password when prompted
# If successful, you'll see the PostgreSQL prompt
\q
```

## Application User Setup

### 1. Create Application Users

For security through privilege separation, we use two users:
- **`django`**: Owns the code and performs deployments (has write access)
- **`www-data`**: Runs the application services (has read-only access to code)

This prevents a compromised application from modifying its own code.

```bash
# Create django user for code deployment and ownership
sudo useradd --system --create-home --shell /bin/bash django

# Set password (optional, for SSH access for deployments)
# sudo passwd django

# www-data user should already exist (created by nginx/apache)
# Verify it exists:
id www-data

# If www-data doesn't exist, create it:
# sudo useradd --system --no-create-home --shell /usr/sbin/nologin www-data
```

### 2. Create Application Directories

```bash
# Create log and runtime directories owned by www-data (service user)
sudo mkdir -p /var/log/platform.wafer.space
sudo mkdir -p /var/run/platform.wafer.space

# Set ownership - www-data runs the services
sudo chown -R www-data:www-data /var/log/platform.wafer.space
sudo chown -R www-data:www-data /var/run/platform.wafer.space

# Note: /home/django already exists from user creation
```

## Application Installation

### 1. Clone Repository

```bash
# Switch to django user
sudo -u django -i

# Clone the repository
cd /home/django
git clone https://github.com/wafer-space/platform.wafer.space.git platform.wafer.space
cd platform.wafer.space

# Checkout desired version/tag (use main for latest)
git checkout main
```

### 2. Install uv (Python Package Manager)

```bash
# As django user
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env

# Add uv to PATH permanently
echo 'source $HOME/.cargo/env' >> ~/.bashrc
```

### 3. Create Virtual Environment and Install Dependencies

```bash
# As django user, in /home/django/platform.wafer.space
cd /home/django/platform.wafer.space

# Create virtual environment and install dependencies
# uv will automatically download Python 3.13
make venv

# Verify installation
uv run python --version  # Should show Python 3.13.7

# Configure to use production settings by default
echo 'export DJANGO_SETTINGS_MODULE=config.settings.production' >> ~/.bashrc
source ~/.bashrc
```

## Environment Configuration

### 1. Create Production Environment File

```bash
# As django user, in /home/django/platform.wafer.space
nano .env
```

Add the following configuration (customize all values):

```bash
# Django Settings
# ------------------------------------------------------------------------------
DJANGO_DEBUG=False
DJANGO_SECRET_KEY=your-very-long-and-random-secret-key-change-this-in-production
DJANGO_SETTINGS_MODULE=config.settings.production
DJANGO_ALLOWED_HOSTS=platform.wafer.space,www.platform.wafer.space
DJANGO_ADMIN_URL=admin-secure-path-change-this/

# Database
# ------------------------------------------------------------------------------
DATABASE_URL=postgres://platform_wafer_space:your_secure_password_here@localhost:5432/platform_wafer_space

# Email Configuration (Mailgun)
# ------------------------------------------------------------------------------
MAILGUN_API_KEY=your-mailgun-api-key
MAILGUN_DOMAIN=mg.platform.wafer.space
MAILGUN_API_URL=https://api.mailgun.net/v3
DJANGO_DEFAULT_FROM_EMAIL=platform.wafer.space <bot@wafer.space>
DJANGO_SERVER_EMAIL=platform.wafer.space <bot@wafer.space>

# OAuth Providers - Production
# ------------------------------------------------------------------------------
# GitHub OAuth
GITHUB_CLIENT_ID=Ov23linEhI33aev2uGSU
GITHUB_CLIENT_SECRET=your_github_production_secret

# GitLab OAuth
GITLAB_CLIENT_ID=f0fde384db4cd0fe11041488a6b87e9d3d20223385b78d1ba1ed4045fbea6c16
GITLAB_CLIENT_SECRET=your_gitlab_production_secret

# Google OAuth
GOOGLE_CLIENT_ID=62545893239-pgg1lcg28u9suivjh4nso9t8mev5qua2.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_google_production_secret

# LinkedIn OAuth (optional)
LINKEDIN_CLIENT_ID=your_linkedin_client_id
LINKEDIN_CLIENT_SECRET=your_linkedin_client_secret

# Security Settings
# ------------------------------------------------------------------------------
DJANGO_SECURE_SSL_REDIRECT=True
DJANGO_SECURE_HSTS_SECONDS=518400
DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=True
DJANGO_SECURE_HSTS_PRELOAD=True
DJANGO_SECURE_CONTENT_TYPE_NOSNIFF=True

# Account Settings
# ------------------------------------------------------------------------------
DJANGO_ACCOUNT_ALLOW_REGISTRATION=True

# Database Connection Pool
# ------------------------------------------------------------------------------
CONN_MAX_AGE=60

# Celery Configuration
# ------------------------------------------------------------------------------
# Uses PostgreSQL as broker by default (via DATABASE_URL)
# Override if needed: CELERY_BROKER_URL=db+postgresql://platform_wafer_space:password@localhost:5432/platform_wafer_space
```

### 2. Secure Environment File

```bash
# As django user
chmod 600 .env

# Verify permissions
ls -l .env  # Should show -rw-------
```

### 3. Generate Django Secret Key

```bash
# Generate a secure secret key
uv run python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"

# Copy the output and update DJANGO_SECRET_KEY in .env
```

## Database Migration

### 1. Run Migrations

```bash
# As django user, in /home/django/platform.wafer.space
# (DJANGO_SETTINGS_MODULE should be set in ~/.bashrc from previous step)
make migrate

# You should see output like:
# Operations to perform:
#   Apply all migrations: admin, auth, contenttypes, sessions, users, projects, ...
# Running migrations:
#   Applying contenttypes.0001_initial... OK
#   ...
```

### 2. Create Superuser

```bash
# Create Django admin superuser
make createsuperuser

# Follow the prompts to set username, email, and password
```

## Static Files Collection

### 1. Collect Static Files

```bash
# As django user, in /home/django/platform.wafer.space
make collectstatic

# Static files will be collected to /home/django/platform.wafer.space/staticfiles/
```

### 2. Verify Static Files

```bash
ls -la /home/django/platform.wafer.space/staticfiles/
# Should contain admin/, css/, js/, etc.
```

### 3. Set File Permissions for Privilege Separation

Set secure permissions so django owns code, www-data can read:

```bash
# As root or with sudo
# Set ownership: django owns files, www-data group can read
sudo chown -R django:www-data /home/django/platform.wafer.space

# Set directory permissions: owner rwx, group rx, other none
sudo find /home/django/platform.wafer.space -type d -exec chmod 750 {} \;

# Set file permissions: owner rw, group r, other none
sudo find /home/django/platform.wafer.space -type f -exec chmod 640 {} \;

# Make manage.py and scripts executable
sudo chmod 750 /home/django/platform.wafer.space/manage.py

# Secure .env file - only django and www-data can read
sudo chmod 640 /home/django/platform.wafer.space/.env

# www-data needs write access to media directory
sudo chown -R www-data:www-data /home/django/platform.wafer.space/wafer_space/media
sudo chmod 755 /home/django/platform.wafer.space/wafer_space/media

# Verify permissions
ls -la /home/django/platform.wafer.space/
ls -la /home/django/platform.wafer.space/.env
```

## Systemd Services

### 1. Create Gunicorn Service

Create `/etc/systemd/system/django-gunicorn.service`:

```bash
sudo nano /etc/systemd/system/django-gunicorn.service
```

Add the following content:

```ini
[Unit]
Description=platform.wafer.space Gunicorn Application Server
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=notify
User=www-data
Group=www-data
WorkingDirectory=/home/django/platform.wafer.space
Environment="PATH=/home/django/platform.wafer.space/.venv/bin:/home/django/.cargo/bin"
Environment="DJANGO_SETTINGS_MODULE=config.settings.production"
EnvironmentFile=/home/django/platform.wafer.space/.env

ExecStart=/home/django/.cargo/bin/uv run gunicorn \
    --workers 4 \
    --worker-class sync \
    --bind unix:/var/run/platform.wafer.space/gunicorn.sock \
    --access-logfile /var/log/platform.wafer.space/gunicorn-access.log \
    --error-logfile /var/log/platform.wafer.space/gunicorn-error.log \
    --log-level info \
    --timeout 120 \
    config.wsgi:application

ExecReload=/bin/kill -s HUP $MAINPID
KillMode=mixed
TimeoutStopSec=5
PrivateTmp=true

# Security hardening
NoNewPrivileges=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/log/platform.wafer.space /var/run/platform.wafer.space /home/django/platform.wafer.space/wafer_space/media

# Restart policy
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

### 2. Create Celery Worker Service

Create `/etc/systemd/system/django-celery.service`:

```bash
sudo nano /etc/systemd/system/django-celery.service
```

Add the following content:

```ini
[Unit]
Description=platform.wafer.space Celery Worker
After=network.target postgresql.service django-gunicorn.service
Requires=postgresql.service

[Service]
Type=forking
User=www-data
Group=www-data
WorkingDirectory=/home/django/platform.wafer.space
Environment="PATH=/home/django/platform.wafer.space/.venv/bin:/home/django/.cargo/bin"
Environment="DJANGO_SETTINGS_MODULE=config.settings.production"
EnvironmentFile=/home/django/platform.wafer.space/.env

ExecStart=/home/django/.cargo/bin/uv run celery \
    -A config \
    worker \
    --loglevel=info \
    --logfile=/var/log/platform.wafer.space/celery.log \
    --pidfile=/var/run/platform.wafer.space/celery.pid \
    --detach \
    --queues=manufacturability,referrals

ExecStop=/bin/kill -s TERM $MAINPID
ExecReload=/bin/kill -s HUP $MAINPID

# Security hardening
NoNewPrivileges=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/log/platform.wafer.space /var/run/platform.wafer.space /home/django/platform.wafer.space/wafer_space/media

# Restart policy
Restart=on-failure
RestartSec=10s

[Install]
WantedBy=multi-user.target
```

### 3. Create Celery Beat Service (Optional - for scheduled tasks)

Create `/etc/systemd/system/django-celery-beat.service`:

```bash
sudo nano /etc/systemd/system/django-celery-beat.service
```

Add the following content:

```ini
[Unit]
Description=platform.wafer.space Celery Beat Scheduler
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/home/django/platform.wafer.space
Environment="PATH=/home/django/platform.wafer.space/.venv/bin:/home/django/.cargo/bin"
Environment="DJANGO_SETTINGS_MODULE=config.settings.production"
EnvironmentFile=/home/django/platform.wafer.space/.env

ExecStart=/home/django/.cargo/bin/uv run celery \
    -A config \
    beat \
    --loglevel=info \
    --logfile=/var/log/platform.wafer.space/celery-beat.log \
    --pidfile=/var/run/platform.wafer.space/celery-beat.pid

# Security hardening
NoNewPrivileges=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/log/platform.wafer.space /var/run/platform.wafer.space /home/django/platform.wafer.space/wafer_space/media

# Restart policy
Restart=on-failure
RestartSec=10s

[Install]
WantedBy=multi-user.target
```

### 4. Enable and Start Services

```bash
# Reload systemd to recognize new service files
sudo systemctl daemon-reload

# Enable services to start on boot
sudo systemctl enable django-gunicorn.service
sudo systemctl enable django-celery.service
# sudo systemctl enable django-celery-beat.service  # If using scheduled tasks

# Start services
sudo systemctl start django-gunicorn.service
sudo systemctl start django-celery.service
# sudo systemctl start django-celery-beat.service  # If using scheduled tasks

# Check service status
sudo systemctl status django-gunicorn.service
sudo systemctl status django-celery.service
# sudo systemctl status django-celery-beat.service  # If using scheduled tasks
```

### 5. Verify Services

```bash
# Check if Gunicorn socket is created
ls -la /var/run/platform.wafer.space/gunicorn.sock

# Check logs
sudo tail -f /var/log/platform.wafer.space/gunicorn-error.log
sudo tail -f /var/log/platform.wafer.space/celery.log

# Test if application is responding
curl --unix-socket /var/run/platform.wafer.space/gunicorn.sock http://localhost/
```

## Nginx Configuration

### 1. Create Nginx Configuration

Create `/etc/nginx/sites-available/platform.wafer.space`:

```bash
sudo nano /etc/nginx/sites-available/platform.wafer.space
```

Add the following content:

```nginx
# Redirect HTTP to HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name platform.wafer.space www.platform.wafer.space;

    # Allow Let's Encrypt challenges
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    # Redirect all other HTTP traffic to HTTPS
    location / {
        return 301 https://$server_name$request_uri;
    }
}

# HTTPS Server
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name platform.wafer.space www.platform.wafer.space;

    # SSL certificates (will be configured by certbot)
    ssl_certificate /etc/letsencrypt/live/platform.wafer.space/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/platform.wafer.space/privkey.pem;
    ssl_trusted_certificate /etc/letsencrypt/live/platform.wafer.space/chain.pem;

    # SSL configuration (Mozilla Intermediate)
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    ssl_stapling on;
    ssl_stapling_verify on;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # Client body size (for file uploads)
    client_max_body_size 100M;

    # Logging
    access_log /var/log/nginx/platform.wafer.space-access.log;
    error_log /var/log/nginx/platform.wafer.space-error.log;

    # Static files (served by WhiteNoise through Django)
    # WhiteNoise will handle static files, so we don't need a separate location

    # Media files (user uploads)
    location /media/ {
        alias /home/django/platform.wafer.space/wafer_space/media/;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }

    # Proxy to Gunicorn
    location / {
        proxy_pass http://unix:/var/run/platform.wafer.space/gunicorn.sock;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_redirect off;
        proxy_buffering off;

        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # Health check endpoint (optional)
    location /health/ {
        proxy_pass http://unix:/var/run/platform.wafer.space/gunicorn.sock;
        access_log off;
    }
}
```

### 2. Enable Nginx Configuration

```bash
# Create symbolic link to enable site
sudo ln -s /etc/nginx/sites-available/platform.wafer.space /etc/nginx/sites-enabled/

# Remove default site (optional)
sudo rm /etc/nginx/sites-enabled/default

# Test Nginx configuration
sudo nginx -t

# If test is successful, reload Nginx
sudo systemctl reload nginx
```

### 3. Create Certbot Directory

```bash
# Create directory for Let's Encrypt challenges
sudo mkdir -p /var/www/certbot
sudo chown -R www-data:www-data /var/www/certbot
```

## SSL/HTTPS Setup

### 1. Obtain SSL Certificate with Let's Encrypt

**First, temporarily comment out the SSL server block in Nginx config:**

```bash
sudo nano /etc/nginx/sites-available/platform.wafer.space
```

Comment out or remove the entire `server { listen 443 ...}` block temporarily, keeping only the HTTP server block.

```bash
# Reload Nginx
sudo nginx -t
sudo systemctl reload nginx
```

**Obtain certificate:**

```bash
# Obtain SSL certificate
sudo certbot certonly --webroot \
    -w /var/www/certbot \
    -d platform.wafer.space \
    -d www.platform.wafer.space \
    --email bot@wafer.space \
    --agree-tos \
    --no-eff-email

# Verify certificate
sudo certbot certificates
```

**Restore the full Nginx configuration:**

```bash
sudo nano /etc/nginx/sites-available/platform.wafer.space
# Uncomment the HTTPS server block

# Test and reload
sudo nginx -t
sudo systemctl reload nginx
```

### 2. Setup Certificate Auto-Renewal

```bash
# Test renewal
sudo certbot renew --dry-run

# Certbot automatically sets up a systemd timer for renewal
sudo systemctl list-timers | grep certbot

# Verify renewal timer is active
sudo systemctl status certbot.timer
```

### 3. Configure Certbot Renewal Hook

Create a renewal hook to reload Nginx after certificate renewal:

```bash
sudo nano /etc/letsencrypt/renewal-hooks/post/reload-nginx.sh
```

Add:
```bash
#!/bin/bash
systemctl reload nginx
```

Make it executable:
```bash
sudo chmod +x /etc/letsencrypt/renewal-hooks/post/reload-nginx.sh
```

## Security Hardening

### Overview of Security Measures

This deployment implements multiple layers of security:

1. **Privilege Separation**: Application runs as `www-data` with read-only access to code
   - Code is owned by `django` user (deployment only)
   - Services run as `www-data` user (cannot modify code)
   - If compromised, attacker cannot modify application files or install backdoors

2. **Systemd Hardening**: Services run with restricted permissions
   - `NoNewPrivileges`: Cannot gain additional privileges
   - `PrivateDevices`: No access to physical devices
   - `ProtectSystem`: Read-only access to system directories
   - `ProtectHome`: Limited access to home directories

3. **File Permissions**: Minimal access rights (750/640)
   - Only django and www-data can read application code
   - Only www-data can write to logs, media, and runtime directories

4. **Network Security**: Firewall and SSL/TLS
   - UFW firewall blocks all except necessary ports
   - Fail2Ban prevents brute force attacks
   - HTTPS enforced with HSTS headers

### 1. Configure Firewall (UFW)

```bash
# Install UFW if not present
sudo apt install -y ufw

# Set default policies
sudo ufw default deny incoming
sudo ufw default allow outgoing

# Allow SSH (adjust port if using non-standard)
sudo ufw allow 22/tcp

# Allow HTTP and HTTPS
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Enable firewall
sudo ufw enable

# Check status
sudo ufw status verbose
```

### 2. Fail2Ban for Brute Force Protection

```bash
# Install fail2ban
sudo apt install -y fail2ban

# Create local configuration
sudo cp /etc/fail2ban/jail.conf /etc/fail2ban/jail.local

# Edit configuration
sudo nano /etc/fail2ban/jail.local
```

Add Django-specific jail:
```ini
[django-auth]
enabled = true
port = http,https
filter = django-auth
logpath = /var/log/platform.wafer.space/gunicorn-error.log
maxretry = 5
bantime = 3600
```

Create filter:
```bash
sudo nano /etc/fail2ban/filter.d/django-auth.conf
```

Add:
```ini
[Definition]
failregex = ^.* "POST /accounts/login/ HTTP.*" (401|403) .*$
ignoreregex =
```

Restart fail2ban:
```bash
sudo systemctl restart fail2ban
sudo systemctl enable fail2ban
```

### 3. PostgreSQL Security

```bash
# Edit PostgreSQL configuration
sudo nano /etc/postgresql/15/main/postgresql.conf
```

Ensure these settings:
```
listen_addresses = 'localhost'
max_connections = 100
shared_buffers = 256MB
```

Restart PostgreSQL:
```bash
sudo systemctl restart postgresql
```

### 4. Regular Security Updates

```bash
# Enable automatic security updates
sudo apt install -y unattended-upgrades

# Configure
sudo dpkg-reconfigure -plow unattended-upgrades
```

## Monitoring and Maintenance

### 1. Log Rotation

Create `/etc/logrotate.d/platform.wafer.space`:

```bash
sudo nano /etc/logrotate.d/platform.wafer.space
```

Add:
```
/var/log/platform.wafer.space/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 www-data www-data
    sharedscripts
    postrotate
        systemctl reload django-gunicorn.service > /dev/null
        systemctl reload django-celery.service > /dev/null
    endscript
}
```

### 2. Monitoring Commands

```bash
# Check service status
sudo systemctl status django-gunicorn.service
sudo systemctl status django-celery.service
sudo systemctl status nginx.service
sudo systemctl status postgresql.service

# View recent logs
sudo journalctl -u django-gunicorn.service -n 100 -f
sudo journalctl -u django-celery.service -n 100 -f
sudo tail -f /var/log/platform.wafer.space/gunicorn-error.log
sudo tail -f /var/log/nginx/platform.wafer.space-error.log

# Check disk usage
df -h
du -sh /home/django/platform.wafer.space/

# Check memory usage
free -h

# Check PostgreSQL status
sudo -u postgres psql -c "SELECT version();"
sudo -u postgres psql -c "SELECT datname, numbackends FROM pg_stat_database;"
```

### 3. Database Backups

Create backup script `/home/django/backup.sh`:

```bash
sudo nano /home/django/backup.sh
```

Add:
```bash
#!/bin/bash
# Backup platform.wafer.space database

BACKUP_DIR="/home/django/backups"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/platform_wafer_space_$DATE.sql.gz"

# Create backup directory if it doesn't exist
mkdir -p $BACKUP_DIR

# Perform backup
pg_dump -h localhost -U platform_wafer_space platform_wafer_space | gzip > $BACKUP_FILE

# Keep only last 30 days of backups
find $BACKUP_DIR -name "platform_wafer_space_*.sql.gz" -mtime +30 -delete

# Log
echo "$(date): Backup completed: $BACKUP_FILE" >> /var/log/platform.wafer.space/backup.log
```

Make executable:
```bash
sudo chmod +x /home/django/backup.sh
sudo chown django:django /home/django/backup.sh
```

Create cron job:
```bash
sudo crontab -e -u django
```

Add:
```cron
# Daily database backup at 2 AM
0 2 * * * /home/django/backup.sh
```

### 4. Application Updates

Create update script `/home/django/update.sh`:

```bash
sudo nano /home/django/update.sh
```

Add:
```bash
#!/bin/bash
# Update platform.wafer.space application

set -e

APP_DIR="/home/django/platform.wafer.space"
LOG_FILE="/var/log/platform.wafer.space/update.log"

echo "$(date): Starting update..." | tee -a $LOG_FILE

# Navigate to app directory
cd $APP_DIR

# Pull latest changes
git pull origin main | tee -a $LOG_FILE

# Update dependencies
make venv | tee -a $LOG_FILE

# Run migrations
make migrate | tee -a $LOG_FILE

# Collect static files
make collectstatic | tee -a $LOG_FILE

# Fix permissions after update (django owns code, www-data can read)
sudo chown -R django:www-data $APP_DIR
sudo find $APP_DIR -type d -exec chmod 750 {} \;
sudo find $APP_DIR -type f -exec chmod 640 {} \;
sudo chmod 750 $APP_DIR/manage.py
sudo chmod 640 $APP_DIR/.env

# www-data needs write access to media directory
sudo chown -R www-data:www-data $APP_DIR/wafer_space/media
sudo chmod 755 $APP_DIR/wafer_space/media

# Restart services
sudo systemctl restart django-gunicorn.service
sudo systemctl restart django-celery.service

echo "$(date): Update completed successfully" | tee -a $LOG_FILE
```

Make executable:
```bash
sudo chmod +x /home/django/update.sh
sudo chown django:django /home/django/update.sh
```

Allow django user to restart services:
```bash
sudo visudo
```

Add:
```
django ALL=(ALL) NOPASSWD: /bin/systemctl restart django-gunicorn.service
django ALL=(ALL) NOPASSWD: /bin/systemctl restart django-celery.service
```

## Troubleshooting

### 1. Service Won't Start

```bash
# Check service status
sudo systemctl status django-gunicorn.service

# Check logs
sudo journalctl -u django-gunicorn.service -n 100
sudo tail -f /var/log/platform.wafer.space/gunicorn-error.log

# Common issues:
# - Database connection: Check DATABASE_URL in .env
# - Permission issues: Check file ownership (should be django:www-data with 750/640)
# - Missing dependencies: Run make venv as django user
```

### 2. 502 Bad Gateway

```bash
# Check if Gunicorn is running
sudo systemctl status django-gunicorn.service

# Check if socket file exists
ls -la /var/run/platform.wafer.space/gunicorn.sock

# Check Nginx error log
sudo tail -f /var/log/nginx/platform.wafer.space-error.log

# Restart services
sudo systemctl restart django-gunicorn.service
sudo systemctl reload nginx
```

### 3. Static Files Not Loading

```bash
# Recollect static files
sudo -u django -i
cd /home/django/platform.wafer.space
export DJANGO_SETTINGS_MODULE=config.settings.production
uv run python manage.py collectstatic --clear --noinput

# Check static files directory
ls -la /home/django/platform.wafer.space/staticfiles/

# Check Nginx configuration
sudo nginx -t
```

### 4. Celery Tasks Not Processing

```bash
# Check Celery worker status
sudo systemctl status django-celery.service

# Check Celery logs
sudo tail -f /var/log/platform.wafer.space/celery.log

# Inspect active tasks
sudo -u django -i
cd /home/django/platform.wafer.space
export DJANGO_SETTINGS_MODULE=config.settings.production
uv run celery -A config inspect active

# Restart Celery
sudo systemctl restart django-celery.service
```

### 5. Database Connection Issues

```bash
# Test database connection
sudo -u django -i
cd /home/django/platform.wafer.space
export DJANGO_SETTINGS_MODULE=config.settings.production
make shell

# Or access database shell directly:
uv run python manage.py dbshell

# Check PostgreSQL is running
sudo systemctl status postgresql

# Check PostgreSQL logs
sudo tail -f /var/log/postgresql/postgresql-15-main.log

# Verify DATABASE_URL in .env
cat /home/django/platform.wafer.space/.env | grep DATABASE_URL
```

### 6. High Memory Usage

```bash
# Check memory usage
free -h
ps aux --sort=-%mem | head -10

# Reduce Gunicorn workers if needed
sudo nano /etc/systemd/system/django-gunicorn.service
# Change --workers to 2 or 3

# Reload and restart
sudo systemctl daemon-reload
sudo systemctl restart django-gunicorn.service
```

### 7. SSL Certificate Issues

```bash
# Check certificate status
sudo certbot certificates

# Test renewal
sudo certbot renew --dry-run

# Force renew
sudo certbot renew --force-renewal

# Check Nginx SSL configuration
sudo nginx -t
```

## Performance Optimization

### 1. PostgreSQL Tuning

```bash
sudo nano /etc/postgresql/15/main/postgresql.conf
```

Adjust based on available RAM (example for 4GB RAM):
```
shared_buffers = 1GB
effective_cache_size = 3GB
maintenance_work_mem = 256MB
checkpoint_completion_target = 0.9
wal_buffers = 16MB
default_statistics_target = 100
random_page_cost = 1.1
effective_io_concurrency = 200
work_mem = 10MB
min_wal_size = 1GB
max_wal_size = 4GB
```

Restart PostgreSQL:
```bash
sudo systemctl restart postgresql
```

### 2. Connection Pooling

For high-traffic sites, consider adding pgBouncer:

```bash
sudo apt install -y pgbouncer
```

Configure and update DATABASE_URL to point to pgBouncer instead of PostgreSQL directly.

### 3. Redis for Caching (Optional)

If local-memory cache is insufficient, add Redis:

```bash
sudo apt install -y redis-server
sudo systemctl enable redis-server
sudo systemctl start redis-server
```

Update settings to use Redis for cache instead of local memory.

## Deployment Checklist

Before going live, verify:

- [ ] All environment variables are set correctly in `.env`
- [ ] Django DEBUG is set to False
- [ ] SECRET_KEY is changed from default
- [ ] Database migrations are applied
- [ ] Static files are collected
- [ ] File permissions are set correctly (django:www-data with 750/640)
- [ ] Services run as www-data user (privilege separation)
- [ ] Superuser account is created
- [ ] All services are running (gunicorn, celery, nginx, postgresql)
- [ ] SSL certificate is installed and auto-renewal is configured
- [ ] Firewall is enabled and configured
- [ ] Backups are scheduled
- [ ] Log rotation is configured
- [ ] Domain DNS points to server IP
- [ ] OAuth apps are configured for production domain
- [ ] Email sending is configured and tested
- [ ] Monitoring and alerting are set up

## Additional Resources

- **Django Deployment Checklist**: https://docs.djangoproject.com/en/stable/howto/deployment/checklist/
- **Gunicorn Documentation**: https://docs.gunicorn.org/
- **Nginx Documentation**: https://nginx.org/en/docs/
- **PostgreSQL Documentation**: https://www.postgresql.org/docs/
- **Celery Documentation**: https://docs.celeryproject.org/
- **Let's Encrypt**: https://letsencrypt.org/

## Support

For issues specific to the platform.wafer.space application:
- GitHub Issues: https://github.com/wafer-space/platform.wafer.space/issues
- Documentation: See other files in `docs/` directory

---

**Note**: This guide assumes a fresh Debian 12 installation. Adjust commands and paths as needed for your specific environment.
