#!/bin/bash
# Restart all platform.wafer.space services
# Run as django user: ./restart.sh
# Or with sudo: sudo ./restart.sh

set -e

LOG_FILE="/var/log/platform.wafer.space/restart.log"

# Create log directory if it doesn't exist (may need sudo)
if [ ! -d "$(dirname "$LOG_FILE")" ]; then
    sudo mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true
fi

# Use sudo for systemctl commands (will be passwordless if sudoers configured)
SUDO_CMD="sudo"

# Check if we're already running as root
if [ "$EUID" -eq 0 ]; then
    SUDO_CMD=""
fi

echo "$(date): Starting service restart..." | tee -a "$LOG_FILE" 2>/dev/null || echo "$(date): Starting service restart..."

# Define all services
SERVICES=(
    "django-gunicorn.service"
    "django-celery-none-ro-default.service"
    "django-celery-none-ro-checks-orch.service"
    "django-celery-none-ro-beat.service"
    "django-celery-mail-ro-email.service"
    "django-celery-http-rw-downloads.service"
    "django-celery-dock-ro-checks-fast.service"
    "django-celery-dock-ro-checks-slow.service"
    "django-celery-dock-rw-checks-save.service"
)

# Stop all services first (in reverse order)
echo "$(date): Stopping services..." | tee -a "$LOG_FILE" 2>/dev/null || echo "$(date): Stopping services..."
for ((i=${#SERVICES[@]}-1; i>=0; i--)); do
    service="${SERVICES[$i]}"
    echo "  Stopping $service..." | tee -a "$LOG_FILE" 2>/dev/null || echo "  Stopping $service..."
    $SUDO_CMD systemctl stop "$service" || echo "  Warning: Failed to stop $service" | tee -a "$LOG_FILE" 2>/dev/null || echo "  Warning: Failed to stop $service"
done

# Start all services (in order)
echo "$(date): Starting services..." | tee -a "$LOG_FILE" 2>/dev/null || echo "$(date): Starting services..."
for service in "${SERVICES[@]}"; do
    echo "  Starting $service..." | tee -a "$LOG_FILE" 2>/dev/null || echo "  Starting $service..."
    $SUDO_CMD systemctl start "$service" || {
        echo "  Error: Failed to start $service" | tee -a "$LOG_FILE" 2>/dev/null || echo "  Error: Failed to start $service"
        exit 1
    }
done

# Check status of all services
echo "" | tee -a "$LOG_FILE" 2>/dev/null || echo ""
echo "$(date): Service status:" | tee -a "$LOG_FILE" 2>/dev/null || echo "$(date): Service status:"
for service in "${SERVICES[@]}"; do
    if $SUDO_CMD systemctl is-active --quiet "$service"; then
        echo "  ✓ $service is running" | tee -a "$LOG_FILE" 2>/dev/null || echo "  ✓ $service is running"
    else
        echo "  ✗ $service is NOT running" | tee -a "$LOG_FILE" 2>/dev/null || echo "  ✗ $service is NOT running"
        $SUDO_CMD systemctl status "$service" --no-pager | tee -a "$LOG_FILE" 2>/dev/null || $SUDO_CMD systemctl status "$service" --no-pager
    fi
done

echo "" | tee -a "$LOG_FILE" 2>/dev/null || echo ""
echo "$(date): Restart completed" | tee -a "$LOG_FILE" 2>/dev/null || echo "$(date): Restart completed"
