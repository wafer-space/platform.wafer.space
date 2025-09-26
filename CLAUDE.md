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

When making changes to the codebase, always consider the impact on Continuous Integration. This section provides comprehensive guidance to prevent CI failures and maintain code quality.

### Pre-commit Workflow

**ALWAYS follow this sequence before committing:**

```bash
# 1. Fix linting issues
make lint-fix        # Auto-fix linting issues with ruff
make format          # Format code consistently

# 2. Run type checking
make type-check      # Run mypy type checking

# 3. Run unit tests
make test            # Run all unit tests

# 4. Run browser tests (HEADLESS ONLY for testing)
make test-browser-headless  # Run browser tests in headless mode

# 5. Complete validation
make check-all       # Run all checks (lint, type-check, tests)
```

### Linting and Code Quality

#### Common Linting Issues and Solutions

1. **Print Statements (T201)**:
   ```python
   # ❌ Avoid
   print(f"Debug info: {value}")

   # ✅ Use logging instead
   import logging
   logger = logging.getLogger(__name__)
   logger.info("Debug info: %s", value)
   ```

2. **Long Lines (E501)** - Keep under 88 characters:
   ```python
   # ❌ Too long
   assert some_very_long_condition_that_exceeds_line_length, "Error message that is also very long"

   # ✅ Break into multiple lines
   error_msg = "Error message that is also very long"
   assert some_very_long_condition_that_exceeds_line_length, error_msg
   ```

3. **Import Organization**:
   ```python
   # ✅ Correct order
   import os
   import sys

   import pytest
   from django.test import TestCase

   from myproject.models import MyModel
   ```

4. **Boolean Arguments (FBT002/FBT003)**:
   ```python
   # ❌ Avoid positional boolean arguments
   def process_data(data, validate=True):
       pass

   # ✅ Use keyword-only arguments
   def process_data(data, *, validate=True):
       pass
   ```

5. **F-strings in Exceptions (EM102)**:
   ```python
   # ❌ Avoid f-strings directly in exceptions
   raise ValueError(f"Invalid value: {value}")

   # ✅ Assign to variable first
   msg = f"Invalid value: {value}"
   raise ValueError(msg)
   ```

6. **Hardcoded Passwords in Tests**:
   ```python
   # ✅ Use noqa comments for test passwords
   password = "testpass123"  # noqa: S105
   user.set_password(password="test123")  # noqa: S106
   ```

#### Browser Test Specific Issues

1. **Dynamic Imports in Fixtures**:
   ```python
   # ✅ Sometimes necessary in fixtures
   from selenium.webdriver.common.by import By  # noqa: PLC0415
   ```

2. **Path Operations**:
   ```python
   # ✅ Use pathlib when possible
   from pathlib import Path
   screenshot_path = Path("screenshots") / f"{name}.png"

   # ✅ Or use noqa for os.path when needed
   import os
   path = os.path.join(dir, filename)  # noqa: PTH118
   ```

3. **Magic Numbers in Performance Tests**:
   ```python
   # ✅ Use constants or noqa comments
   PERFORMANCE_THRESHOLD = 5000  # noqa: PLR2004
   assert load_time < PERFORMANCE_THRESHOLD
   ```

### Testing Strategy

#### Unit Tests
```bash
# Run different test suites
make test                    # All unit tests
make test-verbose           # Verbose output
make test-coverage          # With coverage reporting
make test-app APP=projects  # Specific app tests
make test-fast              # Parallel execution
```

#### Browser Tests - **HEADLESS MODE ONLY**
```bash
# ✅ ALWAYS use headless mode for testing
make test-browser-headless           # Chrome headless
make test-browser-firefox-headless   # Firefox headless
make test-browser-parallel           # Parallel headless execution

# ❌ NEVER use visible mode for regular testing
# make test-browser  # Only for debugging, not CI/testing
```

#### Browser Test Best Practices

1. **Page Object Model Pattern**:
   ```python
   # ✅ Organize tests with Page Objects
   class LoginPage(BasePage):
       USERNAME_INPUT = (By.NAME, "login")

       def login(self, username, password):
           self.fill_input(self.USERNAME_INPUT, username)
           self.click_submit()
   ```

2. **Proper Wait Conditions**:
   ```python
   # ✅ Use explicit waits
   wait = WebDriverWait(driver, 10)
   element = wait.until(
       expected_conditions.presence_of_element_located(locator)
   )

   # ❌ Avoid implicit waits or sleep
   time.sleep(2)  # Unreliable
   ```

