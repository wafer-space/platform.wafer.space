#!/bin/bash
# Setup SSL certificate with Let's Encrypt
# Run as: sudo ./05-setup-ssl.sh

set -e

DOMAIN="${1:-platform.wafer.space}"
EMAIL="${2:-bot@wafer.space}"

echo "=== Setting up SSL certificate ==="
echo "Domain: $DOMAIN"
echo "Email: $EMAIL"
echo ""

# Verify nginx config exists
if [ ! -f "/etc/nginx/sites-available/platform.wafer.space" ]; then
    echo "Error: Nginx configuration not found"
    echo "Run: cd ../nginx && sudo ./install.sh"
    exit 1
fi

# Check if certbot directory exists
if [ ! -d "/var/www/certbot" ]; then
    echo "Creating certbot directory..."
    mkdir -p /var/www/certbot
    chown -R www-data:www-data /var/www/certbot
fi

# Test nginx configuration
echo "Testing nginx configuration..."
nginx -t

# Reload nginx to apply HTTP-only config
echo "Reloading nginx..."
systemctl reload nginx

# Check if certificate already exists
if [ -d "/etc/letsencrypt/live/$DOMAIN" ]; then
    echo "✓ SSL certificate already exists for $DOMAIN"
    echo "To renew: sudo certbot renew"
else
    # Obtain certificate
    echo "Obtaining SSL certificate from Let's Encrypt..."
    certbot certonly --webroot \
        -w /var/www/certbot \
        -d "$DOMAIN" \
        -d "www.$DOMAIN" \
        --email "$EMAIL" \
        --agree-tos \
        --no-eff-email \
        --non-interactive

    echo "✓ Certificate obtained"
fi

# Verify certificate
echo "Verifying certificate..."
certbot certificates

# Test nginx configuration again
echo "Testing nginx configuration with SSL..."
nginx -t

# Reload nginx with SSL enabled
echo "Reloading nginx with SSL..."
systemctl reload nginx

echo ""
echo "=== SSL certificate installed successfully ==="
echo "Certificate: /etc/letsencrypt/live/$DOMAIN/fullchain.pem"
echo "Private key: /etc/letsencrypt/live/$DOMAIN/privkey.pem"
echo ""
echo "Auto-renewal is configured via systemd timer:"
echo "  sudo systemctl status certbot.timer"
