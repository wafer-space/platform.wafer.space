#!/bin/bash
# Install systemd service files
# Run as: sudo ./install.sh
#
# Queue naming convention: {network}:{fs}:{purpose}
#   - Network: none (DB only), mail (Mailgun), http (HTTP/S), dock (Docker IPs)
#   - Filesystem: ro (read-only), rw (media write)
#
# This script handles migration from old service names to new ones.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Installing systemd service files ==="

# Old service files to remove (migration)
OLD_SERVICES=(
    "django-celery.service"
    "django-celery-downloads.service"
    "django-celery-docker-persistent.service"
    "django-celery-docker-ephemeral.service"
    "django-celery-beat.service"
)

# New service files to install
NEW_SERVICES=(
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

# Stop and disable old services
echo ""
echo "=== Cleaning up old services ==="
for service in "${OLD_SERVICES[@]}"; do
    if [ -f "/etc/systemd/system/$service" ]; then
        echo "  Stopping and disabling: $service"
        systemctl stop "$service" 2>/dev/null || true
        systemctl disable "$service" 2>/dev/null || true
    fi
done

# Remove old service files from systemd
echo "  Removing old service files from /etc/systemd/system/..."
for service in "${OLD_SERVICES[@]}"; do
    if [ -f "/etc/systemd/system/$service" ]; then
        rm -f "/etc/systemd/system/$service"
        echo "    Removed: $service"
    fi
done
echo "✓ Old services cleaned up"

# Copy new service files
echo ""
echo "=== Installing new service files ==="
echo "Copying service files to /etc/systemd/system/..."
for service in "${NEW_SERVICES[@]}"; do
    if [ -f "$SCRIPT_DIR/$service" ]; then
        cp "$SCRIPT_DIR/$service" /etc/systemd/system/
        echo "  Installed: $service"
    else
        echo "  WARNING: $service not found in $SCRIPT_DIR"
    fi
done
echo "✓ Service files copied"

# Reload systemd
echo ""
echo "Reloading systemd daemon..."
systemctl daemon-reload
echo "✓ Systemd daemon reloaded"

# Log installation markers to journal for each service
echo ""
echo "Logging installation markers..."
TIMESTAMP=$(date -u +"%Y-%m-%d %H:%M:%S UTC")
for service in "${NEW_SERVICES[@]}"; do
    service_name="${service%.service}"
    echo "Service files installed/updated at $TIMESTAMP" | systemd-cat -t "$service_name" -p info
done
echo "✓ Installation markers logged to journal"

# Enable services
echo ""
echo "Enabling services..."
for service in "${NEW_SERVICES[@]}"; do
    systemctl enable "$service"
done
echo "✓ Services enabled"

# Restart services
echo ""
echo "Restarting services..."

for service in "${NEW_SERVICES[@]}"; do
    echo "  Restarting $service..."
    systemctl restart "$service" && {
        echo "  ✓ Restarted: $service"
    } || {
        echo "  ✗ Failed to restart: $service"
        echo "  Checking status..."
        systemctl status "$service" --no-pager || true
    }
done

echo ""
echo "=== Systemd services installed and restarted ==="
echo "Services have been installed, enabled, and restarted."
echo ""
echo "Installation marker logged to journal at: $TIMESTAMP"
echo ""
echo "Queue naming convention: {network}:{fs}:{purpose}"
echo "  Network: none (DB only), mail (Mailgun), http (HTTP/S), dock (Docker IPs)"
echo "  Filesystem: ro (read-only), rw (media write)"
echo ""
echo "Each service has isolated directories:"
echo "  /run/platform.wafer.space-<service>/     - runtime (PID, socket)"
echo "  /var/log/platform.wafer.space-<service>/ - logs"
echo ""
echo "To check status:"
for service in "${NEW_SERVICES[@]}"; do
    echo "  sudo systemctl status $service"
done
echo ""
echo "To view logs:"
echo "  sudo journalctl -u django-gunicorn.service -f"
echo "  sudo tail -f /var/log/platform.wafer.space-celery-*/worker.log"
echo ""
