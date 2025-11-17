#!/bin/bash
# Install systemd service files
# Run as: sudo ./install.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Installing systemd service files ==="

# Copy service files
echo "Copying service files to /etc/systemd/system/..."
cp "$SCRIPT_DIR/django-gunicorn.service" /etc/systemd/system/
cp "$SCRIPT_DIR/django-celery.service" /etc/systemd/system/
cp "$SCRIPT_DIR/django-celery-manufacturability.service" /etc/systemd/system/
cp "$SCRIPT_DIR/django-celery-beat.service" /etc/systemd/system/

echo "✓ Service files copied"

# Reload systemd
echo "Reloading systemd daemon..."
systemctl daemon-reload
echo "✓ Systemd daemon reloaded"

# Log installation markers to journal for each service
echo "Logging installation markers..."
TIMESTAMP=$(date -u +"%Y-%m-%d %H:%M:%S UTC")
echo "Service files installed/updated at $TIMESTAMP" | systemd-cat -t django-gunicorn -p info
echo "Service files installed/updated at $TIMESTAMP" | systemd-cat -t django-celery -p info
echo "Service files installed/updated at $TIMESTAMP" | systemd-cat -t django-celery-manufacturability -p info
echo "Service files installed/updated at $TIMESTAMP" | systemd-cat -t django-celery-beat -p info
echo "✓ Installation markers logged to journal"

# Enable services
echo "Enabling services..."
systemctl enable django-gunicorn.service
systemctl enable django-celery.service
systemctl enable django-celery-manufacturability.service
# systemctl enable django-celery-beat.service  # Uncomment if using scheduled tasks

echo "✓ Services enabled"

# Restart services
echo ""
echo "Restarting services..."

SERVICES=(
    "django-gunicorn.service"
    "django-celery.service"
    "django-celery-manufacturability.service"
    "django-celery-beat.service"
)

for service in "${SERVICES[@]}"; do
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
echo "To check status:"
echo "  sudo systemctl status django-gunicorn.service"
echo "  sudo systemctl status django-celery.service"
echo "  sudo systemctl status django-celery-manufacturability.service"
echo "  sudo systemctl status django-celery-beat.service"
echo ""
echo "To view logs since installation:"
echo "  sudo journalctl -u django-gunicorn.service --since '$TIMESTAMP'"
echo "  sudo journalctl -u django-celery-manufacturability.service --since '$TIMESTAMP'"
