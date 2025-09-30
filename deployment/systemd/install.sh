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
echo "To start services:"
echo "  sudo systemctl start django-gunicorn.service"
echo "  sudo systemctl start django-celery.service"
echo "  # sudo systemctl start django-celery-beat.service"
echo ""
echo "To check status:"
echo "  sudo systemctl status django-gunicorn.service"
echo "  sudo systemctl status django-celery.service"
