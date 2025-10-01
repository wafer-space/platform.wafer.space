#!/bin/bash
# Setup file permissions for privilege separation
# Run as: sudo ./04-setup-permissions.sh

set -e

APP_DIR="/home/django/platform.wafer.space"

if [ ! -d "$APP_DIR" ]; then
    echo "Error: Application directory not found: $APP_DIR"
    exit 1
fi

echo "=== Setting up file permissions for privilege separation ==="
echo "Application directory: $APP_DIR"

# Ensure /home/django is traversable by www-data (other users need execute permission)
echo "Making /home/django traversable..."
chmod 755 /home/django

# Secure .env file (owner rw, www-data group r, other none)
if [ -f "$APP_DIR/.env" ]; then
    echo "Securing .env file..."
    chown django:www-data "$APP_DIR/.env"
    chmod 640 "$APP_DIR/.env"
fi

# Create media directory if it doesn't exist and set writable by www-data
if [ ! -d "$APP_DIR/wafer_space/media" ]; then
    echo "Creating media directory..."
    mkdir -p "$APP_DIR/wafer_space/media"
fi

echo "Setting media directory writable by www-data..."
chown -R www-data:www-data "$APP_DIR/wafer_space/media"
chmod 755 "$APP_DIR/wafer_space/media"

echo ""
echo "=== Permissions set successfully ==="
echo "✓ /home/django traversable: $(stat -c '%a' /home/django)"
if [ -f "$APP_DIR/.env" ]; then
    echo "✓ .env secured: $(stat -c '%a %U:%G' "$APP_DIR/.env")"
fi
if [ -d "$APP_DIR/wafer_space/media" ]; then
    echo "✓ media writable: $(stat -c '%a %U:%G' "$APP_DIR/wafer_space/media")"
fi
