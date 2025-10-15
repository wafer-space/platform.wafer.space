#!/bin/bash
# Fix nginx default_server configuration to block unknown hosts
# Run as: sudo ./fix-nginx-default-server.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NGINX_DIR="$(cd "$SCRIPT_DIR/../nginx" && pwd)"
CONFIG_SOURCE="$NGINX_DIR/platform.wafer.space.conf"
CONFIG_NAME="platform.wafer.space"
SITES_AVAILABLE="/etc/nginx/sites-available"
SITES_ENABLED="/etc/nginx/sites-enabled"

echo "=== Fixing nginx default_server configuration ==="
echo ""

# Step 1: Remove conflicting default server configs
echo "1. Removing conflicting default server configurations..."

# Remove default nginx site
if [ -f "$SITES_ENABLED/default" ] || [ -L "$SITES_ENABLED/default" ]; then
    echo "   Removing /etc/nginx/sites-enabled/default"
    rm -f "$SITES_ENABLED/default"
    echo "   ✓ Removed default site"
else
    echo "   ✓ No default site found (already removed)"
fi

# Check for other configs with default_server
echo "   Checking for other default_server declarations..."
if grep -r "listen.*default_server" "$SITES_ENABLED"/* 2>/dev/null | grep -v "$CONFIG_NAME"; then
    echo "   ⚠ WARNING: Found other configs with default_server:"
    grep -r "listen.*default_server" "$SITES_ENABLED"/* 2>/dev/null | grep -v "$CONFIG_NAME" || true
    echo ""
    echo "   You may need to manually review and remove these configs."
    echo "   Press Ctrl+C to abort, or Enter to continue..."
    read -r
else
    echo "   ✓ No conflicting default_server found"
fi
echo ""

# Step 2: Install/update our config
echo "2. Installing platform.wafer.space configuration..."

if [ ! -f "$CONFIG_SOURCE" ]; then
    echo "   ✗ Error: Config source not found at $CONFIG_SOURCE"
    exit 1
fi

# Copy config to sites-available
echo "   Copying config to $SITES_AVAILABLE/$CONFIG_NAME"
cp "$CONFIG_SOURCE" "$SITES_AVAILABLE/$CONFIG_NAME"
echo "   ✓ Config copied"

# Create symlink in sites-enabled
if [ -L "$SITES_ENABLED/$CONFIG_NAME" ]; then
    echo "   ✓ Config already enabled"
else
    echo "   Enabling config..."
    ln -s "$SITES_AVAILABLE/$CONFIG_NAME" "$SITES_ENABLED/$CONFIG_NAME"
    echo "   ✓ Config enabled"
fi
echo ""

# Step 3: Verify the config has default_server
echo "3. Verifying default_server directives in config..."
if grep -q "listen.*80.*default_server" "$SITES_AVAILABLE/$CONFIG_NAME"; then
    echo "   ✓ HTTP default_server directive found"
else
    echo "   ✗ HTTP default_server directive NOT found - config may be outdated"
    exit 1
fi

if grep -q "listen.*443.*default_server" "$SITES_AVAILABLE/$CONFIG_NAME"; then
    echo "   ✓ HTTPS default_server directive found (commented or active)"
else
    echo "   ⚠ HTTPS default_server directive NOT found"
fi
echo ""

# Step 4: Test nginx configuration
echo "4. Testing nginx configuration..."
if nginx -t 2>&1; then
    echo "   ✓ Nginx configuration is valid"
else
    echo "   ✗ Nginx configuration test failed"
    echo ""
    echo "   Please review the errors above and fix the configuration."
    exit 1
fi
echo ""

# Step 5: Reload nginx
echo "5. Reloading nginx..."
if systemctl reload nginx; then
    echo "   ✓ Nginx reloaded successfully"
else
    echo "   ✗ Nginx reload failed"
    systemctl status nginx --no-pager -l
    exit 1
fi
echo ""

# Step 6: Test that localhost is blocked
echo "6. Testing that localhost requests are blocked..."
sleep 1  # Give nginx a moment to reload
RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost/health/ 2>&1 || echo "000")

if [ "$RESPONSE" = "000" ]; then
    echo "   ✓ Connection refused/closed (nginx is blocking correctly!)"
    echo ""
    echo "=== SUCCESS ==="
    echo "Localhost and unknown domains are now blocked by nginx."
    echo "They will not reach the Django application."
elif [ "$RESPONSE" = "444" ]; then
    echo "   ✓ 444 response (nginx is blocking correctly!)"
    echo ""
    echo "=== SUCCESS ==="
    echo "Localhost and unknown domains are now blocked by nginx."
elif [ "$RESPONSE" = "400" ]; then
    echo "   ✗ 400 Bad Request - request is still reaching Django!"
    echo ""
    echo "   This means nginx is NOT blocking the request properly."
    echo "   Please run the diagnostic script to investigate:"
    echo "   sudo $SCRIPT_DIR/diagnose-nginx.sh"
    exit 1
else
    echo "   ⚠ Unexpected response: HTTP $RESPONSE"
    echo "   Please run the diagnostic script to investigate:"
    echo "   sudo $SCRIPT_DIR/diagnose-nginx.sh"
fi
echo ""

echo "Next steps:"
echo "1. Monitor Django error emails to confirm localhost errors stop"
echo "2. If issues persist, run: sudo $SCRIPT_DIR/diagnose-nginx.sh"
echo ""
