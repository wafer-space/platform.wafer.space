#!/bin/bash
# Expand existing SSL certificate to include Thousand Parsec domains
# Run as: sudo ./05a-expand-ssl-cert.sh

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

echo "=== Expanding SSL certificate to include all domains ==="
echo "Main domain: $MAIN_DOMAIN"
echo "Additional domains: ${THOUSANDPARSEC_DOMAINS[*]}"
echo "Email: $EMAIL"
echo ""

# Check if certificate exists
if [ ! -d "/etc/letsencrypt/live/$MAIN_DOMAIN" ]; then
    echo "Error: Certificate for $MAIN_DOMAIN does not exist"
    echo "Run: sudo ./05-setup-ssl.sh first"
    exit 1
fi

# Verify nginx config exists and is working
if [ ! -f "/etc/nginx/sites-available/platform.wafer.space" ]; then
    echo "Error: Nginx configuration not found"
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

# Ensure nginx is running
if ! systemctl is-active --quiet nginx; then
    echo "Starting nginx..."
    systemctl start nginx
fi

# Build certbot command with all domains
echo "Expanding certificate to include all domains..."
CERTBOT_CMD="certbot certonly --webroot -w /var/www/certbot --expand"
CERTBOT_CMD="$CERTBOT_CMD -d $MAIN_DOMAIN"

# Add all Thousand Parsec domains
for domain in "${THOUSANDPARSEC_DOMAINS[@]}"; do
    CERTBOT_CMD="$CERTBOT_CMD -d $domain"
done

CERTBOT_CMD="$CERTBOT_CMD --email $EMAIL --agree-tos --no-eff-email --non-interactive"

echo "Running: $CERTBOT_CMD"
eval "$CERTBOT_CMD"

echo "✓ Certificate expanded successfully"

# Verify certificate
echo ""
echo "Verifying certificate..."
certbot certificates

# Enable HTTPS server blocks in nginx config (in case they were re-commented by nginx install)
echo ""
echo "Ensuring HTTPS server blocks are uncommented..."
NGINX_CONFIG="/etc/nginx/sites-available/platform.wafer.space"
sed -i '/^# HTTPS.*UNCOMMENTED BY SSL SETUP SCRIPT$/d' "$NGINX_CONFIG"
sed -i '/^#server {$/,/^#}$/s/^#//' "$NGINX_CONFIG"
echo "✓ HTTPS blocks uncommented"

# Test nginx configuration
echo "Testing nginx configuration..."
if ! nginx -t; then
    echo "✗ Nginx configuration test failed"
    exit 1
fi

# Reload nginx to pick up new certificate and config
echo ""
echo "Reloading nginx with updated certificate..."
if systemctl reload nginx; then
    echo "✓ Nginx reloaded successfully"
else
    echo "✗ Nginx reload failed"
    systemctl status nginx --no-pager -l
    exit 1
fi

echo ""
echo "=== SSL certificate expansion complete ==="
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
