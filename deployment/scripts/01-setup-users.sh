#!/bin/bash
# Setup users for privilege separation
# Run as: sudo ./01-setup-users.sh

set -e

echo "=== Setting up users for privilege separation ==="

# Create django user for code deployment and ownership
if id "django" &>/dev/null; then
    echo "✓ User 'django' already exists"
else
    echo "Creating django user..."
    useradd --system --create-home --shell /bin/bash django
    echo "✓ User 'django' created"
fi

# Verify www-data user exists (should be created by nginx/apache)
if id "www-data" &>/dev/null; then
    echo "✓ User 'www-data' already exists"
else
    echo "Creating www-data user..."
    useradd --system --no-create-home --shell /usr/sbin/nologin www-data
    echo "✓ User 'www-data' created"
fi

# Create application directories
echo "Creating application directories..."
mkdir -p /var/log/platform.wafer.space
mkdir -p /var/run/platform.wafer.space

# Set ownership - www-data runs the services
chown -R www-data:www-data /var/log/platform.wafer.space
chown -R www-data:www-data /var/run/platform.wafer.space

echo "✓ Application directories created and owned by www-data"

echo ""
echo "=== User setup complete ==="
echo "- django: Code owner and deployment user"
echo "- www-data: Service runner (read-only access to code)"
