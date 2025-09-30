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
nginx -t

echo ""
echo "=== Nginx configuration installed ==="
echo ""
echo "IMPORTANT: SSL certificates are not yet configured!"
echo "Before reloading nginx, you need to:"
echo "1. Comment out the HTTPS server block (lines with 'listen 443')"
echo "2. Reload nginx: sudo systemctl reload nginx"
echo "3. Obtain SSL certificate: sudo certbot certonly --webroot -w /var/www/certbot -d platform.wafer.space -d www.platform.wafer.space --email bot@wafer.space"
echo "4. Uncomment the HTTPS server block"
echo "5. Reload nginx again: sudo systemctl reload nginx"
echo ""
echo "Or run: sudo ../scripts/05-setup-ssl.sh"
