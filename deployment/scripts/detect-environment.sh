#!/bin/bash
# Auto-detect deployment environment based on hostname
# Source this file in other scripts: source "$(dirname "$0")/detect-environment.sh"

HOSTNAME=$(hostname -f)

if [[ "$HOSTNAME" == *"test-platform"* ]]; then
    # Staging environment
    ENV_NAME="stage"
    DJANGO_SETTINGS_MODULE="config.settings.stage"
    SECRETS_REPO="git@github.com:mithro/test-platform.wafer.space-secrets.git"
    ENV_TEMPLATE=".env.stage.template"
    MAIN_DOMAIN="test-platform.wafer.space"
elif [[ "$HOSTNAME" == *"platform"* ]] || [[ "$HOSTNAME" == "platform.wafer.space" ]]; then
    # Production environment
    ENV_NAME="prod"
    DJANGO_SETTINGS_MODULE="config.settings.prod"
    SECRETS_REPO="git@github.com:mithro/platform.wafer.space-secrets.git"
    ENV_TEMPLATE=".env.prod.template"
    MAIN_DOMAIN="platform.wafer.space"
else
    echo "Error: Cannot auto-detect environment from hostname: $HOSTNAME"
    echo "Expected hostname to contain 'test-platform' (staging) or 'platform' (production)"
    exit 1
fi

# Common settings (same on both servers)
APP_DIR="/home/django/platform.wafer.space"
DB_NAME="platform_wafer_space"
DB_USER="platform_wafer_space"
LOG_DIR="/var/log/platform.wafer.space"
RUN_DIR="/run/platform.wafer.space"
BACKUP_PREFIX="platform_wafer_space"
SECRETS_DIR="/home/django/.secrets"
DJANGO_USER="django"

# Export for use in scripts
export ENV_NAME DJANGO_SETTINGS_MODULE SECRETS_REPO ENV_TEMPLATE MAIN_DOMAIN
export APP_DIR DB_NAME DB_USER LOG_DIR RUN_DIR BACKUP_PREFIX SECRETS_DIR DJANGO_USER
