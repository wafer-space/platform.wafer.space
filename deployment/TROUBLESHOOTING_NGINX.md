# Nginx Troubleshooting Guide

## Issue: Unknown Hosts (localhost) Reaching Django Application

### Symptoms

You receive Django error emails like:
```
Invalid HTTP_HOST header: 'localhost'. You may need to add 'localhost' to ALLOWED_HOSTS.

DisallowedHost at /health/
Invalid HTTP_HOST header: 'localhost'. You may need to add 'localhost' to ALLOWED_HOSTS.

Request Method: GET
Request URL: http://localhost/health/
```

### Root Cause

The nginx `default_server` configuration is not properly blocking requests to unknown hosts (like `localhost`, IP addresses, or random domain names). This happens when:

1. **Conflicting default_server**: Another nginx configuration file has a `default_server` directive that takes precedence
2. **Missing configuration**: The platform.wafer.space nginx config hasn't been installed or updated
3. **Not reloaded**: Nginx hasn't been reloaded after configuration changes
4. **Bypassing nginx**: Something is connecting directly to the gunicorn socket (rare)

### Quick Fix

Run the fix script on your production server:

```bash
cd /path/to/platform.wafer.space/deployment/scripts
sudo ./fix-nginx-default-server.sh
```

This script will:
1. Remove conflicting default_server configurations (like `/etc/nginx/sites-enabled/default`)
2. Install/update the platform.wafer.space nginx configuration
3. Reload nginx
4. Test that localhost requests are now blocked

### Diagnostic Steps

If the quick fix doesn't work, run the diagnostic script:

```bash
cd /path/to/platform.wafer.space/deployment/scripts
sudo ./diagnose-nginx.sh
```

This will check:
- Whether nginx is running
- If there are conflicting `default_server` declarations
- Which config files are enabled
- If our config is properly linked
- The actual default_server block configuration
- Whether nginx configuration is valid
- When nginx was last reloaded
- Test requests to localhost
- Gunicorn socket status
- Recent nginx error logs

### Understanding the Default Server Configuration

The platform.wafer.space nginx config includes two `default_server` blocks:

**HTTP Default Server (Always Active):**
```nginx
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    # Return 444 (connection closed without response) for unknown domains
    return 444;
}
```

**HTTPS Default Server (Active After SSL Setup):**
```nginx
server {
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    http2 on;
    server_name _;

    # Use platform.wafer.space SSL certs for default server
    ssl_certificate /etc/letsencrypt/live/platform.wafer.space/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/platform.wafer.space/privkey.pem;

    # Return 444 (connection closed without response) for unknown domains
    return 444;
}
```

These blocks catch ALL requests that don't match any specific `server_name` directive and close the connection without sending a response (HTTP 444).

### Common Issues and Solutions

#### 1. Conflicting Default Server

**Problem:** Another nginx config file (usually `/etc/nginx/sites-enabled/default`) has a `default_server` directive.

**Solution:**
```bash
# Remove the default nginx site
sudo rm /etc/nginx/sites-enabled/default

# Reload nginx
sudo systemctl reload nginx
```

#### 2. Nginx Not Reloaded

**Problem:** Configuration changes haven't been applied.

**Solution:**
```bash
# Test configuration
sudo nginx -t

# Reload nginx
sudo systemctl reload nginx
```

#### 3. Outdated Configuration

**Problem:** The nginx config on the server is older than the one in the repository.

**Solution:**
```bash
cd /path/to/platform.wafer.space/deployment/nginx
sudo ./install.sh
```

#### 4. Multiple Default Servers (Advanced)

**Problem:** Multiple config files declare `default_server` for the same port.

**Diagnosis:**
```bash
# Find all default_server declarations
grep -r "listen.*default_server" /etc/nginx/sites-enabled/
```

**Solution:** Remove or modify conflicting configs to remove their `default_server` directives.

### Prevention

To prevent this issue in the future:

1. **Use the install script:** Always use `deployment/nginx/install.sh` to install nginx configuration. It now checks for conflicts.

2. **Verify after installation:** The install script now tests that the default_server is working correctly.

3. **Monitor Django errors:** Set up Django error email notifications to catch these issues early.

4. **Regular audits:** Periodically run the diagnostic script to ensure configuration is correct.

### Testing the Fix

After applying the fix, test that unknown hosts are blocked:

```bash
# Test HTTP request to localhost
curl -v http://localhost/

# Expected result: Connection refused or HTTP 444
# Bad result: Any response from Django (400, 500, etc.)
```

```bash
# Test HTTPS request to localhost (if SSL is set up)
curl -v https://localhost/

# Expected result: Connection refused or HTTP 444
```

### Security Implications

**Why this matters:**

1. **Reduces attack surface:** Unknown hosts can't trigger Django code execution
2. **Prevents information leakage:** Django error pages won't be shown to attackers
3. **Reduces noise:** No Django error emails for port scans and random requests
4. **Performance:** Requests are rejected at nginx level, not Django

**Best practices:**

- Keep `ALLOWED_HOSTS` in Django restricted to only your actual domain(s)
- Use nginx `default_server` to catch and reject unknown hosts
- Monitor both nginx and Django logs for suspicious activity
- Keep nginx and Django configurations in sync

### Related Files

- `deployment/nginx/platform.wafer.space.conf` - Main nginx configuration
- `deployment/nginx/install.sh` - Nginx installation script (improved with conflict detection)
- `deployment/scripts/diagnose-nginx.sh` - Diagnostic script
- `deployment/scripts/fix-nginx-default-server.sh` - Automated fix script
- `config/settings/production.py` - Django ALLOWED_HOSTS configuration

### Further Reading

- [Nginx Server Blocks](https://nginx.org/en/docs/http/ngx_http_core_module.html#server)
- [Django ALLOWED_HOSTS](https://docs.djangoproject.com/en/stable/ref/settings/#allowed-hosts)
- [Security Best Practices for Django](https://docs.djangoproject.com/en/stable/topics/security/)
