#!/bin/bash
# Setup sudoers configuration for django user
# Run as: sudo ./06-setup-sudoers.sh

set -e

SUDOERS_FILE="/etc/sudoers.d/django-services"
SOURCE_FILE="/home/django/platform.wafer.space/deployment/sudoers/django-services"

echo "=== Setting up sudoers configuration for django user ==="

# Check if source file exists
if [ ! -f "$SOURCE_FILE" ]; then
    echo "Error: Source file not found: $SOURCE_FILE"
    exit 1
fi

# Verify sudoers syntax before installing
echo "Verifying sudoers syntax..."
if visudo -c -f "$SOURCE_FILE"; then
    echo "✓ Syntax is valid"
else
    echo "✗ Syntax error in sudoers file"
    exit 1
fi

# Copy file to /etc/sudoers.d/
echo "Installing sudoers configuration..."
cp "$SOURCE_FILE" "$SUDOERS_FILE"

# Set correct permissions (must be 0440)
chmod 0440 "$SUDOERS_FILE"
echo "✓ Set permissions to 0440"

# Verify the installed file
echo "Verifying installed configuration..."
if visudo -c; then
    echo "✓ Configuration is valid and installed"
else
    echo "✗ Configuration error, removing file"
    rm "$SUDOERS_FILE"
    exit 1
fi

echo ""
echo "=== Sudoers configuration complete ==="
echo ""
echo "The django user can now run the following commands without password:"
echo "  sudo systemctl restart django-gunicorn.service"
echo "  sudo systemctl restart django-celery.service"
echo "  sudo systemctl restart django-celery-beat.service"
echo "  sudo systemctl start/stop/status <service>"
echo "  sudo /home/django/platform.wafer.space/deployment/scripts/restart.sh"
echo ""
echo "Test with:"
echo "  sudo -u django sudo systemctl status django-gunicorn.service"
echo ""
