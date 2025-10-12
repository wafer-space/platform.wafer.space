# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 🎯 PREFERRED DEVELOPMENT APPROACH

**ALWAYS prefer Makefile commands over direct command execution.** The project provides a comprehensive Makefile with standardized, tested commands that handle proper environment setup and configuration.

### ✅ Use Makefile Commands (PREFERRED)
```bash
# Development server
make runserver                   # Preferred - runs on correct port (8081)

# Testing
make test                        # Preferred - runs all unit tests
make test-browser-headless       # Preferred - browser tests (headless only)
make lint-fix                   # Preferred - fixes code style issues

# Database operations
make migrate                     # Preferred - runs database migrations
make createsuperuser            # Preferred - creates Django admin user
```

### ❌ Direct Commands (Rare Cases Only)
```bash
# Only use these for very specific operations not covered by Makefile
uv run python manage.py runserver  # Less preferred - may use wrong port
uv run pytest                      # Less preferred - less configuration
```

**Why prefer Makefile commands:**
- ✅ **Consistent configuration** - proper ports, settings, and flags
- ✅ **Maintained by project team** - reflects current best practices
- ✅ **Cross-platform compatibility** - works on all developer machines
- ✅ **Integrated tooling** - handles environment setup automatically
- ✅ **Color output and formatting** - better developer experience

## Development Commands

### Running Tests

#### 🚨🚨🚨 ABSOLUTE CRITICAL RULE - ZERO TOLERANCE 🚨🚨🚨
**THIS IS A BINDING REQUIREMENT - NO EXCEPTIONS EVER**

**RULE**: Browser tests MUST NEVER open visible browser windows when using Claude Code.

```bash
# ❌❌❌ ABSOLUTELY FORBIDDEN - WILL EXPLODE WITH ERROR ❌❌❌
uv run pytest tests/browser/          # FORBIDDEN! WILL BLOCK EXECUTION!
pytest tests/browser/test_file.py     # FORBIDDEN! WILL BLOCK EXECUTION!
python -m pytest tests/browser/       # FORBIDDEN! WILL BLOCK EXECUTION!

# ✅✅✅ ONLY THESE COMMANDS ARE PERMITTED ✅✅✅
make test-browser-headless           # MANDATORY FOR ALL BROWSER TESTS
make test-browser-firefox-headless   # Alternative headless only
make test-browser-parallel           # Parallel headless only
```

**AUTOMATIC ENFORCEMENT ACTIVE:**
- Code will EXPLODE with detailed error if CLAUDECODE environment is detected
- Environment variables automatically block GUI display connections
- pytest configuration forces headless mode for all browser tests
- Multiple protection layers prevent accidental visible browser execution

**MANDATORY CHECK BEFORE EVERY TEST COMMAND:**
1. Does the command contain "tests/browser/"?
2. If YES → STOP! Use `make test-browser-headless` instead
3. If NO → Proceed with command

**THIS PROTECTION IS NON-NEGOTIABLE AND CANNOT BE BYPASSED**

#### Unit Tests (Non-Browser)
```bash
# ✅ PREFERRED: Use Makefile commands
make test                        # Run all unit tests
make test-verbose               # Run tests with verbose output
make test-fast                  # Run tests in parallel
make test-coverage              # Run tests with coverage report
make test-coverage-html         # Generate HTML coverage report
make test-app APP=users         # Run tests for specific app

# ❌ DIRECT COMMANDS: For very specific operations
uv run pytest path/to/specific_test.py  # For very specific test files
```

### Code Quality and Linting
```bash
# ✅ PREFERRED: Use Makefile commands
make lint-fix                   # Run ruff linter with auto-fix + formatting
make lint                       # Run ruff linter (check only)
make type-check                 # Run mypy type checker
make format                     # Format code with ruff
make check-all                  # Run all checks (lint, type-check, tests)

# ❌ DIRECT COMMANDS: For operations not yet in Makefile
uv run pre-commit run --all-files  # Run all pre-commit hooks (no Makefile equivalent yet)
```

### Database Operations
```bash
# ✅ PREFERRED: Use Makefile commands
make migrate                    # Apply database migrations
make makemigrations             # Create new database migrations
make createsuperuser           # Create Django superuser
make collectstatic             # Collect static files

# ❌ DIRECT COMMANDS: All common database operations have Makefile equivalents
# Use Makefile commands above - they handle proper configuration
```

