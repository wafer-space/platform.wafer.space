#!/bin/bash
# Install system dependencies
# Run as: sudo ./02-install-dependencies.sh

set -e

echo "=== Installing system dependencies ==="

# Update package lists
echo "Updating package lists..."
apt update

# Install core dependencies
echo "Installing core dependencies..."
apt install -y \
    build-essential \
    curl \
    git \
    libpq-dev \
    python3-dev \
    python3-pip \
    python3-venv \
    software-properties-common \
    wget \
    certbot \
    python3-certbot-nginx

# Install pyenv dependencies (for Python 3.13)
echo "Installing pyenv dependencies..."
apt install -y \
    libbz2-dev \
    libffi-dev \
    liblzma-dev \
    libncursesw5-dev \
    libreadline-dev \
    libsqlite3-dev \
    libssl-dev \
    libxml2-dev \
    libxmlsec1-dev \
    tk-dev \
    xz-utils \
    zlib1g-dev

# Install PostgreSQL
echo "Installing PostgreSQL..."
apt install -y postgresql postgresql-contrib

# Install Nginx
echo "Installing Nginx..."
apt install -y nginx

# Install UFW firewall
echo "Installing UFW..."
apt install -y ufw

# Install Fail2Ban
echo "Installing Fail2Ban..."
apt install -y fail2ban

echo ""
echo "=== Dependencies installed successfully ==="
echo "Next steps:"
echo "1. Configure PostgreSQL database"
echo "2. Install uv as django user"
echo "3. Clone application repository"
