# OAuth Secret Rotation Guide

This guide provides step-by-step instructions for rotating OAuth secrets across all providers used by the wafer.space platform.

## When to Rotate Secrets

### Immediate Rotation Required
- **Security incident**: Secret was accidentally committed to git, leaked in logs, or exposed
- **Compromised credentials**: Suspicion that a secret has been accessed by unauthorized parties
- **Team member departure**: Team member with access to secrets leaves the organization
- **Third-party breach**: OAuth provider reports a security incident

### Scheduled Rotation
- **Production secrets**: Every 90 days (recommended best practice)
- **Development secrets**: Every 180 days or when shared with new team members
- **After major updates**: When OAuth provider updates their security requirements

## Pre-Rotation Checklist

Before starting the rotation process:

- [ ] Schedule a maintenance window (recommend 30-minute window)
- [ ] Notify team members of the planned rotation
- [ ] Have access to all OAuth provider admin panels:
  - GitHub: https://github.com/organizations/wafer-space/settings/applications
  - GitLab: https://gitlab.com/groups/wafer-space/-/settings/applications
  - Google: https://console.cloud.google.com/apis/credentials
  - Discord: https://discord.com/developers/applications
  - LinkedIn: https://www.linkedin.com/developers/apps
- [ ] Have access to the secrets repository
- [ ] Have SSH access to production server
- [ ] Backup current secrets before rotation

## Secret Rotation Process

### 1. Backup Current Secrets

```bash
# On production server
sudo su - django
cd /home/django/.secrets

# Create timestamped backup
BACKUP_DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p backups
cp github-oauth backups/github-oauth.$BACKUP_DATE
cp gitlab-oauth backups/gitlab-oauth.$BACKUP_DATE
cp google-auth.json backups/google-auth.json.$BACKUP_DATE
cp discord-oauth backups/discord-oauth.$BACKUP_DATE
cp linkedin-oauth backups/linkedin-oauth.$BACKUP_DATE

# Verify backups
ls -la backups/
```

### 2. Generate New Secrets for Each Provider

#### GitHub OAuth

1. Go to https://github.com/organizations/wafer-space/settings/applications
2. Find "wafer.space Production" (or development app)
3. Click the application name
4. In the "Client secrets" section, click "Generate a new client secret"
5. **Important**: Copy the new secret immediately (it will only be shown once)
6. **Do not delete the old secret yet** - we'll do that after verifying the new one works

```bash
# Update the secret file
cd /home/django/.secrets
echo "NEW_GITHUB_SECRET_HERE" > github-oauth.new
# Verify the file
cat github-oauth.new
# Move to production (after verification step)
# mv github-oauth.new github-oauth
```

#### GitLab OAuth

1. Go to https://gitlab.com/groups/wafer-space/-/settings/applications
2. Find "wafer.space Production" (or development app)
3. Click "Edit" on the application
4. Check "Regenerate secret" checkbox
5. Click "Save application"
6. Copy the new secret from the confirmation page

```bash
# Update the secret file
cd /home/django/.secrets
echo "NEW_GITLAB_SECRET_HERE" > gitlab-oauth.new
# Verify the file
cat gitlab-oauth.new
# Move to production (after verification step)
# mv gitlab-oauth.new gitlab-oauth
```

#### Google OAuth

1. Go to https://console.cloud.google.com/apis/credentials
2. Select the wafer-space project
3. Find "wafer.space Production" OAuth 2.0 Client ID
4. Click the client ID name to open details
5. Click "Add Secret" under "Client secrets" section
6. Download the JSON file or copy the new secret
7. **Important**: Update the entire JSON file with the new secret

```bash
# Update the secret file
cd /home/django/.secrets
# Edit google-auth.json to add the new secret
# Or upload the new JSON file from Google
nano google-auth.json
# Verify the JSON is valid
python3 -c "import json; json.load(open('google-auth.json'))"
```

#### Discord OAuth

1. Go to https://discord.com/developers/applications
2. Select the "wafer-space" application
3. Go to "OAuth2" section
4. Click "Reset Secret" button
5. Confirm the reset
6. Copy the new secret immediately

```bash
# Update the secret file
cd /home/django/.secrets
echo "NEW_DISCORD_SECRET_HERE" > discord-oauth.new
# Verify the file
cat discord-oauth.new
# Move to production (after verification step)
# mv discord-oauth.new discord-oauth
```

#### LinkedIn OAuth