3. **Responsive Testing Considerations**:
   ```python
   # ✅ Account for headless behavior differences
   def test_mobile_navigation(self, driver):
       driver.set_window_size(375, 667)  # Mobile viewport
       # Test may behave differently in headless mode
       navbar_toggler = driver.find_elements(By.CLASS_NAME, "navbar-toggler")
       if navbar_toggler and navbar_toggler[0].is_displayed():
           # Handle case where toggler is visible
           pass
   ```

4. **Screenshot Management**:
   ```python
   # ✅ Automatic screenshots on failure
   @pytest.fixture(autouse=True)
   def _screenshot_on_failure(request, driver):
       yield
       if hasattr(request.node, "rep_call") and request.node.rep_call.failed:
           # Screenshots saved to tests/browser/screenshots/
           driver.save_screenshot(screenshot_path)
   ```

### Dependency Management

1. **Adding New Dependencies**:
   ```bash
   # Add to pyproject.toml [dependency-groups]
   uv sync --dev  # Install new dependencies
   ```

2. **Browser Testing Dependencies**:
   ```toml
   [dependency-groups]
   dev = [
       "selenium==4.27.1",
       "pytest-selenium==4.1.0",
       "webdriver-manager==4.0.2",
       "pytest-xdist==3.6.1",  # For parallel execution
   ]
   ```

### GitHub Actions Troubleshooting

#### Common CI Failure Patterns

1. **Linting Failures**:
   - Run `make lint-fix` locally first
   - Check the specific ruff rule and fix accordingly
   - Add `# noqa: RULE` comments only when necessary

2. **Test Import Errors**:
   - Ensure all imports are at top-level when possible
   - Check that dependencies are in pyproject.toml
   - Verify Python path and module structure

3. **Browser Test Failures**:
   - Always use headless mode in CI
   - Add proper wait conditions for dynamic content
   - Account for timing differences in CI environment
   - Use appropriate viewport sizes for responsive tests

4. **Database/Migration Issues**:
   - Ensure migrations are created for model changes
   - Test with fresh database state
   - Use transactional fixtures for test isolation

#### Debugging CI Failures

1. **Reproduce Locally**:
   ```bash
   # Use same commands as CI
   make test-browser-headless  # Same as CI environment
   make ci-test               # CI-specific test suite
   ```

2. **Check Logs**:
   ```bash
   # View detailed test output
   make test-verbose
   make test-browser-headless -v -s --tb=long
   ```

3. **Environment Parity**:
   - Use same Python version as CI (3.13.7)
   - Run in clean virtual environment
   - Check for environment-specific issues

### Code Quality Standards

#### Documentation Requirements
```python
def complex_function(param1: str, param2: int) -> dict[str, Any]:
    """
    Process data with specific parameters.

    Args:
        param1: Description of first parameter
        param2: Description of second parameter

    Returns:
        Dictionary containing processed results

    Raises:
        ValueError: When param1 is invalid
    """
```

#### Error Handling Patterns
```python
# ✅ Specific exception handling
try:
    result = process_data(data)
except ValidationError as e:
    logger.error("Data validation failed: %s", e)
    raise ProcessingError(f"Cannot process data: {e}") from e
```

#### Security Best Practices
```python
# ✅ Use environment variables for secrets
import os
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")

# ✅ Validate user input
def process_user_input(user_data: dict) -> dict:
    validated_data = UserInputSchema(**user_data)
    return process(validated_data)
```

### Database Migrations

#### Migration Workflow
```bash
# 1. Make model changes
# 2. Create migration
make makemigrations

# 3. Review migration file
# 4. Test migration
make migrate

# 5. Test reverse migration (when applicable)
uv run python manage.py migrate app_name previous_migration

# 6. Re-apply forward migration
make migrate
```

#### Migration Best Practices
1. **Descriptive Names**:
   ```bash
   make makemigrations projects --name add_url_download_fields
   ```

2. **Data Migration Safety**:
   ```python
   # Always handle missing data gracefully
   def forwards_func(apps, schema_editor):
       MyModel = apps.get_model("myapp", "MyModel")
       for obj in MyModel.objects.all():
           if not obj.new_field:
               obj.new_field = "default_value"
               obj.save()
   ```

### Performance Considerations

1. **Test Execution Time**:
   ```bash
   make test-browser-parallel  # Faster execution
   make test-fast              # Parallel unit tests
   ```

2. **CI Resource Usage**:
   - Use headless browsers to reduce memory usage
   - Run tests in parallel when possible
   - Cache dependencies between CI runs

3. **Database Performance**:
   ```python
   # ✅ Use appropriate test database settings
   @pytest.mark.django_db(transaction=True)  # When needed
   def test_with_transactions():
       pass
   ```

This comprehensive guide ensures consistent code quality and prevents CI failures. Always refer to this section when encountering build issues or implementing new features.
- Only run the headless versions of the browser tests when testing.