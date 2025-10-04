#!/bin/bash
# Update platform.wafer.space application

set -e

APP_DIR="/home/django/platform.wafer.space"
SECRETS_DIR="/home/django/.secrets"
LOG_FILE="/var/log/platform.wafer.space/update.log"

# Use production settings
export DJANGO_SETTINGS_MODULE=config.settings.production

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

# Fix permissions after update (django owns code, www-data can read)
sudo chown -R django:www-data "$APP_DIR"
sudo find "$APP_DIR" -type d -exec chmod 750 {} \;
sudo find "$APP_DIR" -type f -exec chmod 640 {} \;
sudo chmod 750 "$APP_DIR/manage.py"
sudo chmod 640 "$APP_DIR/.env"

# www-data needs write access to media directory
sudo chown -R www-data:www-data "$APP_DIR/wafer_space/media"
sudo chmod 755 "$APP_DIR/wafer_space/media"

# Restart services
sudo systemctl restart django-gunicorn.service
sudo systemctl restart django-celery.service

echo "$(date): Update completed successfully" | tee -a "$LOG_FILE"
