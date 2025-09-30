#!/bin/bash
# Setup file permissions for privilege separation
# Run as: sudo ./04-setup-permissions.sh [APP_DIR]

set -e

APP_DIR="${1:-/home/django/platform.wafer.space}"

if [ ! -d "$APP_DIR" ]; then
    echo "Error: Application directory not found: $APP_DIR"
    echo "Usage: $0 [APP_DIR]"
    exit 1
fi

echo "=== Setting up file permissions for privilege separation ==="
echo "Application directory: $APP_DIR"

# Set ownership: django owns files, www-data group can read
echo "Setting ownership to django:www-data..."
chown -R django:www-data "$APP_DIR"

# Set directory permissions: owner rwx, group rx, other none
echo "Setting directory permissions (750)..."
find "$APP_DIR" -type d -exec chmod 750 {} \;

# Set file permissions: owner rw, group r, other none
echo "Setting file permissions (640)..."
find "$APP_DIR" -type f -exec chmod 640 {} \;

# Make manage.py executable
if [ -f "$APP_DIR/manage.py" ]; then
    echo "Making manage.py executable..."
    chmod 750 "$APP_DIR/manage.py"
fi

# Secure .env file
if [ -f "$APP_DIR/.env" ]; then
    echo "Securing .env file (640)..."
    chmod 640 "$APP_DIR/.env"
fi

# www-data needs write access to media directory
if [ -d "$APP_DIR/wafer_space/media" ]; then
    echo "Setting media directory ownership to www-data..."
    chown -R www-data:www-data "$APP_DIR/wafer_space/media"
    chmod 755 "$APP_DIR/wafer_space/media"
fi

# Create media directory if it doesn't exist
if [ ! -d "$APP_DIR/wafer_space/media" ]; then
    echo "Creating media directory..."
    mkdir -p "$APP_DIR/wafer_space/media"
    chown -R www-data:www-data "$APP_DIR/wafer_space/media"
    chmod 755 "$APP_DIR/wafer_space/media"
fi

echo ""
echo "=== Permissions set successfully ==="
echo "Verification:"
ls -la "$APP_DIR" | head -10
echo ""
if [ -f "$APP_DIR/.env" ]; then
    ls -la "$APP_DIR/.env"
fi
