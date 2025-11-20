# wafer.space Online Platform

Platform for wafer.space low cost silicon manufacturing.

[![Built with Cookiecutter Django](https://img.shields.io/badge/built%20with-Cookiecutter%20Django-ff69b4.svg?logo=cookiecutter)](https://github.com/cookiecutter/cookiecutter-django/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

License: Apache Software License 2.0

## Getting Started

This project includes a comprehensive Makefile for development workflow automation. To see all available commands:

```bash
make help
```

## Quick Start

### Initial Setup

```bash
# Install uv package manager (if not already installed)
make install

# Create virtual environment and install dependencies
make venv

# Run database migrations
make migrate

# Create a superuser account
make createsuperuser

# Start the development server
make runserver
```

## Development Workflow

### Database Management

```bash
# Create new migrations
make makemigrations

# Apply migrations
make migrate

# Reset database (WARNING: Deletes all data!)
make db-reset

# Create superuser
make createsuperuser
```

### Running Tests

```bash
# Run all tests
make test

# Run tests with verbose output
make test-verbose

# Run tests in parallel (faster)
make test-fast

# Run tests for specific app
make test-app APP=projects

# Run tests with coverage report
make test-coverage

# Generate HTML coverage report
make test-coverage-html

# Run only previously failed tests
make test-failed
```

### Browser Testing (Selenium)

Browser tests use Selenium WebDriver to test the application's UI functionality across different browsers and viewports. Tests include homepage navigation, authentication flows, responsive design, and performance metrics.

```bash
# Run browser tests with Chrome (visible mode)
make test-browser

# Run browser tests in headless mode (for CI)
make test-browser-headless

# Run browser tests with Firefox
make test-browser-firefox

# Run browser tests in parallel (faster)
make test-browser-parallel

# Run browser tests with debugging (visible, verbose)
make test-browser-debug

# Run browser tests with different viewports
make test-browser-mobile    # 375x667 (iPhone)
make test-browser-tablet    # 768x1024 (iPad)

# Clean browser test screenshots
make test-browser-screenshots
```

### Code Quality

```bash
# Run linting with ruff
make lint

# Run linting with auto-fix
make lint-fix

# Format code with ruff
make format

# Run type checking with mypy
make type-check

# Run all checks (lint, type-check, tests)
make check-all
```

### Development Server

```bash
# Run Django development server
make runserver

# Open Django shell
make shell

# Open Django shell_plus (with auto-imports)
make shell-plus
```

### Celery Background Tasks

```bash
# Start Celery worker
make celery

# Purge all Celery tasks
make celery-purge
```

### Static Files

```bash
# Collect static files for production
make collectstatic
```

### Utilities

```bash
# Clean Python cache files
make clean

# Clean everything including virtual environment
make clean-all

# Show all URL patterns
make show-urls

# Check deployment readiness
make check-deploy
```

### CI/CD

```bash
# Run CI test suite
make ci-test

# Run pre-commit checks (lint-fix + tests)
make pre-commit
```

## Project Structure

- **wafer_space/** - Main application directory
  - **users/** - User authentication and management
  - **projects/** - Project submission and manufacturability checking
  - **referrals/** - Referral program management
  - **shuttles/** - Shuttle run management
  - **coupons/** - Coupon system
- **config/** - Django configuration
  - **settings/** - Environment-specific settings
- **staticfiles/** - Collected static files
- **templates/** - Django templates

## Features

### Admin Project Access

Django superusers can view and manage any user's project with comprehensive audit logging:
- Full access to view, edit, delete, and submit any project
- Visual warning banners indicate admin mode
- All access automatically logged with IP, timestamp, and action
- Read-only audit logs viewable in Django admin

See [docs/admin_project_access.md](docs/admin_project_access.md) for details.

## Settings

Moved to [settings](https://cookiecutter-django.readthedocs.io/en/latest/1-getting-started/settings.html).

## Deployment

For comprehensive production deployment instructions on Debian Linux, see the [Production Deployment Guide](docs/production_deployment.md).

This guide covers:
- System requirements and initial setup
- PostgreSQL and dependency installation
- Application installation with uv
- Environment configuration
- Systemd service setup (Gunicorn and Celery)
- Nginx reverse proxy configuration
- SSL/HTTPS with Let's Encrypt
- Security hardening and monitoring
- Troubleshooting and maintenance procedures
