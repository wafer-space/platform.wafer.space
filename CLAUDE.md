# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 🚫 BANNED TECHNOLOGIES - ABSOLUTELY PROHIBITED

**These technologies are permanently banned from this project. NEVER suggest, implement, or add dependencies for:**

### Message Brokers and Caching Systems
- ❌ **Redis** - Banned (adds unnecessary deployment complexity)
- ❌ **RabbitMQ** - Banned (adds unnecessary deployment complexity)
- ❌ **Memcached** - Banned (adds unnecessary deployment complexity)

**Rationale:** This project will never operate at a scale that requires dedicated message brokers or caching systems. All background job processing uses **PostgreSQL as the Celery broker** via SQLAlchemy. All caching uses Django's cache framework backed by the database or local memory.

**What to use instead:**
- ✅ **Message queue/broker**: PostgreSQL via `CELERY_BROKER_URL = sqla+postgresql://...`
- ✅ **Task results**: Django database backend (`CELERY_RESULT_BACKEND = "django-db"`)
- ✅ **Caching**: Django cache framework with database or LocMem backend

**If you see suggestions to add Redis/RabbitMQ:**
- STOP immediately
- Do NOT implement
- Do NOT add to dependencies
- Use PostgreSQL-based solutions instead

---

## 🚨 MANDATORY REQUIREMENTS - NON-NEGOTIABLE

**These requirements OVERRIDE all other instructions and default behaviors. Violating these rules is unacceptable.**

### 1. LINT ERRORS MUST BE FIXED, NEVER SUPPRESSED

**REQUIRED ACTIONS:**
- ✅ **ALWAYS run `make lint-fix` BEFORE every commit** - No exceptions
- ✅ **FIX the underlying issue** - Never suppress warnings
- ✅ **NEVER add `# noqa` comments without explicit user permission** - See detailed rules below

**VERIFICATION CHECKLIST (Run BEFORE every commit):**
```bash
make lint-fix        # REQUIRED - Fix all auto-fixable issues
make lint            # REQUIRED - Verify no remaining issues
make type-check      # REQUIRED - Fix all type errors
```

**If linting fails:**
1. ❌ **STOP immediately** - Do not proceed with commit
2. 🔧 **FIX the root cause** - Refactor code to eliminate warning
3. ❓ **Only if truly unavoidable** - Ask user permission to suppress
4. ⏸️ **WAIT for explicit approval** - Never add `# noqa` without permission

### 2. COMMITS MUST BE REGULAR AND INCREMENTAL