### Background Jobs (Celery)
```bash
# ✅ PREFERRED: Use Makefile commands where available
make celery                     # Start Celery worker

# ❌ DIRECT COMMANDS: For specific Celery operations
uv run celery -A config worker -Q manufacturability,referrals --loglevel=info
uv run celery -A config purge   # Purge all pending tasks (development only)
uv run celery -A config inspect active  # Inspect active tasks

# Note: Some specialized Celery commands don't have Makefile equivalents yet
```

### Documentation
```bash
# ✅ PREFERRED: Use Makefile commands
make docs                       # Build Sphinx documentation
make docs-live                  # Start live documentation server

# ❌ DIRECT COMMANDS: Documentation has Makefile equivalents
# Use Makefile commands above - they handle proper paths and configuration
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
- **ALWAYS run `make check-all` before committing** (combines linting, type-checking, and tests)
- Use `make lint-fix` to automatically fix code style issues

### Utility Commands
```bash
# ✅ PREFERRED: Use Makefile commands for common utilities
make clean                      # Clean up Python cache files
make clean-all                  # Clean everything including virtual environment
make show-urls                  # Show all Django URL patterns
make check-deploy              # Check deployment readiness
make help                      # Show all available Makefile commands

# Development environment setup
make venv                      # Create virtual environment and install dependencies
make dev-install              # Install development dependencies
```

## 📋 Quick Command Reference

**Most Common Commands (Use These 90% of the Time):**
```bash
make runserver                 # Start development server
make test                      # Run all unit tests
make test-browser-headless     # Run browser tests (headless only)
make lint-fix                  # Fix code style issues
make migrate                   # Apply database migrations
make check-all                 # Run all quality checks before commit
```

## 🔍 Finding the Right Command

**ALWAYS start by checking the Makefile:**
```bash
make help                      # Shows all available commands with descriptions
```

**Decision Tree for Command Selection:**
1. **First, always check:** `make help` to see available targets
2. **Is there a Makefile target?** → Use `make [target]` (99% of cases)
3. **Need very specific test targeting?** → Use `uv run pytest path/to/file.py`
4. **Need debugging with special flags?** → Use direct command with explanation
5. **Browser tests?** → **ALWAYS** use `make test-browser-headless`

**Note:** The Makefile should always be present - if it's missing, something is seriously wrong with the repository setup.

**Examples of When to Use Direct Commands:**
```bash
# ✅ ACCEPTABLE: Very specific test targeting
uv run pytest wafer_space/users/tests/test_models.py::TestUser::test_email_validation -v

# ✅ ACCEPTABLE: Specialized Django management commands not in Makefile
uv run python manage.py shell -c "from django.contrib.auth import get_user_model; print(get_user_model().objects.count())"

