#!/bin/bash
# Update platform.wafer.space application

set -e

APP_DIR="/home/django/platform.wafer.space"
SECRETS_DIR="/home/django/.secrets"
LOG_FILE="/var/log/platform.wafer.space/update.log"

# Use production settings
export DJANGO_SETTINGS_MODULE=config.settings.prod

echo "$(date): Starting update..." | tee -a "$LOG_FILE"

# Navigate to app directory
cd "$APP_DIR" || exit

# Pull latest changes
git pull origin main | tee -a "$LOG_FILE"

# Update secrets repository if it exists
if [ -d "$SECRETS_DIR/.git" ]; then
    echo "$(date): Updating secrets repository..." | tee -a "$LOG_FILE"
    sudo -u django git -C "$SECRETS_DIR" pull | tee -a "$LOG_FILE"
else
    echo "$(date): Warning: Secrets directory not found or not a git repository" | tee -a "$LOG_FILE"
fi

# Update dependencies
make venv | tee -a "$LOG_FILE"

# Run migrations
make migrate | tee -a "$LOG_FILE"

# Collect static files
make collectstatic | tee -a "$LOG_FILE"

# Fix permissions after update - run the permissions script
sudo "$APP_DIR/deployment/scripts/04-setup-permissions.sh"

# Restart services
sudo systemctl restart django-gunicorn.service
sudo systemctl restart 'django-celery-*.service'

echo "$(date): Update completed successfully" | tee -a "$LOG_FILE"