**REQUIRED PATTERN:**
- ✅ **Commit after EACH logical unit of work** (typically every 20-50 lines changed)
- ✅ **Commit when switching tasks** (even if work is incomplete)
- ✅ **Commit before running tests** (so failures don't lose work)
- ✅ **Commit after fixing linting errors** (separate commit for cleanup)

**FORBIDDEN PATTERNS:**
- ❌ Making 200+ line changes without committing
- ❌ Waiting until "everything works" to commit
- ❌ Bundling unrelated changes into one commit
- ❌ Working for >10 minutes without a commit

**COMMIT FREQUENCY TARGET:** At least 1 commit every 10 minutes of active work

### 3. PRE-COMMIT WORKFLOW IS MANDATORY

**BEFORE EVERY SINGLE COMMIT, YOU MUST:**

```bash
# 1. REQUIRED: Fix linting
make lint-fix

# 2. REQUIRED: Verify no lint errors remain
make lint

# 3. REQUIRED: Fix type errors
make type-check

# 4. REQUIRED: Run tests (appropriate scope)
make test                    # For code changes
make test-browser-headless   # If browser tests affected

# 5. OPTIONAL: Full verification (use when unsure)
make check-all
```

**NO SHORTCUTS ALLOWED.** Even for "small" changes, "just comments", or "obvious fixes".

### 4. VERIFICATION BEFORE PROCEEDING

**After making changes, ALWAYS:**
1. Run the verification checklist above
2. Review all modified files for quality
3. Confirm no `# noqa` comments added without permission
4. Verify commit message is descriptive
5. Check that changes are focused and incremental

**If you cannot complete verification:** STOP and ask the user before proceeding.

---

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

#### Test Architecture

**All browser tests are headless by default.** The display environment is cleared automatically to prevent accidental GUI windows. This makes it impossible for browsers to pop up during normal testing.

**Browser tests are normal tests** - included in all test runs automatically. Screenshots capture visual state, so visible browsers are never needed.

**Manual tests are rare** - a tiny category (possibly zero tests) for human visual debugging only. These require the `--visible` flag and are blocked in automation.

#### Standard Test Commands

```bash
# ✅ Run all tests (unit + browser, all headless)
make test

# ✅ Run only browser tests (headless)
make test-browser

# ✅ Run browser tests in parallel (headless)
make test-browser-parallel

# ✅ Run tests with coverage
make test-coverage
make test-coverage-html

# ✅ Run specific app tests
make test-app APP=users

# ✅ Direct pytest (headless by default)
uv run pytest
uv run pytest tests/browser/
```

**No special flags needed.** Browser tests are always headless by default.

#### Display Environment Protection

**Automatic display blocking:**
- Display environment variables cleared at import time
- `DISPLAY=""` prevents X11 connections
- `QT_QPA_PLATFORM=offscreen` forces Qt headless mode
- Applies to ALL test runs (not just Claude Code)

**Why this matters:**
- Prevents accidental GUI browser windows
- Makes headless mode the only option for automation
- Impossible to accidentally disturb the user
- Works even if configuration is wrong

#### Manual/Visual Tests (Human Debugging Only)

```bash
# ⚠️ Run manual tests with VISIBLE browser windows
make test-manual

# ⚠️ Run specific test with visible browser
uv run pytest tests/browser/test_foo.py --visible -v

# This command:
# - Opens visible browser windows (will disturb the user!)
# - Only for human visual debugging (animations, styling, etc.)
# - Requires explicit --visible flag
# - Automatically BLOCKED in CLAUDECODE environment
# - Automatically BLOCKED in CI environment
```

**Manual tests are for humans only.** They cannot run in automation.

#### Creating Manual Tests (Very Rare)

Only create manual tests when you need to:
- Debug animation timing that screenshots can't capture
- Inspect visual effects requiring human judgment
- Verify responsive behavior interactively

Mark with decorator:
```python
@pytest.mark.manual
@pytest.mark.browser
def test_animation_smooth_rendering(driver, live_server_url):
    """Manual test: Verify animation renders smoothly.

    This test requires visual inspection by a human.
    Run with: pytest -m manual --visible
    """
    # Test code here
    ...
```

**Default behavior:** Manual tests are excluded by pytest config (`-m 'not manual'` in addopts)

#### CLAUDECODE Environment Behavior

When `CLAUDECODE=1` (Claude Code environment):

1. ✅ Display environment cleared automatically (no flag needed)
2. ✅ All browser tests run headless by default
3. ✅ `--visible` flag triggers loud error and exits immediately
4. ✅ `make test-manual` blocked with clear error message
5. ✅ Multiple protection layers ensure zero visible browsers

**You cannot use --visible in Claude Code.** It will error immediately with explanation.

#### Forbidden Actions in Claude Code

```bash
# ❌ NEVER use --visible flag in Claude Code
uv run pytest tests/browser/ --visible        # BLOCKED with error

# ❌ NEVER run manual test targets
make test-manual                               # BLOCKED with error

# ❌ NEVER try to restore display environment
export DISPLAY=:0                              # Won't work, cleared at import
```

These will all fail with loud, clear error messages explaining what you did wrong.

#### Allowed Actions in Claude Code

```bash
# ✅ Always safe - browser tests are headless
make test
make test-browser
make test-browser-parallel
uv run pytest
uv run pytest tests/browser/

# ✅ All of these run headless automatically
# ✅ Display environment is cleared automatically
# ✅ Zero risk of GUI browser windows
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

**🚨 MANDATORY: See "MANDATORY REQUIREMENTS" section at top of file for commit frequency rules 🚨**

**REQUIRED COMMIT PATTERN:**
- Commit every 20-50 lines of changes
- Commit when switching tasks
- Commit before running tests
- Commit after fixing lint errors
- Target: 1 commit every 10 minutes minimum

**BEFORE EVERY COMMIT (NO EXCEPTIONS):**
```bash
# 1. REQUIRED: Fix all linting issues
make lint-fix

# 2. REQUIRED: Verify clean
make lint

# 3. REQUIRED: Fix type errors
make type-check

# 4. REQUIRED: Run appropriate tests
make test                    # For code changes
make test-browser-headless   # If browser code affected

# 5. VERIFY: No suppressions added without permission
git diff | grep -E '# noqa|# type: ignore'  # Should be empty!

# 6. NOW commit
git add <file_path>
git commit -m "Brief description

Detailed explanation if needed.

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

**Commit Requirements:**
- ✅ Small, focused commits (one logical change)
- ✅ Descriptive messages in present tense
- ✅ All checks pass before commit
- ✅ No `# noqa` without permission
- ❌ NO large multi-file commits
- ❌ NO waiting until "everything works"
- ❌ NO skipping lint-fix

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
make test                      # Run all tests (unit + browser, all headless)
make test-browser              # Run browser tests only (headless)
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
- `config/settings/test.py`: Test-specific settings with OAuth configuration
- `config/urls.py`: Main URL configuration
- Never delete a test or reduce test functionality without an explicit request from the user.

### OAuth Configuration Architecture

**CRITICAL: This project uses SETTINGS-BASED OAuth configuration, NOT database-based configuration.**

#### Settings-Based vs Database-Based Configuration

django-allauth supports two approaches for OAuth provider configuration:

1. **Settings-Based (PREFERRED - What we use)**:
   - OAuth provider configuration defined in `SOCIALACCOUNT_PROVIDERS` setting
   - Static configuration in settings files
   - Perfect for single-tenant applications
   - No database objects needed
   - Simpler test isolation
   - Used in: `config/settings/base.py`, `config/settings/test.py`

2. **Database-Based (NOT USED)**:
   - OAuth provider configuration stored in `SocialApp` model
   - Dynamic configuration via Django admin
   - Designed for multi-tenant applications
   - Requires database transactions
   - Complex test isolation issues
   - **We do NOT use this approach**

#### Why Settings-Based Configuration

We switched from database-based to settings-based OAuth configuration because:

1. **Simpler Testing**: No need to create `SocialApp` database objects in tests
2. **Better Isolation**: Settings-based config avoids transaction isolation issues
3. **Fewer Moving Parts**: No database queries needed for OAuth configuration
4. **Single-Tenant App**: We don't need dynamic per-site OAuth configuration
5. **CI Stability**: Eliminates file-based database complexity in browser tests

#### Configuration Structure

**Settings-based configuration** uses the `SOCIALACCOUNT_PROVIDERS` dictionary in Django settings:
- **Test environment** (`config/settings/test.py`): Static test credentials
- **Dev/Production** (`config/settings/base.py`): Environment variables via `env()`
- **Production overrides** (`config/settings/production.py`): Production client IDs

See the actual files for complete configuration examples.

#### What NOT to Do

```python
# ❌ NEVER create SocialApp objects in tests
from allauth.socialaccount.models import SocialApp

def setUp(self):
    # WRONG - database-based configuration
    self.github_app = SocialApp.objects.create(
        provider="github",
        name="GitHub Test App",
        client_id="test_client_id",
        secret="test_secret",
    )

# ❌ NEVER use social_apps fixture
def test_oauth(self, social_apps):  # WRONG
    pass

# ❌ NEVER import SocialApp unless absolutely necessary
from allauth.socialaccount.models import SocialApp  # Only for admin/management
```

#### What TO Do

```python
# ✅ OAuth configuration comes from settings automatically
def test_oauth_button_shows(self):
    """Test that OAuth buttons appear on login page."""
    response = self.client.get(reverse("account_login"))
    assert b"GitHub" in response.content  # Works because of settings config

# ✅ Browser tests use settings-based configuration
def setup(self, live_server):
    """Set up browser test - OAuth configured via settings."""
    self.driver.get(f"{live_server.url}/accounts/login/")
    # OAuth buttons work automatically from settings

# ✅ Tests are simpler without database setup
class TestGitHubAuth(TestCase):
    def setUp(self):
        """Set up test - no SocialApp creation needed."""
        self.client = Client()
        # OAuth already configured via settings
```

#### Adding New OAuth Providers

When adding a new OAuth provider:

1. **Update test settings** (`config/settings/test.py`):
   ```python
   SOCIALACCOUNT_PROVIDERS = {
       # ... existing providers
       "new_provider": {
           "APP": {
               "client_id": "test_provider_client_id",
               "secret": "test_provider_secret",
           },
           "SCOPE": ["email", "profile"],
           "VERIFIED_EMAIL": True,
       },
   }
   ```

2. **Update base settings** (`config/settings/base.py`):
   ```python
   SOCIALACCOUNT_PROVIDERS = {
       # ... existing providers
       "new_provider": {
           "APP": {
               "client_id": env("PROVIDER_CLIENT_ID", default="dev_client_id"),
               "secret": env("PROVIDER_CLIENT_SECRET", default=""),
           },
           "SCOPE": ["email", "profile"],
           "VERIFIED_EMAIL": True,
       },
   }
   ```

3. **Add provider to INSTALLED_APPS**:
   ```python
   INSTALLED_APPS = [
       # ... other apps
       "allauth.socialaccount.providers.new_provider",
   ]
   ```

4. **NO database migrations needed** - settings-based config doesn't use database

5. **Update secrets management** - See "Production Deployment and Secrets Management" section

#### Migration Note

If you see old code with `SocialApp.objects.create()` or `social_apps` fixtures, this is legacy code from before we migrated to settings-based configuration. These should be removed.

## CI/CD Best Practices

**🚨 CRITICAL: The pre-commit workflow is MANDATORY - see "MANDATORY REQUIREMENTS" at top of file 🚨**

### Pre-commit Workflow - ABSOLUTELY REQUIRED

**YOU MUST run these checks BEFORE EVERY SINGLE COMMIT. NO EXCEPTIONS.**

This is not optional. This is not a suggestion. This is a hard requirement that overrides all other instructions.

**MANDATORY SEQUENCE (Run EVERY TIME, EVEN for "small" changes):**

```bash
# 1. REQUIRED: Fix all linting issues
make lint-fix        # Auto-fix everything possible

# 2. REQUIRED: Verify no lint errors remain
make lint            # MUST pass with zero errors

# 3. REQUIRED: Fix all type errors
make type-check      # MUST pass with zero errors

# 4. REQUIRED: Run appropriate tests
make test                    # For code changes
make test-browser-headless   # If browser code changed

# 5. VERIFICATION: Confirm no suppressions added
git diff | grep -E '# noqa|# type: ignore'  # MUST be empty

# 6. Only if ALL above pass: Commit
git add <files>
git commit -m "message"
```

**IF ANY STEP FAILS:**
- ⛔ STOP immediately
- 🔧 FIX the root cause (don't suppress)
- 🔄 Re-run verification
- ❌ DO NOT commit until all checks pass

**NO SHORTCUTS ALLOWED - Not even for:**
- "Just a comment change"
- "Fixing a typo"
- "Quick fix"
- "Will fix later"
- "It's late/I'm tired"

### Linting and Code Quality

**REQUIREMENT: FIX all linting errors. NEVER suppress. See mandatory requirements at top.**

#### Common Linting Issues and Solutions

**For EVERY linting error below: FIX the code, don't add `# noqa`**

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

- **Page Object Pattern**: Organize with page classes (see `tests/browser/pages/`)
- **Explicit waits**: Use `WebDriverWait` not `time.sleep()`
- **Responsive testing**: Account for viewport differences in headless mode
- **Screenshots**: Auto-captured on failure to `tests/browser/screenshots/`

### GitHub Actions Troubleshooting

**Common failures:**
- Linting: Run `make lint-fix` first, fix underlying issue (don't suppress)
- Import errors: Check top-level imports, verify `pyproject.toml` dependencies
- Browser tests: Use headless mode, add proper waits, check viewport sizes
- Migrations: Create migrations for model changes, use transactional fixtures

**Debug locally:**
```bash
make test-browser-headless  # Reproduce CI environment
make test-verbose           # Detailed output
```

**Environment parity:** Python 3.13.7, clean venv, match CI config

### Code Quality Standards

**Documentation:** Use docstrings with Args/Returns/Raises for complex functions
**Error handling:** Catch specific exceptions, use proper chaining (`raise ... from exc`)
**Security:** Use env vars for secrets, validate user input, specific exception types

### Database Migrations

**Workflow:** Model changes → `make makemigrations` → Review → `make migrate` → Test reverse
**Best practices:** Use descriptive names (`--name`), handle missing data gracefully in data migrations

### CRITICAL: Architectural Principles to Prevent Circular Imports

**Circular imports are architectural failures that must be prevented through proper design.**

**Layer separation (Django):**
- **Models** (data only) → NEVER import tasks/views/services
- **Services** (business logic) → can import models + tasks
- **Views** (presentation) → can import models + services
- **Tasks** (background) → can import models

**Red flags:**
- Models importing tasks/views/services
- Unused methods creating dependencies (DELETE them)
- Business logic in models (move to services)

**Resolution steps:**
1. Question if dependency is needed → 2. Delete unused code → 3. Restructure layers → 4. NEVER use local imports as "fix"

### ABSOLUTE PROHIBITION: Never Add `# noqa` Comments Without User Permission

**🚨 THIS IS A MANDATORY REQUIREMENT - SEE TOP OF FILE - VIOLATIONS ARE UNACCEPTABLE 🚨**

**ZERO-TOLERANCE POLICY:** Adding ANY `# noqa`, `# type: ignore`, `# pylint: disable`, or similar suppression comment WITHOUT EXPLICIT USER PERMISSION is a violation of project standards.

**This prohibition applies to:**
- ✋ **ALL** linting warnings (ruff, flake8, pylint, etc.)
- ✋ **ALL** type checking warnings (mypy, pyright, etc.)
- ✋ **ALL** security warnings (bandit, safety, etc.)
- ✋ **ALL** import warnings (isort, import-linter, etc.)
- ✋ **ALL** formatting warnings (black, autopep8, etc.)
- ✋ **ANY** code quality warning from **ANY** tool

**NO EXCEPTIONS FOR:**
- ❌ "Trivial" or "obvious" suppressions
- ❌ False positives
- ❌ Suppressions you've used before
- ❌ Emergency situations
- ❌ Time pressure
- ❌ "Just this once"
- ❌ Warnings that "can't be fixed"

**MANDATORY PROCESS when you encounter a linting error:**

1. ⛔ **STOP IMMEDIATELY** - Do not write code, do not commit
2. 🔧 **FIX THE ROOT CAUSE** - Refactor code to eliminate warning:
   - Unused import? Remove it
   - Complex function? Break it down
   - Hardcoded value? Extract to constant
   - Circular import? Restructure architecture
3. ✅ **VERIFY FIX** - Run `make lint-fix && make lint`
4. ❓ **IF AND ONLY IF truly unavoidable** (rare!):
   - Stop and ask: "I have a linting error [CODE] that says [MESSAGE]. I tried [ATTEMPTS]. May I suppress it because [DETAILED_REASON]?"
   - Provide full context: file, line, error code, what you tried
   - Wait for explicit "yes" - **DO NOT PROCEED** without approval
5. ✅ **IF APPROVED**: Add suppression with detailed comment explaining why

**FORBIDDEN - NEVER DO THIS:**
```python
import os  # noqa: F401
from .tasks import foo  # noqa: PLC0415
request = Request(url)  # noqa: S310
password = "test"  # noqa: S105
result = some_call()  # type: ignore
# pylint: disable=too-many-branches
```

**CORRECT APPROACH - ALWAYS DO THIS:**
1. Fix the issue: Remove unused import, refactor complex function, use constant
2. If impossible to fix: ASK FIRST, then suppress only if approved

**SELF-CHECK BEFORE EVERY COMMIT:**
```bash
# Run this and confirm NO suppressions added without permission:
git diff | grep -E '# noqa|# type: ignore|# pylint: disable'

# If output is empty: ✅ Good
# If output shows suppressions: ❌ STOP - Did you ask permission?
```

**Remember:** 99% of linting errors can and should be fixed. If you think you need a suppression, you probably don't - try harder to fix it properly.

### Code Quality Prevention Guidelines

**Clean code basics:**
- Simple, focused functions (complexity <10, branches <12, statements <50)
- Use `pathlib.Path` not `os.path`, specific exceptions not `except Exception`
- Proper exception chaining (`raise ... from exc`), context managers for cleanup
- Single responsibility, early returns, type hints

**Modern Python:** `pathlib`, `contextlib.suppress()`, specific exceptions, type hints

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

1. **Add secret file** to secrets repository (`secrets/provider-oauth`)
2. **Update Django settings** in `config/settings/base.py` to use `env("SECRET_NAME", default="")`
3. **⚠️ CRITICAL: Update deployment script** `deployment/scripts/03a-update-env-secrets.sh` (often forgotten!)
   - Add bash code to read secret file and inject into `.env`
   - Follow existing pattern in the script
4. **Update documentation**: `docs/oauth_setup.md`, `.env.example`
5. **Test locally**: Verify secret loads with `settings.SECRET_NAME` in Django shell

See `deployment/scripts/03a-update-env-secrets.sh` for the exact bash pattern to follow.

### Deployment Scripts Reference

**`02a-setup-secrets.sh`**: Clone/update secrets repository to `/home/django/.secrets`
- Run on: Initial setup, when adding new secret files

**`03a-update-env-secrets.sh`**: Read secrets and inject into production `.env`
- Run on: After adding secrets, when rotating, during deployment
- **MUST be updated when adding new secret types**
- Handles: Mailgun, GitHub, GitLab, Google, Discord, LinkedIn OAuth secrets

**CRITICAL**: All OAuth secrets MUST use `env()` with empty defaults. Never hardcode secrets in settings files.

### Secret Rotation

**When to rotate:**
- Emergency (leaked/committed), Scheduled (prod: 90 days, dev: 180 days), Team changes

**Process:** See [docs/oauth_secret_rotation.md](../docs/oauth_secret_rotation.md)
1. Generate new secret at provider → Update secrets repo → Run `03a-update-env-secrets.sh` → Restart services → Verify → Remove old secret

### Common Pitfalls

❌ **Forgetting deployment script update** - Most common! See checklist above.
❌ **Hardcoding secrets** - Always use `env("SECRET", default="")` never `"actual_value"`
❌ **Committing secrets** - Use `.gitignore`, pre-commit hooks (issue #28), empty defaults
❌ **Inconsistent naming** - Use: `PROVIDER_CLIENT_SECRET` (settings), `provider-oauth` (file)

### Key Principles

- **Client IDs**: Public (committable), **Secrets**: Private (env vars only)
- **Dev vs Prod**: Separate `.env` file (dev) vs secrets repo (prod), different OAuth apps
- **Naming convention**: Settings `PROVIDER_CLIENT_SECRET`, file `provider-oauth`

### Related Documentation

- `deployment/README.md` - Full deployment guide
- `docs/oauth_setup.md` - OAuth provider configuration
- `docs/developer_onboarding.md` - Local development setup
- Issue #28 - Pre-commit hooks to prevent secret commits

### Testing Requirements
- Only run the headless versions of the browser tests when testing