# ✅ ACCEPTABLE: Debugging with specific pytest flags
uv run pytest --pdb --tb=long path/to/failing_test.py
```

## Project Architecture

This is a Django 5.2+ application for wafer.space low cost silicon manufacturing, built with cookiecutter-django template.

### Core Components

- **Django Configuration**: Settings split into `config/settings/` with base, local, production, and test configurations. Uses django-environ for environment variables.

- **Applications**: Main application code in `wafer_space/` with:
  - `users/`: User authentication and management with django-allauth
  - `templates/`: Django templates using crispy-bootstrap5
  - `static/`: Static assets managed by WhiteNoise

- **Database**: PostgreSQL in production. Uses django-model-utils for model utilities.

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

4. **🚨 CRITICAL: Prevent Circular Imports**:
   **Circular imports must be avoided at all costs.** They indicate poor architecture and cause runtime errors.

   ```python
   # ❌ NEVER create circular imports
   # models.py
   from .tasks import process_model

   # tasks.py
   from .models import MyModel  # This creates a circular dependency!
   ```

   **✅ Solutions (in order of preference):**

   **Option 1: Restructure the architecture (BEST)**
   ```python
   # Move business logic to appropriate layer
   # models.py - only data representation
   class MyModel(models.Model):
       name = models.CharField(max_length=100)
       # No business logic or task calls here

   # services.py - business logic layer
   def process_model_data(model_instance):
       from .tasks import background_process
       return background_process.delay(model_instance.id)

   # views.py - orchestration layer
   from .services import process_model_data
   result = process_model_data(my_model)
   ```

   **Option 2: Use dependency injection**
   ```python
   # models.py
   class MyModel(models.Model):
       def start_processing(self, processor_func):
           return processor_func(self.id)

   # views.py
   from .tasks import background_process
   from .models import MyModel
   model.start_processing(background_process.delay)
   ```

   **Option 3: Remove unused methods**
   ```python
   # If a method causing circular imports is unused, DELETE it
   # Don't keep dead code that creates architectural problems
   ```

   **❌ NEVER use local imports to "fix" circular imports**
   ```python
   # This is NOT a solution, it's hiding the problem:
   def some_method(self):
       from .tasks import some_task  # Wrong approach
       return some_task.delay(self.id)
   ```

5. **Boolean Arguments (FBT002/FBT003)**:
   ```python
   # ❌ Avoid positional boolean arguments
   def process_data(data, validate=True):
       pass

   # ✅ Use keyword-only arguments
   def process_data(data, *, validate=True):
       pass
   ```

6. **F-strings in Exceptions (EM102)**:
   ```python
   # ❌ Avoid f-strings directly in exceptions
   raise ValueError(f"Invalid value: {value}")

   # ✅ Assign to variable first
   msg = f"Invalid value: {value}"
   raise ValueError(msg)
   ```

7. **Hardcoded Passwords in Tests**:
   ```python
   # ✅ Use constants for test passwords instead of hardcoding
   TEST_PASSWORD = "testpass123"
   user.set_password(password=TEST_PASSWORD)
   ```

#### Browser Test Specific Issues

1. **Dynamic Imports in Fixtures**:
   ```python
   # ✅ Move imports to top-level when possible
   from selenium.webdriver.common.by import By
   # Only use local imports when absolutely necessary to avoid circular dependencies
   ```

2. **Path Operations**:
   ```python
   # ✅ Use pathlib when possible
   from pathlib import Path
   screenshot_path = Path("screenshots") / f"{name}.png"

   # ✅ Convert any os.path usage to pathlib
   import os
   path = Path(dir) / filename
   ```

3. **Magic Numbers in Performance Tests**:
   ```python
   # ✅ Use descriptive constants
   PERFORMANCE_THRESHOLD_MS = 5000  # Maximum acceptable load time in milliseconds
   assert load_time < PERFORMANCE_THRESHOLD_MS
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
   - Fix the underlying issue rather than suppressing warnings

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

## Code Quality Standards

### CRITICAL: Architectural Principles to Prevent Circular Imports

**Circular imports are architectural failures that must be prevented through proper design.**

#### Layer Separation (Django Best Practices)
```python
# ✅ Proper layered architecture

# models.py - Data layer only
class Project(models.Model):
    name = models.CharField(max_length=100)
    # Only data representation, no business logic

# services.py - Business logic layer
def start_project_processing(project):
    """Business logic for processing projects."""
    from .tasks import process_project  # OK: services can import tasks
    project.status = 'processing'
    project.save()
    return process_project.delay(project.id)

# views.py - Presentation layer
from .services import start_project_processing
from .models import Project

def project_view(request, project_id):
    project = Project.objects.get(id=project_id)
    task = start_project_processing(project)  # Proper orchestration
    return JsonResponse({'task_id': task.id})

# tasks.py - Background processing layer
from .models import Project  # OK: tasks can import models

@shared_task
def process_project(project_id):
    project = Project.objects.get(id=project_id)
    # Process the project
    project.status = 'completed'
    project.save()
```

#### Import Direction Rules
1. **Models** should NEVER import from tasks, views, or services
2. **Services** can import from models and tasks (business orchestration)
3. **Views** can import from models and services (presentation orchestration)
4. **Tasks** can import from models (data access)

#### Red Flags That Indicate Poor Architecture
```python
# 🚨 These patterns indicate architectural problems:

# models.py importing tasks/views/services
from .tasks import some_task  # ❌ Models calling tasks directly

# Unused methods that create dependencies
def start_download(self):  # ❌ If unused, DELETE it
    from .tasks import download_task
    return download_task.delay(self.id)

# Business logic in models
class Project(models.Model):
    def complex_business_operation(self):  # ❌ Move to services
        # Complex logic doesn't belong in models
```

#### When You Encounter Circular Import Errors
1. **FIRST**: Question if the dependency is actually needed
2. **SECOND**: Consider if unused code can be deleted
3. **THIRD**: Restructure using proper layer separation
4. **NEVER**: Use local imports as a "quick fix"

### ABSOLUTE PROHIBITION: Never Add `# noqa` Comments Without User Permission

**🚨 CRITICAL RULE: You must ALWAYS, ALWAYS, ALWAYS ask the user for explicit permission before adding ANY `# noqa` comment. 🚨**

