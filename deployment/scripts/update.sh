#!/bin/bash
# Update platform.wafer.space application

set -e

APP_DIR="/home/django/platform.wafer.space"
LOG_FILE="/var/log/platform.wafer.space/update.log"

echo "$(date): Starting update..." | tee -a $LOG_FILE

# Navigate to app directory
cd $APP_DIR

# Pull latest changes
git pull origin main | tee -a $LOG_FILE

# Update dependencies
uv sync | tee -a $LOG_FILE

# Run migrations
uv run python manage.py migrate --settings=config.settings.production | tee -a $LOG_FILE

# Collect static files
uv run python manage.py collectstatic --settings=config.settings.production --noinput | tee -a $LOG_FILE

# Fix permissions after update (django owns code, www-data can read)
sudo chown -R django:www-data $APP_DIR
sudo find $APP_DIR -type d -exec chmod 750 {} \;
sudo find $APP_DIR -type f -exec chmod 640 {} \;
sudo chmod 750 $APP_DIR/manage.py
sudo chmod 640 $APP_DIR/.env

# www-data needs write access to media directory
sudo chown -R www-data:www-data $APP_DIR/wafer_space/media
sudo chmod 755 $APP_DIR/wafer_space/media

# Restart services
sudo systemctl restart django-gunicorn.service
sudo systemctl restart django-celery.service

echo "$(date): Update completed successfully" | tee -a $LOG_FILE
