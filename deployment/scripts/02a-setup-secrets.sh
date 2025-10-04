#!/bin/bash
# Setup secrets repository
# Run as: sudo ./02a-setup-secrets.sh

set -e

SECRETS_REPO="git+ssh://github.com/mithro/platform.wafer.space-secrets.git"
SECRETS_DIR="/home/django/.secrets"
DJANGO_USER="django"

echo "=== Setting up secrets repository ==="

# Clone or update secrets repository
if [ -d "$SECRETS_DIR/.git" ]; then
    echo "Updating secrets repository..."
    sudo -u "$DJANGO_USER" git -C "$SECRETS_DIR" pull
    echo "✓ Secrets repository updated"
else
    echo "Cloning secrets repository..."
    sudo -u "$DJANGO_USER" git clone "$SECRETS_REPO" "$SECRETS_DIR"
    echo "✓ Secrets repository cloned to $SECRETS_DIR"
fi

# Set proper permissions
chmod 700 "$SECRETS_DIR"
chown -R "$DJANGO_USER:$DJANGO_USER" "$SECRETS_DIR"

echo "✓ Secrets repository setup complete"