**This rule has NO exceptions. It applies to:**
- ALL linting warnings (ruff, flake8, pylint, etc.)
- ALL type checking warnings (mypy, pyright, etc.)
- ALL security warnings (bandit, safety, etc.)
- ALL import warnings (isort, import-linter, etc.)
- ALL formatting warnings (black, autopep8, etc.)
- ANY other code quality warnings from ANY tool
- Even if the warning seems "trivial" or "obviously needed"
- Even if you are 100% confident the suppression is correct
- Even if the warning is a false positive
- Even if you've used the same suppression before
- Even in emergency situations or time pressure

**The process you MUST follow:**
1. **STOP** when you encounter a linting error
2. **First try to fix the underlying issue properly** without suppression
3. **Only if the warning is unavoidable** - ask the user for permission
4. **Explain in detail** why you want to suppress the warning
5. **Wait for explicit user approval** before proceeding
6. **Only add the comment if approved** with proper explanation

**Examples of what is FORBIDDEN:**
```python
# ALL of these are WRONG - never do any of these without permission:
import os  # noqa: F401
from .tasks import foo  # noqa: PLC0415
request = Request(url)  # noqa: S310
password = "test"  # noqa: S105
```

**What TO do instead:**
1. **Ask permission first**: "May I add `# noqa: F401` to suppress the unused import warning for `import os`? This import is needed for X specific reason and cannot be avoided because Y."
2. **Wait for user approval** - do not proceed without explicit "yes"
3. **Only then add the comment** if the user approves
4. **Include detailed explanation** in the comment when approved

**Remember: It doesn't matter how small, trivial, or "obviously correct" the suppression seems - you MUST ask first.**

### Code Quality Prevention Guidelines

#### Write Clean Code from the Start
- **Functions must be simple and focused** - Keep complexity (C901) under 10
- **Limit branches and statements** - No more than 12 branches (PLR0912) or 50 statements (PLR0915)
- **Use modern Python patterns** - Always use `pathlib.Path` instead of `os.path`
- **Handle exceptions specifically** - Never use broad `except Exception:` (BLE001)
- **Use secure practices** - Be mindful of URL handling (S310) and hash functions (S324)
- **Follow proper exception chaining** - Use `raise ... from exc` (B904)

#### Function Design Principles
- **Single Responsibility**: Each function should do one thing well
- **Avoid deep nesting**: Use early returns and guard clauses
- **Extract complex logic**: Break large functions into smaller helper functions
- **Use context managers**: Prefer `contextlib.suppress()` over try/except/pass

#### Modern Python Standards
```python
# ✅ Good: Use pathlib
from pathlib import Path
temp_dir = Path(tempfile.gettempdir()) / "wafer_space_downloads"
temp_dir.mkdir(parents=True, exist_ok=True)

# ❌ Bad: Use os.path
import os
temp_dir = os.path.join(tempfile.gettempdir(), "wafer_space_downloads")
os.makedirs(temp_dir, exist_ok=True)

# ✅ Good: Specific exceptions
try:
    operation()
except (IOError, OSError) as exc:
    raise ProcessingError("Operation failed") from exc

# ❌ Bad: Broad exceptions
try:
    operation()
except Exception:
    return False

# ✅ Good: Context managers for cleanup
with contextlib.suppress(OSError):
    path.unlink()

# ❌ Bad: Manual exception handling
try:
    os.remove(path)
except OSError:
    pass
```

#### Complexity Management
- **Break down complex functions** into smaller, testable units
- **Use early returns** to reduce nesting levels
- **Extract configuration** and constants to module level
- **Limit function parameters** - prefer configuration objects for complex functions
- **Use type hints** for better code clarity and tooling support

## 🚀 Production Deployment and Secrets Management

### Overview

This project uses a **two-repository approach** for security:
- **Main Repository** (`platform.wafer.space`): All code, tests, and non-sensitive configuration
- **Secrets Repository** (`platform.wafer.space-secrets`): Private repository containing production secrets

### Critical File Locations

```
platform.wafer.space/
├── secrets/                           # Local copy of secrets repository (gitignored)
│   ├── github-oauth                   # GitHub OAuth Client Secret
│   ├── gitlab-oauth                   # GitLab OAuth Client Secret
│   ├── google-auth.json               # Google OAuth credentials (JSON format)
│   ├── discord-oauth                  # Discord OAuth Client Secret
│   ├── linkedin-oauth                 # LinkedIn OAuth Client Secret
│   └── mailgun                        # Mailgun API key
│
├── deployment/
│   ├── scripts/
│   │   ├── 02a-setup-secrets.sh       # Clone/update secrets repository on server
│   │   └── 03a-update-env-secrets.sh  # Update .env with secrets from repository
│   ├── nginx/                         # Nginx configuration
│   ├── systemd/                       # Systemd service files
│   └── README.md                      # Deployment documentation
│
└── config/settings/
    ├── base.py                        # Base settings (dev Client IDs with env var secrets)
    └── production.py                  # Production settings (prod Client IDs override)
```

