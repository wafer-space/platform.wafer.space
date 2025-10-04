# Troubleshooting Guide

This document provides solutions to common issues you may encounter during development.

## OAuth Authentication Issues

### MultipleObjectsReturned Error on Login Page

**Error:**
```
MultipleObjectsReturned at /accounts/login/
No exception message supplied
```

**Cause:**
This happens when there are duplicate SocialApp objects in the database, typically from running unit tests that create test SocialApp objects.

**Solution:**
Clean up duplicate SocialApp objects from the database:

```bash
# Method 1: Using Django shell
uv run python manage.py shell -c "
from allauth.socialaccount.models import SocialApp
SocialApp.objects.all().delete()
print('Cleaned up SocialApp objects')
"

# Method 2: Reset the database entirely (WARNING: loses all data)
make db-reset
```

**Prevention:**
- Unit tests automatically clean up their SocialApp objects in `tearDown()` methods
- If tests are interrupted, they may leave objects behind
- Always run tests to completion when possible

### Third-Party Login Failure Error

**Error:**
```
Third-Party Login Failure
An error occurred while attempting to login via your third-party account.
```

**Cause:**
This error occurs when you try to login with a different OAuth provider (e.g., GitLab) after previously signing up with another provider (e.g., GitHub) using the same email address.

**Why This Happens:**
- You signed up with GitHub using `user@example.com`
- Later, you try to login with GitLab using the same `user@example.com`
- The system doesn't automatically link the accounts, causing an error

**Solution:**
The platform is now configured to automatically link multiple OAuth providers with the same verified email address. This is enabled via:

```python
# config/settings/base.py
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True
```

**Expected Behavior:**
- ✅ Use any OAuth provider (GitHub, GitLab, Google) with the same email
- ✅ Accounts automatically link when emails match
- ✅ No need to remember which provider you used originally
- ✅ Seamlessly switch between providers

**If You Still See This Error:**
1. **Clear your session**: Logout completely and try again
2. **Use password reset**: If you have a local account, reset your password and login traditionally
3. **Check email verification**: Ensure the email from the OAuth provider is verified
4. **Contact support**: If the issue persists, create a GitHub issue with details

**Related Issue:** See [Issue #22](https://github.com/wafer-space/platform.wafer.space/issues/22) for technical details.

### OAuth Configuration Issues

**OAuth button not appearing:**
1. Check that the secret is configured in `.env`
2. Verify the development server is reading the `.env` file
3. Ensure no duplicate SocialApp objects exist in the database

**OAuth redirect fails:**
1. Verify the callback URL in your GitHub OAuth app matches:
   - Development: `http://localhost:8081/accounts/github/login/callback/`
   - Production: `https://platform.wafer.space/accounts/github/login/callback/`
2. Check that the Client ID and Secret are correctly configured

### Testing OAuth Flow

**Check if OAuth is configured correctly:**
```bash
# Test configuration loading
uv run python manage.py shell -c "
from django.conf import settings
github_config = settings.SOCIALACCOUNT_PROVIDERS['github']['APP']
print(f'Client ID: {github_config[\"client_id\"]}')
print(f'Secret configured: {\"Yes\" if github_config[\"secret\"] else \"No\"}')
"

# Test login page loads
curl -s http://localhost:8081/accounts/login/ | grep -i github

# Test OAuth redirect (don't follow redirect)
curl -s -I http://localhost:8081/accounts/github/login/ | head -5
```

## Database Issues

### Migration Problems

**Error: No such table exists**
```bash
# Run migrations
make migrate

# If migrations are corrupted, reset database (WARNING: loses data)
make db-reset
```

**Circular migration dependencies:**
```bash
# Check migration status
uv run python manage.py showmigrations

# If needed, create a merge migration
uv run python manage.py makemigrations --merge
```

## Development Server Issues

### Port Already in Use

**Error: `[Errno 48] Address already in use`**
```bash
# Find process using port 8081
lsof -i :8081

# Kill the process (replace PID with actual process ID)
kill -9 <PID>

# Or use a different port
uv run python manage.py runserver 8082
```

### Static Files Not Loading

```bash
# Collect static files
make collectstatic

# Check static file configuration
uv run python manage.py shell -c "
from django.conf import settings
print(f'STATIC_URL: {settings.STATIC_URL}')
print(f'STATIC_ROOT: {settings.STATIC_ROOT}')
"
```

## Testing Issues

### Browser Tests Failing

**Ensure you're using headless mode:**
```bash
# ✅ Correct
make test-browser-headless

# ❌ Wrong - will fail in Claude Code
make test-browser
```

**Chrome/Firefox not found:**
```bash
# Install Chrome on Ubuntu/Debian
wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | sudo apt-key add -
sudo sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list'
sudo apt update
sudo apt install google-chrome-stable

# Install Firefox
sudo apt install firefox
```

### Test Database Issues

**Tests creating real SocialApp objects:**
- Tests should clean up in `tearDown()` methods
- Check that `@pytest.mark.django_db` is used appropriately
- Verify test isolation with database transactions

## Code Quality Issues

### Linting Failures

```bash
# Fix most linting issues automatically
make lint-fix

# Check specific linting errors
make lint

# Type checking issues
make type-check
```

### Import Errors

**Circular imports:**
- Review the architecture guidelines in `CLAUDE.md`
- Move business logic to appropriate layers
- Avoid importing tasks in models

**Module not found:**
```bash
# Reinstall dependencies
make clean-venv
make venv
```

## Environment Issues

### .env File Not Being Read

**Check if environment loading is working:**
```bash
# Verify .env file exists
ls -la .env

# Check if Django is reading it
uv run python manage.py shell -c "
import os
print(f'GITHUB_CLIENT_SECRET set: {bool(os.environ.get(\"GITHUB_CLIENT_SECRET\"))}')
"
```

### Python Version Issues

**Ensure you're using Python 3.13.7:**
```bash
# Check Python version
python --version
uv python list

# Use correct Python version
uv python install 3.13.7
```

## Production Issues

### HTTPS Required for OAuth

**OAuth providers require HTTPS in production:**
- Ensure SSL/TLS is properly configured
- Update OAuth app callback URLs to use `https://`
- Check that `SECURE_SSL_REDIRECT = True` in production settings

### Static Files in Production

```bash
# Collect static files
make collectstatic

# Verify WhiteNoise configuration
grep -r "WhiteNoise" config/settings/
```

## Getting Help

### Debug Information

**Collect debug information for issue reports:**
```bash
# Django version and settings
uv run python manage.py shell -c "
import django
from django.conf import settings
print(f'Django version: {django.get_version()}')
print(f'Debug mode: {settings.DEBUG}')
print(f'Database: {settings.DATABASES[\"default\"][\"ENGINE\"]}')
"

# Python and package versions
uv run python --version
uv pip list | grep -E "(django|allauth|pytest)"

# Environment information
uname -a
```

### Useful Commands for Debugging

```bash
# Check all URL patterns
make show-urls

# Test deployment readiness
make check-deploy

# Comprehensive health check
make check-all

# Clean everything and start fresh
make clean-all
make venv
make migrate
```

### Community Resources

- **Django-allauth Documentation**: https://docs.allauth.org/
- **Django Documentation**: https://docs.djangoproject.com/
- **Project Issues**: Create an issue on GitHub with debug information
- **Security Issues**: Follow the security policy in the repository

---

💡 **Tip**: When reporting issues, always include the output of relevant debug commands and describe the steps to reproduce the problem.