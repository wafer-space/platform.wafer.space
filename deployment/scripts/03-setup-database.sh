#!/bin/bash
# Setup PostgreSQL database
# Run as: sudo ./03-setup-database.sh

set -e

DB_NAME="platform_wafer_space"
DB_USER="platform_wafer_space"
APP_DIR="/home/django/platform.wafer.space"
ENV_FILE="$APP_DIR/.env"

echo "=== Setting up PostgreSQL database ==="

# Check if database already exists
DB_EXISTS=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'")
USER_EXISTS=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'")

if [ "$DB_EXISTS" = "1" ] && [ "$USER_EXISTS" = "1" ]; then
    echo "✓ Database '$DB_NAME' and user '$DB_USER' already exist"
    echo ""
    echo "If you need to reset the password, run:"
    echo "  sudo -u postgres psql -c \"ALTER USER $DB_USER WITH PASSWORD 'new_password';\""
    echo "  Then update DATABASE_URL in $ENV_FILE"
    echo ""
    echo "=== Database setup complete (already configured) ==="
    exit 0
fi

# Generate secure random password
echo "Generating secure random password..."
DB_PASSWORD=$(openssl rand -base64 32 | tr -d "=+/" | cut -c1-32)
echo "✓ Generated secure random password"

# Create database if it doesn't exist (must be outside transaction)
if [ "$DB_EXISTS" != "1" ]; then
    echo "Creating database..."
    sudo -u postgres psql <<EOF
CREATE DATABASE $DB_NAME;
EOF
fi

# Create user and configure
echo "Creating/updating user..."
sudo -u postgres psql <<EOF
-- Create user if not exists, or update password
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$DB_USER') THEN
        CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';
    ELSE
        ALTER USER $DB_USER WITH PASSWORD '$DB_PASSWORD';
    END IF;
END
\$\$;

-- Configure user
ALTER ROLE $DB_USER SET client_encoding TO 'utf8';
ALTER ROLE $DB_USER SET default_transaction_isolation TO 'read committed';
ALTER ROLE $DB_USER SET timezone TO 'UTC';
EOF

# Grant privileges (must connect to the database)
echo "Granting privileges..."
sudo -u postgres psql -d "$DB_NAME" <<EOF
GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;
EOF

echo "✓ Database created successfully"

# Test connection
echo "Testing database connection..."
if PGPASSWORD="$DB_PASSWORD" psql -h localhost -U $DB_USER -d $DB_NAME -c "SELECT version();" >/dev/null 2>&1; then
    echo "✓ Database connection successful"
else
    echo "✗ Database connection failed"
    exit 1
fi

echo ""
echo "=== Database setup complete ==="
echo "Database: $DB_NAME"
echo "User: $DB_USER"
echo ""

# Write DATABASE_URL to .env file
DATABASE_URL="postgres://$DB_USER:$DB_PASSWORD@localhost:5432/$DB_NAME"

# Create .env file from template if it doesn't exist
if [ ! -f "$ENV_FILE" ]; then
    echo "Creating .env file from template..."

    # Copy template file
    TEMPLATE_FILE="$APP_DIR/.env.production.template"
    if [ -f "$TEMPLATE_FILE" ]; then
        cp "$TEMPLATE_FILE" "$ENV_FILE"
        echo "✓ Copied .env.production.template to .env"
    else
        echo "⚠️  Template file not found, creating minimal .env"
        touch "$ENV_FILE"
    fi
fi

# Add or update DATABASE_URL in .env file
if grep -q "^DATABASE_URL=" "$ENV_FILE"; then
    # Update existing DATABASE_URL
    sed -i "s|^DATABASE_URL=.*|DATABASE_URL=$DATABASE_URL|" "$ENV_FILE"
    echo "✓ Updated DATABASE_URL in .env"
else
    # Add DATABASE_URL
    {
        echo ""
        echo "# Database configuration (added by setup script)"
        echo "DATABASE_URL=$DATABASE_URL"
    } >> "$ENV_FILE"
    echo "✓ Added DATABASE_URL to .env"
fi

# Set proper ownership and permissions
chown django:django "$ENV_FILE"
chmod 640 "$ENV_FILE"

echo ""
echo "✓ Environment file configured: $ENV_FILE"
echo ""
echo "⚠️  IMPORTANT: Edit $ENV_FILE and configure:"
echo "    - DJANGO_SECRET_KEY (generate with: uv run python -c ...)"
echo "    - MAILGUN_API_KEY"
echo "    - OAuth credentials (GITHUB, GITLAB, GOOGLE)"
echo ""
echo "⚠️  For security, the database password is NOT displayed in this terminal."
echo "    It has been securely saved to $ENV_FILE (mode 640, owner django:django)"
