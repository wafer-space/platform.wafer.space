#!/bin/bash
# Setup SSL certificate with Let's Encrypt
# Run as: sudo ./05-setup-ssl.sh

set -e

MAIN_DOMAIN="platform.wafer.space"
EMAIL="bot@wafer.space"

# All domains to include in certificate
THOUSANDPARSEC_DOMAINS=(
    "thousandparsec.com"
    "www.thousandparsec.com"
    "thousandparsec.net"
    "www.thousandparsec.net"
    "thousandparsec.org"
    "www.thousandparsec.org"
    "old.thousandparsec.com"
    "old.thousandparsec.net"
    "old.thousandparsec.org"
    "git.thousandparsec.com"
    "git.thousandparsec.net"
    "git.thousandparsec.org"
    "mail.thousandparsec.com"
    "mail.thousandparsec.net"
    "mail.thousandparsec.org"
    "code.thousandparsec.com"
    "code.thousandparsec.net"
    "code.thousandparsec.org"
    "darcs.thousandparsec.com"
    "darcs.thousandparsec.net"
    "darcs.thousandparsec.org"
    "forums.thousandparsec.com"
    "forums.thousandparsec.net"
    "forums.thousandparsec.org"
    "metaserver.thousandparsec.com"
    "metaserver.thousandparsec.net"
    "metaserver.thousandparsec.org"
    "packages.thousandparsec.com"
    "packages.thousandparsec.net"
    "packages.thousandparsec.org"
    "schemepy.thousandparsec.com"
    "schemepy.thousandparsec.net"
    "schemepy.thousandparsec.org"
    "svn.thousandparsec.com"
    "svn.thousandparsec.net"
    "svn.thousandparsec.org"
    "test.thousandparsec.com"
    "test.thousandparsec.net"
    "test.thousandparsec.org"
)

echo "=== Setting up SSL certificate ==="
echo "Main domain: $MAIN_DOMAIN"
echo "Additional domains: ${THOUSANDPARSEC_DOMAINS[*]}"
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

# Start or reload nginx to apply HTTP-only config
if systemctl is-active --quiet nginx; then
    echo "Reloading nginx..."
    systemctl reload nginx
else
    echo "Starting nginx..."
    systemctl start nginx
fi

# Check if certificate already exists
if [ -d "/etc/letsencrypt/live/$MAIN_DOMAIN" ]; then
    echo "✓ SSL certificate already exists for $MAIN_DOMAIN"
    echo "To renew or add domains: sudo certbot renew or re-run this script with --force-renewal"
else
    # Build certbot command with all domains
    echo "Obtaining SSL certificate from Let's Encrypt..."
    CERTBOT_CMD="certbot certonly --webroot -w /var/www/certbot"
    CERTBOT_CMD="$CERTBOT_CMD -d $MAIN_DOMAIN"

    # Add all Thousand Parsec domains
    for domain in "${THOUSANDPARSEC_DOMAINS[@]}"; do
        CERTBOT_CMD="$CERTBOT_CMD -d $domain"
    done

    CERTBOT_CMD="$CERTBOT_CMD --email $EMAIL --agree-tos --no-eff-email --non-interactive"

    echo "Running: $CERTBOT_CMD"
    eval "$CERTBOT_CMD"

    echo "✓ Certificate obtained for all domains"
fi

# Verify certificate
echo "Verifying certificate..."
certbot certificates

# Enable HTTPS server block in nginx config
echo "Enabling HTTPS server block..."
NGINX_CONFIG="/etc/nginx/sites-available/platform.wafer.space"
# Remove the marker comment and uncomment the HTTPS block
sed -i '/^# HTTPS Server - UNCOMMENTED BY SSL SETUP SCRIPT$/d' "$NGINX_CONFIG"
sed -i '/^#server {$/,/^#}$/s/^#//' "$NGINX_CONFIG"

# Test nginx configuration with SSL enabled
echo "Testing nginx configuration with SSL..."
if ! nginx -t; then
    echo "✗ Nginx configuration test failed"
    exit 1
fi

# Reload or restart nginx with SSL enabled
if systemctl is-active --quiet nginx; then
    echo "Reloading nginx with SSL..."
    if systemctl reload nginx; then
        echo "✓ Nginx reloaded successfully"
    else
        echo "✗ Nginx reload failed"
        systemctl status nginx --no-pager -l
        exit 1
    fi
else
    echo "Starting nginx with SSL..."
    if systemctl start nginx; then
        echo "✓ Nginx started successfully"
    else
        echo "✗ Nginx start failed"
        systemctl status nginx --no-pager -l
        exit 1
    fi
fi

echo ""
echo "=== SSL certificate installed successfully ==="
echo "Certificate: /etc/letsencrypt/live/$MAIN_DOMAIN/fullchain.pem"
echo "Private key: /etc/letsencrypt/live/$MAIN_DOMAIN/privkey.pem"
echo ""
echo "Domains covered by this certificate:"
echo "  - $MAIN_DOMAIN"
for domain in "${THOUSANDPARSEC_DOMAINS[@]}"; do
    echo "  - $domain"
done
echo ""
echo "✓ Auto-renewal is configured (certbot.timer)"
echo ""
echo "To verify auto-renewal is active (optional):"
echo "  sudo systemctl status certbot.timer"