### 🚨 CRITICAL: When Adding New Secrets

**MANDATORY CHECKLIST** - Complete ALL steps when adding new secrets or OAuth providers:

#### 1. Add Secret to Secrets Repository
```bash
# In your local secrets/ directory (which is a git clone of the secrets repo)
cd secrets/
echo "your_secret_value" > new-secret-name
git add new-secret-name
git commit -m "Add new-secret-name for [purpose]"
git push
```

#### 2. Update Django Settings
```python
# config/settings/base.py - Add environment variable reference
NEW_SECRET = env("NEW_SECRET_NAME", default="")

# For OAuth providers specifically:
SOCIALACCOUNT_PROVIDERS = {
    "provider_name": {
        "APP": {
            "client_id": env("PROVIDER_CLIENT_ID", default="dev_client_id"),
            "secret": env("PROVIDER_CLIENT_SECRET", default=""),  # Empty default!
        },
        # ... other config
    }
}

# config/settings/production.py - Override with production Client ID
SOCIALACCOUNT_PROVIDERS["provider_name"]["APP"]["client_id"] = env(
    "PROVIDER_CLIENT_ID",
    default="prod_client_id",  # Production Client ID can be in code
)
# Secret MUST come from environment variable, never hardcode!
```

#### 3. Update Deployment Script (`deployment/scripts/03a-update-env-secrets.sh`)

**THIS STEP IS CRITICAL AND OFTEN FORGOTTEN!**

```bash
# Add a new section to read and inject the secret
# Read Provider OAuth secret
if [ ! -f "$SECRETS_DIR/provider-oauth" ]; then
    echo "Error: Required secret file not found: $SECRETS_DIR/provider-oauth"
    exit 1
fi
PROVIDER_SECRET=$(cat "$SECRETS_DIR/provider-oauth" | tr -d '\n')
if grep -q "^PROVIDER_CLIENT_SECRET=" "$ENV_FILE"; then
    sed -i "s|^PROVIDER_CLIENT_SECRET=.*|PROVIDER_CLIENT_SECRET=$PROVIDER_SECRET|" "$ENV_FILE"
else
    echo "PROVIDER_CLIENT_SECRET=$PROVIDER_SECRET" >> "$ENV_FILE"
fi
echo "✓ Updated Provider OAuth secret"
```

#### 4. Update Documentation
```bash
# Update relevant documentation files:
docs/oauth_setup.md              # OAuth provider setup instructions
docs/developer_onboarding.md     # Development environment setup
.env.example                     # Example environment variables (NO REAL SECRETS!)
```

#### 5. Test Locally
```bash
# Verify the secret is properly loaded
uv run python manage.py shell
>>> from django.conf import settings
>>> settings.PROVIDER_CLIENT_SECRET  # Should show your dev secret from .env
>>> settings.SOCIALACCOUNT_PROVIDERS['provider_name']['APP']['secret']
```

### Deployment Scripts Reference

#### `deployment/scripts/02a-setup-secrets.sh`
**Purpose**: Clone or update the secrets repository on the production server

**When to run**:
- Initial server setup
- When secrets repository structure changes
- When adding completely new secret files

**What it does**:
```bash
# Run as sudo
sudo ./deployment/scripts/02a-setup-secrets.sh

# Clones git@github.com:mithro/platform.wafer.space-secrets.git
# Into /home/django/.secrets
# Sets proper permissions (700, owned by django user)
```

#### `deployment/scripts/03a-update-env-secrets.sh`
**Purpose**: Read secrets from the secrets repository and update production `.env` file

**When to run**:
- After adding new secrets to secrets repository
- When rotating existing secrets
- During deployment when secrets have changed
- **MUST be updated when adding new secret types**

**What it does**:
```bash
# Run as sudo
sudo ./deployment/scripts/03a-update-env-secrets.sh

# Reads each secret file from /home/django/.secrets/
# Updates /home/django/platform.wafer.space/.env
# Requires services restart to take effect
```