1. Go to https://www.linkedin.com/developers/apps
2. Select the "wafer.space" application
3. Go to "Auth" tab
4. Under "Authentication keys", find "Client secret"
5. Click "Regenerate secret"
6. Copy the new secret immediately

```bash
# Update the secret file
cd /home/django/.secrets
echo "NEW_LINKEDIN_SECRET_HERE" > linkedin-oauth.new
# Verify the file
cat linkedin-oauth.new
# Move to production (after verification step)
# mv linkedin-oauth.new linkedin-oauth
```

### 3. Update Secrets Repository

```bash
# On production server, in secrets directory
cd /home/django/.secrets

# Commit the new secrets (DO NOT commit to the main platform repository!)
git add github-oauth gitlab-oauth google-auth.json discord-oauth linkedin-oauth
git commit -m "Rotate OAuth secrets - $(date +%Y-%m-%d)"
git push

# Verify the push succeeded
git log -1
```

### 4. Update Production Environment

```bash
# On production server
sudo /home/django/platform.wafer.space/deployment/scripts/03a-update-env-secrets.sh

# Verify the .env file was updated
sudo grep -E "(GITHUB|GITLAB|GOOGLE|DISCORD|LINKEDIN)_CLIENT_SECRET" /home/django/platform.wafer.space/.env | head -c 100
# (Truncated output to avoid exposing full secrets)
```

### 5. Restart Services

```bash
# Restart all Django services to load new secrets
sudo systemctl restart django-gunicorn.service
sudo systemctl restart django-celery.service
sudo systemctl restart django-celery-beat.service

# Check service status
sudo systemctl status django-gunicorn.service
sudo systemctl status django-celery.service
sudo systemctl status django-celery-beat.service
```

### 6. Verification Testing

Test each OAuth provider to ensure the new secrets work:

#### Test OAuth Login Flow

```bash
# Access the production site
# Go to: https://platform.wafer.space/accounts/login/

# Test each provider:
# 1. Click "Sign in with GitHub"
# 2. Complete the OAuth flow
# 3. Verify successful login
# 4. Log out

# Repeat for each provider:
# - Sign in with GitLab
# - Sign in with Google
# - Sign in with Discord
# - Sign in with LinkedIn
```

#### Monitor Application Logs

```bash
# On production server
sudo journalctl -u django-gunicorn.service -f --since "5 minutes ago"

# Look for any OAuth-related errors
# Successful OAuth should show no errors in logs
```

#### Test API Endpoints

```bash
# Test that OAuth callback endpoints are working
curl -I https://platform.wafer.space/accounts/github/login/callback/
# Should return 302 or 400 (not 500)

curl -I https://platform.wafer.space/accounts/gitlab/login/callback/
curl -I https://platform.wafer.space/accounts/google/login/callback/
curl -I https://platform.wafer.space/accounts/discord/login/callback/
curl -I https://platform.wafer.space/accounts/linkedin_oauth2/login/callback/
```

### 7. Finalize Rotation

Once all tests pass and you've verified the new secrets work:

#### Move New Secrets to Production

```bash
# On production server
cd /home/django/.secrets

# For each provider, move the .new file to production
mv github-oauth.new github-oauth
mv gitlab-oauth.new gitlab-oauth
mv discord-oauth.new discord-oauth
mv linkedin-oauth.new linkedin-oauth

# Re-run the update script
sudo /home/django/platform.wafer.space/deployment/scripts/03a-update-env-secrets.sh

# Restart services again
sudo systemctl restart django-gunicorn.service django-celery.service django-celery-beat.service
```

#### Remove Old Secrets from OAuth Providers

**Only do this after confirming the new secrets work!**

1. **GitHub**: Delete the old client secret from the app settings
2. **GitLab**: Old secret is automatically invalidated when regenerated
3. **Google**: Delete the old secret from the credentials page
4. **Discord**: Old secret is automatically invalidated when reset
5. **LinkedIn**: Old secret is automatically invalidated when regenerated

#### Update Development Environments

If rotating development secrets, notify team members:

```bash
# Send notification to team
# Subject: "OAuth Secrets Rotated - Update Required"
# Body:
# "The OAuth development secrets have been rotated. Please update your .env file:
#  1. Pull the latest secrets repository
#  2. Re-run the dev setup script: python scripts/dev_setup.py
#  3. Restart your local development server
#
#  If you created personal OAuth apps, you don't need to update anything."
```

## Rollback Procedure

If the new secrets don't work or cause issues:

### Quick Rollback

