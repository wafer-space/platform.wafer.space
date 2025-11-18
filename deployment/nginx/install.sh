#!/bin/bash
# Install nginx configuration
# Run as: sudo ./install.sh

set -e

# Auto-detect environment
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../scripts/detect-environment.sh"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NGINX_CONF="$MAIN_DOMAIN.conf"

echo "=== Installing nginx configuration ($ENV_NAME environment) ==="
echo "Configuration: $NGINX_CONF"

# Create certbot directory
echo "Creating certbot directory..."
mkdir -p /var/www/certbot
chown -R www-data:www-data /var/www/certbot
echo "✓ Certbot directory created"

# Disable default nginx site to avoid conflicts
if [ -L /etc/nginx/sites-enabled/default ] || [ -f /etc/nginx/sites-enabled/default ]; then
    echo "Disabling default nginx site..."
    rm -f /etc/nginx/sites-enabled/default
    echo "✓ Default site disabled"
fi

# Check for other configs with default_server that might conflict
echo "Checking for conflicting default_server configurations..."
if grep -r "listen.*default_server" /etc/nginx/sites-enabled/* 2>/dev/null | grep -v "$MAIN_DOMAIN"; then
    echo "⚠ WARNING: Found other configs with default_server:"
    grep -r "listen.*default_server" /etc/nginx/sites-enabled/* 2>/dev/null | grep -v "$MAIN_DOMAIN" || true
    echo ""
    echo "These may conflict with our configuration."
    echo "Press Ctrl+C to abort, or Enter to continue..."
    read -r
else
    echo "✓ No conflicting default_server found"
fi

# Copy nginx config
echo "Copying nginx configuration..."
cp "$SCRIPT_DIR/$NGINX_CONF" "/etc/nginx/sites-available/$MAIN_DOMAIN"
echo "✓ Configuration copied"

# Enable site
if [ -L "/etc/nginx/sites-enabled/$MAIN_DOMAIN" ]; then
    echo "✓ Site already enabled"
else
    echo "Enabling site..."
    ln -s "/etc/nginx/sites-available/$MAIN_DOMAIN" /etc/nginx/sites-enabled/
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

# Verify default_server is working
echo "Verifying default_server configuration..."
sleep 1  # Give nginx a moment to fully reload
RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost/ 2>&1 || echo "000")
if [ "$RESPONSE" = "000" ] || [ "$RESPONSE" = "444" ]; then
    echo "✓ Default server is blocking unknown hosts correctly"
elif [ "$RESPONSE" = "400" ]; then
    echo "⚠ WARNING: Requests to localhost are reaching the application!"
    echo "  This may indicate a conflicting nginx configuration."
    echo "  Run: sudo ../scripts/diagnose-nginx.sh to investigate"
else
    echo "⚠ Unexpected response to localhost: HTTP $RESPONSE"
fi
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
