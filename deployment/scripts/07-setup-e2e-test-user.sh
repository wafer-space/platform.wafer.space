#!/bin/bash
# Setup E2E test user for automated verification
# Run as: sudo ./07-setup-e2e-test-user.sh
#
# This script creates or updates a test user for the E2E verification script.
# The password is read from the secrets repository.
#
# Prerequisites:
#   - Secrets repository must be set up (02a-setup-secrets.sh)
#   - Secret file must exist: /home/django/.secrets/e2e-test-password

set -e

# Auto-detect environment
source "$(dirname "$0")/detect-environment.sh"

echo "=== Setting up E2E test user ($ENV_NAME environment) ==="

# Verify secrets directory exists
if [ ! -d "$SECRETS_DIR" ]; then
    echo "Error: Secrets directory not found at $SECRETS_DIR"
    echo "Run 02a-setup-secrets.sh to clone the secrets repository first"
    exit 1
fi

# Read E2E test password from secrets repository
E2E_SECRET_FILE="$SECRETS_DIR/test-user"
if [ ! -f "$E2E_SECRET_FILE" ]; then
    echo "Error: E2E test password file not found: $E2E_SECRET_FILE"
    echo ""
    echo "To create the secret file in the secrets repository:"
    echo "  1. cd /home/django/.secrets"
    echo "  2. echo 'your-secure-password' > test-user"
    echo "  3. git add test-user"
    echo "  4. git commit -m 'Add E2E test user password'"
    echo "  5. git push"
    echo ""
    echo "Then run this script again."
    exit 1
fi

E2E_TEST_PASSWORD=$(cat "$E2E_SECRET_FILE" | tr -d '\n')

if [ -z "$E2E_TEST_PASSWORD" ]; then
    echo "Error: E2E test password file is empty: $E2E_SECRET_FILE"
    exit 1
fi

echo "Creating/updating E2E test user..."

# Run the Django management command as the django user
cd "$APP_DIR"
export DJANGO_SETTINGS_MODULE
export E2E_TEST_PASSWORD
sudo -u "$DJANGO_USER" -E \
    /home/django/.local/bin/uv run python manage.py create_e2e_test_user

echo ""
echo "=== E2E test user setup complete ==="
echo ""
echo "To run E2E verification:"
echo "  uv run python -m scripts.e2e_verify https://$MAIN_DOMAIN"
echo ""
echo "Note: Update scripts/e2e_verify/main.py with the password from secrets"