```bash
# On production server
cd /home/django/.secrets

# Restore from backup (replace DATE with your backup timestamp)
BACKUP_DATE="20251012_153000"  # Use actual backup timestamp
cp backups/github-oauth.$BACKUP_DATE github-oauth
cp backups/gitlab-oauth.$BACKUP_DATE gitlab-oauth
cp backups/google-auth.json.$BACKUP_DATE google-auth.json
cp backups/discord-oauth.$BACKUP_DATE discord-oauth
cp backups/linkedin-oauth.$BACKUP_DATE linkedin-oauth

# Update environment
sudo /home/django/platform.wafer.space/deployment/scripts/03a-update-env-secrets.sh

# Restart services
sudo systemctl restart django-gunicorn.service django-celery.service django-celery-beat.service

# Verify rollback
# Test OAuth login flows again
```

### Rollback OAuth Provider Secrets

If you already deleted old secrets from the OAuth providers:

1. Generate new secrets again following the rotation process
2. The old secrets in your backup will no longer work if deleted from the provider
3. This is why we recommend **not deleting old secrets until verification is complete**

## Security Best Practices

### During Rotation

- ✅ **Always backup before rotating** - Keep timestamped backups
- ✅ **Test in staging first** - If you have a staging environment, rotate there first
- ✅ **Keep old secrets active** - Don't delete old secrets until new ones are verified
- ✅ **Rotate all secrets together** - Don't leave some secrets old while rotating others
- ✅ **Monitor after rotation** - Watch logs for 24 hours after rotation

### After Rotation

- ✅ **Delete old secrets from providers** - After verification, remove old secrets
- ✅ **Update documentation** - Note when rotation occurred
- ✅ **Archive backups securely** - Keep backups but ensure they're protected
- ✅ **Schedule next rotation** - Add calendar reminder for next scheduled rotation

### What NOT to Do

- ❌ **Never commit secrets to git** - Only commit to the dedicated secrets repository
- ❌ **Never share secrets in plaintext** - Use password managers or secure channels
- ❌ **Never skip testing** - Always verify before deleting old secrets
- ❌ **Never rotate during peak hours** - Schedule during maintenance windows
- ❌ **Never delete backups immediately** - Keep backups for at least 90 days

## Emergency Rotation

If secrets are leaked or compromised:

### Immediate Actions (< 5 minutes)

1. **Generate new secrets immediately** on all OAuth providers
2. **Update secrets repository** with new secrets
3. **Deploy to production** without waiting for maintenance window
4. **Restart all services**

### Follow-up Actions (< 1 hour)

1. **Test all OAuth flows** to ensure system is working
2. **Monitor logs** for any unauthorized access attempts
3. **Review access logs** on OAuth providers for suspicious activity
4. **Document the incident** including timeline and affected secrets

### Post-Incident (< 24 hours)

1. **Conduct security review** to understand how the leak occurred
2. **Implement preventive measures** (e.g., pre-commit hooks, secret scanning)
3. **Notify stakeholders** if user data was potentially accessed
4. **Update runbooks** with lessons learned

## Rotation Log Template

Keep a log of all secret rotations:

```
Date: 2025-10-12
Rotated by: Tim Ansell
Reason: Scheduled 90-day rotation
Secrets rotated:
  - GitHub OAuth (Production)
  - GitLab OAuth (Production)
  - Google OAuth (Production)
  - Discord OAuth (Production)
  - LinkedIn OAuth (Production)
Issues: None
Verification: All OAuth flows tested successfully
Next rotation: 2026-01-10
```

## Automation Considerations

### Future Improvements

Consider automating parts of the rotation process:

1. **Automated backup**: Cron job to backup secrets daily
2. **Rotation reminders**: Calendar notifications 1 week before scheduled rotation
3. **Verification testing**: Automated OAuth flow testing
4. **Secret expiry monitoring**: Alert when secrets are approaching rotation deadline

### Security Scanning

Implement automated secret scanning:

- Use GitHub's secret scanning on repositories
- Add pre-commit hooks to prevent secret commits (Issue #28)
- Run periodic scans of logs and configuration files

## Support and Questions

- **Security incidents**: Contact @mithro immediately
- **Rotation assistance**: Create private issue on GitHub
- **OAuth provider issues**: Check provider status pages first:
  - GitHub: https://www.githubstatus.com/
  - GitLab: https://status.gitlab.com/
  - Google: https://www.google.com/appsstatus
  - Discord: https://discordstatus.com/
  - LinkedIn: https://www.linkedin-apistatus.com/

---

**Remember**: It's better to rotate secrets proactively than to respond to a security incident. When in doubt, rotate.
