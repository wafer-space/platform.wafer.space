# Docker Access Configuration for Manufacturability Checking

The manufacturability checking system requires the Celery worker to have access to Docker to run precheck validations in isolated containers.

## Requirements

1. **Docker Engine** must be installed on the production server
2. **Dedicated Celery worker user** (`celery-mfg`) must have permission to access the Docker daemon
3. **Docker image** (`ghcr.io/wafer-space/gf180mcu-precheck:latest`) must be pulled

## Setup Steps

### 1. Install Docker

```bash
# Install Docker Engine (if not already installed)
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
```

### 2. Create Dedicated Celery Worker User

The manufacturability Celery worker requires a dedicated user separate from the web server user for security isolation.

```bash
# Create celery-mfg user (system user, no login shell)
sudo useradd -r -s /bin/false -M -d /nonexistent celery-mfg

# Grant read access to Django application directory
sudo usermod -aG django celery-mfg
```

### 3. Grant Docker Access to Celery Worker

The `celery-mfg` user needs permission to interact with the Docker daemon to run precheck containers.

```bash
# Add celery-mfg user to the docker group
sudo usermod -aG docker celery-mfg

# Verify the user was added
groups celery-mfg
```

**Security Note:** Adding a user to the `docker` group grants significant privileges equivalent to root access. This is why we use a dedicated user (`celery-mfg`) instead of the web server user (`www-data`). This provides security isolation - if the manufacturability worker is compromised, the web server is not automatically compromised.

### 4. Pull the Precheck Docker Image

```bash
# Pull the image (as root or a user with Docker access)
docker pull ghcr.io/wafer-space/gf180mcu-precheck:latest

# Verify the image was pulled
docker images | grep gf180mcu-precheck
```

### 5. Test Docker Access

After configuration, verify that the Celery worker can access Docker:

```bash
# Switch to the celery-mfg user
sudo -u celery-mfg -s

# Test Docker access
docker ps

# Test running the precheck image
docker run --rm ghcr.io/wafer-space/gf180mcu-precheck:latest --version

# Exit back to your user
exit
```

If these commands succeed, Docker access is configured correctly.

### 6. Install and Start Manufacturability Service

Install the systemd service for the manufacturability worker:

```bash
# Install the service file
sudo cp deployment/systemd/django-celery-manufacturability.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable the service to start on boot
sudo systemctl enable django-celery-manufacturability.service

# Start the service
sudo systemctl start django-celery-manufacturability.service

# Check status
sudo systemctl status django-celery-manufacturability.service
```

## Alternative: Using SupplementaryGroups (Already Configured)

The manufacturability service (`django-celery-manufacturability.service`) is already configured with `SupplementaryGroups=docker` in the systemd unit file. This means Docker access is only granted within the context of the systemd service, providing an additional layer of security.

You don't need to manually configure this - it's already set up in the service file.

## Verification

To verify manufacturability checking is working:

1. Submit a project with a GDS file
2. Check the manufacturability Celery logs for Docker activity:
   ```bash
   sudo journalctl -u django-celery-manufacturability.service -f | grep -i docker
   ```
3. Monitor running containers during a check:
   ```bash
   watch docker ps
   ```
4. Verify both Celery workers are running:
   ```bash
   # Referrals worker (runs as www-data)
   sudo systemctl status django-celery.service

   # Manufacturability worker (runs as celery-mfg)
   sudo systemctl status django-celery-manufacturability.service
   ```

## Troubleshooting

### Permission Denied Error

If you see "permission denied" errors when running Docker commands:

1. Verify the user is in the docker group: `groups celery-mfg`
2. Ensure Docker socket permissions: `ls -la /var/run/docker.sock`
3. Restart the manufacturability Celery worker after adding to docker group:
   ```bash
   sudo systemctl restart django-celery-manufacturability.service
   ```
4. In some cases, a system reboot may be required for group changes to take effect

### Image Pull Errors

If the Docker image cannot be pulled:

1. Check network connectivity from the server
2. Verify the image name and tag are correct
3. Check if authentication is required for `ghcr.io`
4. Manual pull test: `docker pull ghcr.io/wafer-space/gf180mcu-precheck:latest`

### Container Execution Failures

If containers fail to start:

1. Check Docker daemon status: `sudo systemctl status docker`
2. Verify available disk space: `df -h`
3. Check Docker logs: `sudo journalctl -u docker.service -n 100`
4. Test manual container run with verbose output

## Security Considerations

- **Dedicated user architecture**: The manufacturability worker runs as `celery-mfg`, separate from the web server user (`www-data`)
  - **Benefit**: Compromising the manufacturability worker doesn't automatically compromise the web server
  - **Trade-off**: Docker access = root-equivalent access, but limited to one isolated service

- **Container isolation**: Precheck runs in isolated containers with no network access

- **Resource limits**: Configure Docker resource constraints if needed

- **Image trust**: Only use official precheck images from trusted sources (`ghcr.io/wafer-space/gf180mcu-precheck:latest`)

- **Regular updates**: Keep Docker and the precheck image updated

- **X-Forwarded-For and IP Tracking**: Export compliance certification logs the client IP address for audit purposes. Ensure nginx is configured as the trusted reverse proxy:
  - The nginx config uses `$proxy_add_x_forwarded_for` which appends to existing headers
  - For accurate client IP logging, ensure requests only come through trusted nginx proxy
  - Client-provided X-Forwarded-For headers can be spoofed if requests bypass nginx
  - IP addresses are used for audit trail purposes, not security enforcement

- **Two-worker architecture**:
  - `django-celery.service` (as `www-data`): Handles referrals queue
  - `django-celery-manufacturability.service` (as `celery-mfg`): Handles manufacturability queue with Docker access

## Environment Variables

Ensure these variables are set in the production `.env` file:

```bash
# Docker image to use for manufacturability checking
PRECHECK_DOCKER_IMAGE=ghcr.io/wafer-space/gf180mcu-precheck:latest

# Concurrency limits
PRECHECK_CONCURRENT_LIMIT=4
PRECHECK_PER_USER_LIMIT=1

# Timeout for precheck execution (3 hours)
PRECHECK_TIMEOUT_SECONDS=10800
```

## Monitoring

Monitor Docker resource usage:

```bash
# View Docker stats
docker stats

# Check disk usage by Docker
docker system df

# Clean up unused images/containers periodically
docker system prune -a
```
