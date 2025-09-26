# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Running the Development Server
```bash
uv run python manage.py runserver
```

### Running Tests
```bash
# Run all tests
uv run pytest

# Run a specific test file
uv run pytest path/to/test_file.py

# Run tests with coverage
uv run coverage run -m pytest
uv run coverage html
```

### Linting and Type Checking
```bash
# Run ruff linter with auto-fix
uv run ruff check --fix .

# Run ruff formatter
uv run ruff format .

# Run mypy type checker
uv run mypy wafer_space

# Run djlint for Django templates
uv run djlint --reformat .
uv run djlint --check .

# Run all pre-commit hooks
uv run pre-commit run --all-files
```

### Database Operations
```bash
# Create new migrations
uv run python manage.py makemigrations

# Apply migrations
uv run python manage.py migrate

# Create superuser
uv run python manage.py createsuperuser
```

### Background Jobs (Celery)
```bash
# Start Celery worker for processing background tasks
uv run celery -A config worker --loglevel=info

# Start Celery worker with specific queues
uv run celery -A config worker -Q manufacturability,referrals --loglevel=info

# Monitor Celery tasks (requires flower - optional)
# uv add flower
# uv run celery -A config flower

# Purge all pending tasks (development only)
uv run celery -A config purge

# Inspect active tasks
uv run celery -A config inspect active
```

### Documentation
```bash
# Build Sphinx documentation
cd docs && make html

# Live reload documentation server
cd docs && make livehtml
```

### Git Workflow
```bash
# Check current status and staged changes
git status
git diff --staged

# Add specific files to staging
git add <file_path>

# Commit changes with descriptive message
git commit -m "Brief description of change

More detailed explanation if needed.

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"

# Push changes to remote
git push origin <branch_name>
```

**Commit Guidelines:**
- Make small, focused commits with single improvements or bug fixes
- Use descriptive commit messages in present tense
- Include context about why the change was made
- Run linting and tests before committing when possible

## Project Architecture

This is a Django 5.2+ application for wafer.space low cost silicon manufacturing, built with cookiecutter-django template.

### Core Components

- **Django Configuration**: Settings split into `config/settings/` with base, local, production, and test configurations. Uses django-environ for environment variables.

- **Applications**: Main application code in `wafer_space/` with:
  - `users/`: User authentication and management with django-allauth
  - `templates/`: Django templates using crispy-bootstrap5
  - `static/`: Static assets managed by WhiteNoise

- **Database**: PostgreSQL in production, with Redis for caching. Uses django-model-utils for model utilities.

- **Testing**: pytest-django with factory-boy for test fixtures. Tests located in `*/tests/` directories within each app.

- **Frontend**: Bootstrap 5 with django-crispy-forms for form rendering.

### Development Tools

- **Package Management**: Uses `uv` for Python dependency management (pyproject.toml)
- **Code Quality**: Ruff for linting/formatting, mypy for type checking, djlint for Django templates
- **Pre-commit Hooks**: Configured with trailing whitespace, file fixes, Django upgrade, and linting
- **Debug Toolbar**: Available in local development for performance analysis

### Key Configuration Files

- `pyproject.toml`: Project dependencies and tool configurations (pytest, mypy, ruff, djlint)
- `.pre-commit-config.yaml`: Pre-commit hook configurations
- `config/settings/base.py`: Core Django settings shared across environments
- `config/settings/local.py`: Development-specific settings with debug toolbar
- `config/urls.py`: Main URL configuration
- Never delete a test or reduce test functionality without an explicit request from the user.

## CI/CD Best Practices

When making changes to the codebase, always consider the impact on Continuous Integration:

### Pre-commit Hooks and Linting

1. **Run linting locally before committing**:
   ```bash
   make lint-fix        # Fix auto-fixable linting issues
   make type-check      # Run mypy type checking
   make check-all       # Run all checks (lint, type-check, tests)
   ```

2. **Common linting issues to avoid**:
   - **Print statements**: Use logging instead of `print()` in production code
   - **Long lines**: Keep lines under 88 characters (ruff default)
   - **Import organization**: Keep imports at the top of files
   - **Boolean arguments**: Use keyword-only arguments for boolean parameters
   - **F-strings in exceptions**: Assign f-strings to variables before raising exceptions
   - **Hardcoded passwords in tests**: Use `# noqa: S105` or `# noqa: S106` for test passwords

3. **Browser test considerations**:
   - Browser tests may need `# noqa: PLC0415` for imports inside fixtures
   - Screenshot utilities may need `# noqa: PTH118` for path operations
   - Test performance metrics may need `# noqa: PLR2004` for magic numbers

### Testing Strategy

1. **Always run tests before committing**:
   ```bash
   make test            # Run unit tests
   make test-browser-headless  # Run browser tests for CI
   ```

2. **Browser test reliability**:
   - Use Page Object Model pattern for maintainability
   - Add proper wait conditions for dynamic content
   - Use headless mode in CI/CD pipelines
   - Consider viewport-specific behavior in responsive tests

3. **Test organization**:
   - Keep test fixtures in conftest.py
   - Use descriptive test names
   - Group related tests in classes
   - Use pytest markers for test categorization

### GitHub Actions Troubleshooting

1. **Linting failures**: Check ruff output and fix issues locally first
2. **Test failures**: Run tests locally with same Python version as CI
3. **Import errors**: Ensure all dependencies are in pyproject.toml
4. **Browser test failures**: Use headless mode and proper wait conditions

### Code Quality Standards

1. **Type hints**: Use type hints for function parameters and return values
2. **Documentation**: Add docstrings for all public functions and classes
3. **Error handling**: Use proper exception handling with descriptive messages
4. **Logging**: Use structured logging instead of print statements
5. **Security**: Avoid hardcoded secrets, use environment variables

### Database Migrations

1. **Always create migrations for model changes**:
   ```bash
   make makemigrations  # Create new migrations
   make migrate         # Apply migrations
   ```

2. **Test migrations in both directions** (forward and backward when possible)
3. **Review migration files** before committing
4. **Use descriptive migration names** when needed