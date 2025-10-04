#!/bin/bash
# Setup wildcard SSL certificate with Let's Encrypt using DNS validation
# Run as: sudo ./05b-setup-wildcard-ssl.sh
#
# IMPORTANT: This script requires manual DNS TXT record configuration
# You will need to add DNS TXT records during the certificate request process

set -e

MAIN_DOMAIN="platform.wafer.space"
EMAIL="bot@wafer.space"

# Wildcard domains (requires DNS validation)
WILDCARD_DOMAINS=(
    "*.thousandparsec.com"
    "thousandparsec.com"
    "*.thousandparsec.net"
    "thousandparsec.net"
    "*.thousandparsec.org"
    "thousandparsec.org"
)

echo "=== Setting up wildcard SSL certificate ==="
echo "Main domain: $MAIN_DOMAIN"
echo "Wildcard domains: ${WILDCARD_DOMAINS[*]}"
echo "Email: $EMAIL"
echo ""
echo "IMPORTANT: Wildcard certificates require DNS validation."
echo "You will be prompted to add TXT records to your DNS during this process."
echo ""
read -r -p "Press Enter to continue or Ctrl+C to cancel..."
echo ""

# Check if certificate already exists
if [ -d "/etc/letsencrypt/live/$MAIN_DOMAIN" ]; then
    echo "Certificate already exists for $MAIN_DOMAIN"
    echo "This will expand the certificate to include wildcard domains."
    echo ""
    read -p "Continue? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 0
    fi
fi

# Build certbot command with all domains using DNS validation
echo "Requesting wildcard SSL certificate..."
CERTBOT_CMD="certbot certonly --manual --preferred-challenges dns"
CERTBOT_CMD="$CERTBOT_CMD -d $MAIN_DOMAIN"

# Add all wildcard domains
for domain in "${WILDCARD_DOMAINS[@]}"; do
    CERTBOT_CMD="$CERTBOT_CMD -d $domain"
done

CERTBOT_CMD="$CERTBOT_CMD --email $EMAIL --agree-tos --no-eff-email"

echo "Running: $CERTBOT_CMD"
echo ""
echo "You will be prompted to add DNS TXT records for domain validation."
echo "Follow the instructions carefully and add the records before continuing."
echo ""

eval "$CERTBOT_CMD"

echo ""
echo "✓ Certificate obtained for all domains including wildcards"

# Verify certificate
echo ""
echo "Verifying certificate..."
certbot certificates

# Update nginx configuration if it exists
NGINX_CONFIG="/etc/nginx/sites-available/platform.wafer.space"
if [ -f "$NGINX_CONFIG" ]; then
    # Check if HTTPS blocks are already uncommented
    if grep -q "^#server {$" "$NGINX_CONFIG"; then
        echo ""
        echo "Enabling HTTPS server blocks in nginx configuration..."
        # Remove the marker comments and uncomment the HTTPS blocks
        sed -i '/^# HTTPS.*UNCOMMENTED BY SSL SETUP SCRIPT$/d' "$NGINX_CONFIG"
        sed -i '/^#server {$/,/^#}$/s/^#//' "$NGINX_CONFIG"

        echo "Testing nginx configuration..."
        nginx -t

        echo "Reloading nginx..."
        systemctl reload nginx
        echo "✓ Nginx configuration updated and reloaded"
    else
        echo ""
        echo "HTTPS blocks already enabled in nginx configuration"
        echo "Reloading nginx to pick up new certificate..."
        systemctl reload nginx
    fi
fi

echo ""
echo "=== Wildcard SSL certificate setup complete ==="
echo "Certificate: /etc/letsencrypt/live/$MAIN_DOMAIN/fullchain.pem"
echo "Private key: /etc/letsencrypt/live/$MAIN_DOMAIN/privkey.pem"
echo ""
echo "Domains covered by this certificate:"
echo "  - $MAIN_DOMAIN"
for domain in "${WILDCARD_DOMAINS[@]}"; do
    echo "  - $domain"
done
echo ""
echo "NOTE: Wildcard certificates require DNS validation and must be renewed manually"
echo "or with automated DNS API integration. Auto-renewal via webroot is not possible."
echo ""
echo "To renew manually:"
echo "  sudo certbot renew --manual --preferred-challenges dns"
echo ""
