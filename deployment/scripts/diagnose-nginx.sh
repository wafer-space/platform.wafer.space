#!/bin/bash
# Diagnostic script to check why nginx isn't blocking localhost requests
# Run as: sudo ./diagnose-nginx.sh

set -e

echo "=== Nginx Configuration Diagnostic ==="
echo ""

# Check if nginx is running
echo "1. Checking if nginx is running..."
if systemctl is-active --quiet nginx; then
    echo "   ✓ Nginx is running"
else
    echo "   ✗ Nginx is NOT running"
    systemctl status nginx --no-pager -l
    exit 1
fi
echo ""

# Check for multiple default_server declarations
echo "2. Checking for conflicting default_server declarations..."
echo "   Searching all enabled nginx configs for 'default_server':"
grep -r "default_server" /etc/nginx/sites-enabled/ 2>/dev/null || echo "   (no matches found)"
echo ""

# Check which config files are enabled
echo "3. Listing enabled nginx sites:"
ls -la /etc/nginx/sites-enabled/
echo ""

# Check if our config is properly linked
echo "4. Checking if platform.wafer.space config is enabled:"
if [ -L /etc/nginx/sites-enabled/platform.wafer.space ]; then
    echo "   ✓ Config is enabled (symlinked)"
    echo "   Target: $(readlink -f /etc/nginx/sites-enabled/platform.wafer.space)"
else
    echo "   ✗ Config is NOT enabled"
fi
echo ""

# Show the actual default_server block from our config
echo "5. Checking our HTTP default_server block:"
if [ -f /etc/nginx/sites-available/platform.wafer.space ]; then
    echo "   First 15 lines of config:"
    head -n 15 /etc/nginx/sites-available/platform.wafer.space
else
    echo "   ✗ Config file not found!"
fi
echo ""

# Test nginx configuration
echo "6. Testing nginx configuration:"
if nginx -t 2>&1; then
    echo "   ✓ Nginx configuration is valid"
else
    echo "   ✗ Nginx configuration has errors"
fi
echo ""

# Check when nginx was last reloaded
echo "7. Checking when nginx was last reloaded:"
systemctl status nginx --no-pager -l | grep -A 5 "Active:"
echo ""

# Try to make a test request
echo "8. Testing localhost request (simulating the problematic request):"
echo "   Making request to http://localhost/health/"
RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost/health/ 2>&1 || echo "failed")
if [ "$RESPONSE" = "000" ] || [ "$RESPONSE" = "failed" ]; then
    echo "   ✓ Connection refused/closed (nginx is blocking it correctly)"
elif [ "$RESPONSE" = "400" ]; then
    echo "   ✓ 400 Bad Request (nginx is handling it, Django rejected ALLOWED_HOSTS)"
    echo "   ⚠ This means the request IS reaching Django through nginx"
elif [ "$RESPONSE" = "444" ]; then
    echo "   ✓ 444 (connection closed - nginx blocking correctly)"
else
    echo "   ⚠ HTTP $RESPONSE - unexpected response"
    echo "   This means the request is getting through somehow"
fi
echo ""

# Check if gunicorn socket is accessible
echo "9. Checking gunicorn socket:"
if [ -S /run/platform.wafer.space/gunicorn.sock ]; then
    echo "   ✓ Gunicorn socket exists"
    ls -la /run/platform.wafer.space/gunicorn.sock
else
    echo "   ✗ Gunicorn socket not found"
fi
echo ""

# Check nginx error logs for recent entries
echo "10. Recent nginx error log entries (last 10):"
if [ -f /var/log/nginx/error.log ]; then
    tail -n 10 /var/log/nginx/error.log
else
    echo "    No error log found"
fi
echo ""

echo "=== Diagnostic complete ==="
echo ""
echo "Common issues and fixes:"
echo "1. If multiple default_server found: Remove/disable conflicting configs"
echo "2. If config not enabled: Run 'cd ../nginx && sudo ./install.sh'"
echo "3. If config outdated: Copy latest config and reload nginx"
echo "4. If nginx not reloaded: Run 'sudo systemctl reload nginx'"
