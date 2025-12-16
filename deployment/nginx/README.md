# Nginx Configuration

Nginx serves as a reverse proxy to Gunicorn.

## HTTP Server (Port 80)

- Serves Let's Encrypt challenge files from `/var/www/certbot`
- Redirects all other traffic to HTTPS

## HTTPS Server (Port 443)

- TLS 1.2 and 1.3 only
- Strong cipher suites (Mozilla Intermediate profile)
- HTTP/2 enabled
- Security headers (HSTS, X-Frame-Options, CSP, etc.)
- Proxies to Gunicorn Unix socket
- Serves media files directly from `/home/django/platform.wafer.space/wafer_space/media/`

## Configuration Files

- `/etc/nginx/sites-available/platform.wafer.space` - Main config
- `/etc/nginx/sites-enabled/platform.wafer.space` - Symlink to enable
- Logs: `/var/log/nginx/platform.wafer.space-{access,error}.log`

## Installation

```bash
cd deployment/nginx
sudo ./install.sh
```

The install script:
1. Copies the appropriate config file based on environment (staging vs production)
2. Creates symlink in sites-enabled
3. Tests nginx configuration
4. Reloads nginx

## Files

| File | Description |
|------|-------------|
| `platform.wafer.space.conf` | Production nginx config |
| `test-platform.wafer.space.conf` | Staging nginx config |
| `install.sh` | Installation script |