**Current secrets handled** (as of current version):
- ✅ Mailgun API key (`mailgun`)
- ✅ GitHub OAuth Client Secret (`github-oauth`)
- ✅ GitLab OAuth Client Secret (`gitlab-oauth`)
- ✅ Google OAuth Client Secret (`google-auth.json`)
- ❌ Discord OAuth Client Secret (`discord-oauth`) - **MISSING FROM SCRIPT**
- ❌ LinkedIn OAuth Client Secret (`linkedin-oauth`) - **MISSING FROM SCRIPT**

### Common Pitfalls and How to Avoid Them

#### ❌ Pitfall 1: Forgetting to Update Deployment Script
**Problem**: You add a new secret to the secrets repository and Django settings, but forget to update `03a-update-env-secrets.sh`. Result: Production deployment fails or uses empty/default secrets.

**Solution**: ALWAYS update the deployment script when adding new secrets. Use the checklist above.

#### ❌ Pitfall 2: Hardcoding Secrets in Settings
**Problem**: Adding secrets directly to `config/settings/production.py` like this:
```python
# ❌ NEVER DO THIS
SOCIALACCOUNT_PROVIDERS["provider"]["APP"]["secret"] = "actual_secret_value"
```

**Solution**: Always use environment variables:
```python
# ✅ CORRECT
SOCIALACCOUNT_PROVIDERS["provider"]["APP"]["secret"] = env("PROVIDER_SECRET", default="")
```

#### ❌ Pitfall 3: Committing Secrets to Git
**Problem**: Accidentally adding real secrets to any tracked file.

**Solution**:
- Use `.gitignore` for `secrets/` directory and `.env` files
- Use pre-commit hooks for secret detection (see issue #28)
- Never set non-empty defaults for secrets in settings files
- If you commit secrets, immediately rotate them and rewrite git history

#### ❌ Pitfall 4: Different Secret Names in Different Places
**Problem**: Using different environment variable names in settings vs deployment scripts.

**Solution**: Use consistent naming convention:
- Settings file: `PROVIDER_CLIENT_SECRET`
- Deployment script: Same variable name
- Secrets file: `provider-oauth` (kebab-case)

### Secret Management Best Practices

1. **Client IDs vs Secrets**:
   - **Client IDs**: Public, can be committed to git in settings files
   - **Client Secrets**: Private, MUST be in environment variables only

2. **Development vs Production**:
   - Development secrets go in local `.env` file (gitignored)
   - Production secrets go in secrets repository
   - Use different OAuth apps for dev and prod

3. **Secret Rotation**:
   ```bash
   # 1. Update secret in secrets repository
   cd secrets/
   echo "new_secret_value" > provider-oauth
   git commit -am "Rotate provider OAuth secret"
   git push

   # 2. On production server
   sudo ./deployment/scripts/02a-setup-secrets.sh  # Pull latest secrets
   sudo ./deployment/scripts/03a-update-env-secrets.sh  # Update .env
   sudo systemctl restart django-gunicorn django-celery  # Restart services
   ```

4. **Verifying Deployment**:
   ```bash
   # After deploying, verify secrets are loaded
   sudo -u django bash
   cd ~/platform.wafer.space
   source venv/bin/activate
   python manage.py shell
   >>> from django.conf import settings
   >>> settings.GITHUB_CLIENT_SECRET  # Should be non-empty
   >>> len(settings.GITHUB_CLIENT_SECRET)  # Should show secret length
   ```

### Emergency: Secret Compromised

If a secret is accidentally committed or exposed:

1. **Immediately rotate** the secret at the provider (GitHub, Google, etc.)
2. **Update secrets repository** with new secret
3. **Run deployment script** on production: `sudo ./deployment/scripts/03a-update-env-secrets.sh`
4. **Restart services**: `sudo systemctl restart django-gunicorn django-celery`
5. **Rewrite git history** if committed (use with caution)
6. **Verify** the old secret no longer works

### Testing Deployment Scripts Locally

You can test the deployment script logic locally (without sudo):

```bash
# Test secret reading logic
cd secrets/
cat github-oauth  # Should show the secret value
cat google-auth.json | python3 -c "import json, sys; print(json.load(sys.stdin)['web']['client_secret'])"

# Verify .env gets updated correctly
# Create a test .env file and run the script logic manually
```

### Related Documentation

- `deployment/README.md` - Full deployment guide
- `docs/oauth_setup.md` - OAuth provider configuration
- `docs/developer_onboarding.md` - Local development setup
- Issue #28 - Pre-commit hooks to prevent secret commits

### Testing Requirements
- Only run the headless versions of the browser tests when testing
