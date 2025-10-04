#!/bin/bash
# Helper script to load .env file for manual testing
# This handles systemd EnvironmentFile format (no quotes)
# Usage: source deployment/scripts/load-env.sh

ENV_FILE="/home/django/platform.wafer.space/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "Error: .env file not found at $ENV_FILE"
    return 1
fi

# Read .env file and export variables, handling systemd EnvironmentFile format
# This is more robust than 'source .env' for the no-quotes format
while IFS='=' read -r key value; do
    # Skip empty lines and comments
    [[ -z "$key" || "$key" =~ ^[[:space:]]*# ]] && continue

    # Remove leading/trailing whitespace from key
    key=$(echo "$key" | xargs)

    # Export the variable
    # Note: value may contain spaces (e.g., email addresses), which is fine
    export "$key=$value"
done < "$ENV_FILE"

echo "✓ Loaded environment variables from $ENV_FILE"
