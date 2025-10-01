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

# Generate or prompt for database password
echo ""
echo "Database password options:"
echo "  1. Generate secure random password (recommended)"
echo "  2. Enter password manually"
read -rp "Choose option (1/2) [1]: " PASSWORD_OPTION
PASSWORD_OPTION=${PASSWORD_OPTION:-1}

if [ "$PASSWORD_OPTION" = "1" ]; then
    # Generate a secure random password
    DB_PASSWORD=$(openssl rand -base64 32 | tr -d "=+/" | cut -c1-32)
    echo "✓ Generated secure random password"
else
    # Prompt for database password
    read -rsp "Enter password for database user '$DB_USER': " DB_PASSWORD
    echo

    if [ -z "$DB_PASSWORD" ]; then
        echo "Error: Password cannot be empty"
        exit 1
    fi
fi

# Create database and user
echo "Creating database and user..."
sudo -u postgres psql <<EOF
-- Create database if not exists
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_database WHERE datname = '$DB_NAME') THEN
        CREATE DATABASE $DB_NAME;
    END IF;
END
\$\$;

-- Create user if not exists
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

-- Grant privileges
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

# Save DATABASE_URL to a temporary file for the django user
DATABASE_URL="postgres://$DB_USER:$DB_PASSWORD@localhost:5432/$DB_NAME"
DB_CONFIG_FILE="/tmp/database_config_$(date +%s).txt"

cat > "$DB_CONFIG_FILE" <<EOF
# Add this line to your .env file at: $ENV_FILE
DATABASE_URL=$DATABASE_URL
EOF

chmod 600 "$DB_CONFIG_FILE"
chown django:django "$DB_CONFIG_FILE" 2>/dev/null || true

echo "✓ Database credentials saved to: $DB_CONFIG_FILE"
echo ""
echo "Next steps:"
echo "1. As django user, add the DATABASE_URL to your .env file:"
echo "   sudo -u django cat $DB_CONFIG_FILE >> $ENV_FILE"
echo ""
echo "2. Securely delete the temporary credentials file:"
echo "   sudo rm $DB_CONFIG_FILE"
echo ""
echo "⚠️  For security, the password is NOT displayed in this terminal."
echo "    It has been saved to the temporary file shown above."
