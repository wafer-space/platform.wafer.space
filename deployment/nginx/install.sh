#!/bin/bash
# Install nginx configuration
# Run as: sudo ./install.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Installing nginx configuration ==="

# Create certbot directory
echo "Creating certbot directory..."
mkdir -p /var/www/certbot
chown -R www-data:www-data /var/www/certbot
echo "✓ Certbot directory created"

# Disable default nginx site to avoid conflicts
if [ -L /etc/nginx/sites-enabled/default ]; then
    echo "Disabling default nginx site..."
    rm /etc/nginx/sites-enabled/default
    echo "✓ Default site disabled"
fi

# Copy nginx config
echo "Copying nginx configuration..."
cp "$SCRIPT_DIR/platform.wafer.space.conf" /etc/nginx/sites-available/platform.wafer.space
echo "✓ Configuration copied"

# Enable site
if [ -L /etc/nginx/sites-enabled/platform.wafer.space ]; then
    echo "✓ Site already enabled"
else
    echo "Enabling site..."
    ln -s /etc/nginx/sites-available/platform.wafer.space /etc/nginx/sites-enabled/
    echo "✓ Site enabled"
fi

# Test configuration
echo "Testing nginx configuration..."
if ! nginx -t; then
    echo "✗ Nginx configuration test failed"
    exit 1
fi

# Reload nginx to apply new configuration
echo "Reloading nginx..."
if systemctl reload nginx; then
    echo "✓ Nginx reloaded successfully"
else
    echo "✗ Nginx reload failed"
    systemctl status nginx --no-pager -l
    exit 1
fi

echo ""
echo "=== Nginx configuration installed ==="
echo ""
echo "✓ HTTP server is active (port 80)"
echo "✓ HTTPS server block is commented out (will be enabled by SSL setup)"
echo ""
echo "Next step: Setup SSL certificate"
echo "  cd ../scripts"
echo "  sudo ./05-setup-ssl.sh"
echo ""
echo "The SSL script will:"
echo "  1. Obtain Let's Encrypt certificate"
echo "  2. Uncomment the HTTPS server block"
echo "  3. Reload nginx with SSL enabled"
