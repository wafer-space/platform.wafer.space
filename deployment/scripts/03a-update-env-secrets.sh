#!/bin/bash
# Update .env file with secrets from secrets repository
# Run as: sudo ./03a-update-env-secrets.sh
# This can be run independently to update secrets without touching the database

set -e

APP_DIR="/home/django/platform.wafer.space"
ENV_FILE="$APP_DIR/.env"
SECRETS_DIR="/home/django/.secrets"

echo "=== Updating .env file with secrets ==="

# Verify .env file exists
if [ ! -f "$ENV_FILE" ]; then
    echo "Error: .env file not found at $ENV_FILE"
    echo "Run 03-setup-database.sh first to create the initial .env file"
    exit 1
fi

# Verify secrets directory exists
if [ ! -d "$SECRETS_DIR" ]; then
    echo "Error: Secrets directory not found at $SECRETS_DIR"
    echo "Run 02a-setup-secrets.sh to clone the secrets repository first"
    exit 1
fi

echo "Reading secrets from secrets repository..."

# Read Mailgun API key
if [ ! -f "$SECRETS_DIR/mailgun" ]; then
    echo "Error: Required secret file not found: $SECRETS_DIR/mailgun"
    exit 1
fi
MAILGUN_KEY=$(cat "$SECRETS_DIR/mailgun" | tr -d '\n')
if grep -q "^MAILGUN_API_KEY=" "$ENV_FILE"; then
    sed -i "s|^MAILGUN_API_KEY=.*|MAILGUN_API_KEY=$MAILGUN_KEY|" "$ENV_FILE"
else
    echo "MAILGUN_API_KEY=$MAILGUN_KEY" >> "$ENV_FILE"
fi
echo "✓ Updated Mailgun API key"

# Read GitHub OAuth secret
if [ ! -f "$SECRETS_DIR/github-oauth" ]; then
    echo "Error: Required secret file not found: $SECRETS_DIR/github-oauth"
    exit 1
fi
GITHUB_SECRET=$(cat "$SECRETS_DIR/github-oauth" | tr -d '\n')
if grep -q "^GITHUB_CLIENT_SECRET=" "$ENV_FILE"; then
    sed -i "s|^GITHUB_CLIENT_SECRET=.*|GITHUB_CLIENT_SECRET=$GITHUB_SECRET|" "$ENV_FILE"
else
    echo "GITHUB_CLIENT_SECRET=$GITHUB_SECRET" >> "$ENV_FILE"
fi
echo "✓ Updated GitHub OAuth secret"

# Read GitLab OAuth secret
if [ ! -f "$SECRETS_DIR/gitlab-oauth" ]; then
    echo "Error: Required secret file not found: $SECRETS_DIR/gitlab-oauth"
    exit 1
fi
GITLAB_SECRET=$(cat "$SECRETS_DIR/gitlab-oauth" | tr -d '\n')
if grep -q "^GITLAB_CLIENT_SECRET=" "$ENV_FILE"; then
    sed -i "s|^GITLAB_CLIENT_SECRET=.*|GITLAB_CLIENT_SECRET=$GITLAB_SECRET|" "$ENV_FILE"
else
    echo "GITLAB_CLIENT_SECRET=$GITLAB_SECRET" >> "$ENV_FILE"
fi
echo "✓ Updated GitLab OAuth secret"

# Read Google OAuth secret from JSON file
if [ ! -f "$SECRETS_DIR/google-auth.json" ]; then
    echo "Error: Required secret file not found: $SECRETS_DIR/google-auth.json"
    exit 1
fi
GOOGLE_SECRET=$(python3 -c "import json; print(json.load(open('$SECRETS_DIR/google-auth.json'))['web']['client_secret'])")
if grep -q "^GOOGLE_CLIENT_SECRET=" "$ENV_FILE"; then
    sed -i "s|^GOOGLE_CLIENT_SECRET=.*|GOOGLE_CLIENT_SECRET=$GOOGLE_SECRET|" "$ENV_FILE"
else
    echo "GOOGLE_CLIENT_SECRET=$GOOGLE_SECRET" >> "$ENV_FILE"
fi
echo "✓ Updated Google OAuth secret"

# Read Discord OAuth secret
if [ ! -f "$SECRETS_DIR/discord-oauth" ]; then
    echo "Error: Required secret file not found: $SECRETS_DIR/discord-oauth"
    exit 1
fi
DISCORD_SECRET=$(cat "$SECRETS_DIR/discord-oauth" | tr -d '\n')
if grep -q "^DISCORD_CLIENT_SECRET=" "$ENV_FILE"; then
    sed -i "s|^DISCORD_CLIENT_SECRET=.*|DISCORD_CLIENT_SECRET=$DISCORD_SECRET|" "$ENV_FILE"
else
    echo "DISCORD_CLIENT_SECRET=$DISCORD_SECRET" >> "$ENV_FILE"
fi
echo "✓ Updated Discord OAuth secret"

# Read LinkedIn OAuth secret
if [ ! -f "$SECRETS_DIR/linkedin-oauth" ]; then
    echo "Error: Required secret file not found: $SECRETS_DIR/linkedin-oauth"
    exit 1
fi
LINKEDIN_SECRET=$(cat "$SECRETS_DIR/linkedin-oauth" | tr -d '\n')
if grep -q "^LINKEDIN_CLIENT_SECRET=" "$ENV_FILE"; then
    sed -i "s|^LINKEDIN_CLIENT_SECRET=.*|LINKEDIN_CLIENT_SECRET=$LINKEDIN_SECRET|" "$ENV_FILE"
else
    echo "LINKEDIN_CLIENT_SECRET=$LINKEDIN_SECRET" >> "$ENV_FILE"
fi
echo "✓ Updated LinkedIn OAuth secret"

# Generate CELERY_BROKER_URL from DATABASE_URL
if grep -q "^DATABASE_URL=" "$ENV_FILE"; then
    DATABASE_URL=$(grep "^DATABASE_URL=" "$ENV_FILE" | cut -d'=' -f2-)
    # Convert postgres:// to postgresql:// and add sqla+ prefix
    CELERY_URL=$(echo "$DATABASE_URL" | sed 's|^postgres://|sqla+postgresql://|')
    if grep -q "^CELERY_BROKER_URL=" "$ENV_FILE"; then
        sed -i "s|^CELERY_BROKER_URL=.*|CELERY_BROKER_URL=$CELERY_URL|" "$ENV_FILE"
    else
        echo "CELERY_BROKER_URL=$CELERY_URL" >> "$ENV_FILE"
    fi
    echo "✓ Updated Celery broker URL from DATABASE_URL"
fi

# Set proper ownership and permissions
# www-data needs to read .env for Celery
chown django:www-data "$ENV_FILE"
chmod 640 "$ENV_FILE"

echo ""
echo "✓ Secrets updated successfully in $ENV_FILE"
echo ""
echo "⚠️  Remember to restart services to load the new secrets:"
echo "    sudo systemctl restart django-gunicorn.service"
echo "    sudo systemctl restart django-celery.service"
echo "    sudo systemctl restart django-celery-beat.service"
