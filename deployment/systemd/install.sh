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
echo "Service files installed/updated at $TIMESTAMP" | systemd-cat -t django-celery-beat -p info
echo "✓ Installation markers logged to journal"

# Enable services
echo "Enabling services..."
systemctl enable django-gunicorn.service
systemctl enable django-celery.service
# systemctl enable django-celery-beat.service  # Uncomment if using scheduled tasks

echo "✓ Services enabled"

echo ""
echo "=== Systemd services installed ==="
echo "Services have been installed and enabled but not started."
echo ""
echo "Installation marker logged to journal at: $TIMESTAMP"
echo ""
echo "To start services:"
echo "  sudo systemctl start django-gunicorn.service"
echo "  sudo systemctl start django-celery.service"
echo "  # sudo systemctl start django-celery-beat.service"
echo ""
echo "To check status:"
echo "  sudo systemctl status django-gunicorn.service"
echo "  sudo systemctl status django-celery.service"
echo ""
echo "To view logs since installation:"
echo "  sudo journalctl -u django-gunicorn.service --since '$TIMESTAMP'"
