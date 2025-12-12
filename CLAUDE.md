# CLAUDE.md

Guidance for Claude Code when working with this repository.

## 🚫 BANNED TECHNOLOGIES - ABSOLUTELY PROHIBITED

**Never suggest, implement, or add dependencies for:**
- ❌ **Redis** - Banned
- ❌ **RabbitMQ** - Banned
- ❌ **Memcached** - Banned

**Use instead:**
- ✅ Message queue: PostgreSQL via `CELERY_BROKER_URL = sqla+postgresql://...`
- ✅ Task results: `CELERY_RESULT_BACKEND = "django-db"`
- ✅ Caching: Django cache framework with database or LocMem backend

---

## 🚨 MANDATORY REQUIREMENTS - NON-NEGOTIABLE

**These requirements OVERRIDE all other instructions. Violating these rules is unacceptable.**

### 1. LINT ERRORS MUST BE FIXED, NEVER SUPPRESSED

```bash
make lint-fix    # REQUIRED before every commit
make lint        # REQUIRED - verify clean
make type-check  # REQUIRED - fix all type errors
```

**NEVER add `# noqa`, `# type: ignore`, or similar without explicit user permission.**

If linting fails:
1. ❌ **STOP** - Do not proceed with commit
2. 🔧 **FIX the root cause** - Refactor code to eliminate warning
3. ❓ **Only if truly unavoidable** - Ask user permission to suppress
4. ⏸️ **WAIT for explicit approval** - Never suppress without permission

### 2. COMMITS MUST BE REGULAR AND INCREMENTAL

- ✅ Commit every 20-50 lines of changes
- ✅ Commit when switching tasks
- ✅ Commit before running tests
- ❌ Never make 200+ line changes without committing
- ❌ Never wait until "everything works" to commit

**Target:** At least 1 commit every 10 minutes of active work

### 3. PRE-COMMIT WORKFLOW IS MANDATORY

**Before EVERY commit, run:**
```bash
make lint-fix && make lint && make type-check && make test
```

All checks must pass. **NO SHORTCUTS** - not even for "small" changes or "just comments".

### 4. NEVER CREATE CIRCULAR IMPORTS

**Circular imports are architectural failures. They are PROHIBITED.**

**Layer separation (MUST follow):**
- **Models** → NEVER import tasks/views/services
- **Services** → can import models + tasks
- **Views** → can import models + services
- **Tasks** → can import models only

```python
# ❌ FORBIDDEN - models.py importing tasks
from .tasks import process_model  # NEVER do this in models

# ❌ FORBIDDEN - using local imports to "fix" circular imports
def some_method(self):
    from .tasks import some_task  # This hides the problem, doesn't fix it
```

**If you encounter circular imports:**
1. Restructure architecture - move logic to services layer
2. Delete unused methods creating the dependency
3. NEVER use local imports as a workaround

---

## DEVELOPMENT COMMANDS

**Always prefer Makefile commands.** Run `make help` for all available commands.

**Key commands:**
```bash
make runserver           # Dev server (port 8081)
make test                # All tests (headless)
make test-browser        # Browser tests (headless)
make lint-fix            # Fix code style
make migrate             # Apply migrations
make check-all           # All quality checks
```

**Direct pytest** only for specific targeting:
```bash
uv run pytest path/to/test.py::TestClass::test_method -v
```

---

## TESTING

**CRITICAL: All browser tests run headless by default.**

- `make test` - all tests (unit + browser, headless)
- `make test-browser` - browser tests only (headless)
- ❌ **NEVER** use `--visible` flag in Claude Code (blocked with error)
- ❌ **NEVER** run `make test-manual` (for human debugging only)

**Browser test best practices:**
- Use `WebDriverWait`, never `time.sleep()`
- Screenshots auto-captured on failure to `tests/browser/screenshots/`
- Use Page Object pattern (see `tests/browser/pages/`)

---

## PROJECT ARCHITECTURE

Django 5.2+ application for wafer.space silicon manufacturing.

**Structure:**
- `config/settings/` - 4 environments (dev, pytest, stage, prod) with unified 15-section structure
- `wafer_space/` - Main application code
- `tests/` - pytest-django with factory-boy fixtures

**Tools:** uv (packages), ruff (lint/format), mypy (types), djlint (templates)

**Key files:**
- `pyproject.toml` - Dependencies and tool config
- `config/settings/base.py` - Core Django settings
- Never delete tests without explicit user request

---

## OAUTH CONFIGURATION

**CRITICAL: This project uses SETTINGS-BASED OAuth, NOT database-based.**

- Configuration in `SOCIALACCOUNT_PROVIDERS` setting
- ❌ **NEVER** create `SocialApp` database objects
- ❌ **NEVER** use `social_apps` fixtures in tests
- OAuth works automatically from settings - no setup needed in tests

**Adding new providers:** See `docs/oauth_setup.md`

**Environment pattern:**
- `base.py`: All credentials set to `None` (fail-fast)
- Each environment overrides with its own credentials
- Client IDs hardcoded, secrets via `env()` **without defaults**

---

## CODE QUALITY STANDARDS

### Ruff Rules We Enforce

| Code | Issue | Fix |
|------|-------|-----|
| T201 | Print statements | Use `logging.getLogger(__name__)` |
| E501 | Lines >88 chars | Break into multiple lines |
| EM102 | F-strings in exceptions | Assign message to variable first |
| FBT002/3 | Boolean positional args | Use keyword-only: `def fn(*, flag=True)` |
| S105 | Hardcoded passwords | Use constants: `TEST_PASSWORD = "..."` |

### Type Hints (REQUIRED)

- All public functions must have type hints
- Use `from __future__ import annotations` for forward references
- Fix mypy errors, don't ignore them

### Exception Handling

```python
# ✅ Correct: specific exception + chaining
try:
    result = external_api_call()
except RequestException as exc:
    msg = f"API failed: {exc}"
    raise ServiceError(msg) from exc

# ❌ Wrong: bare except or Exception
except:  # Never
except Exception:  # Too broad
```

### Test Standards

- Use factory-boy for test data, not fixtures
- One assertion concept per test
- Test file mirrors source: `wafer_space/users/models.py` → `wafer_space/users/tests/test_models.py`

### Documentation Standards

- All fenced code blocks must have a language specifier (e.g., `python`, `bash`, `text`)
- Wrap URLs in angle brackets: `<https://example.com>` (avoids MD034 lint error)
- Use proper markdown link syntax for clickable links: `[Link text](url)`

---

## SECRETS MANAGEMENT

**Two-repository approach:**
- Main repo: Code and non-sensitive config
- Secrets repo: `platform.wafer.space-secrets` (private)

**CRITICAL: When adding new secrets:**
1. Set to `None` in `base.py`
2. Override in each environment file
3. Add secret file to secrets repo
4. **⚠️ Update `deployment/scripts/03a-update-env-secrets.sh`** (often forgotten!)
5. Update `docs/oauth_setup.md` and `.env.example`

**Key principle:** Client IDs are public (hardcoded), secrets use `env()` without defaults.

See `deployment/README.md` for full deployment guide.

---

## .ENV FILES - SECRETS ONLY

**`.env` files are for secrets and passwords ONLY - not for settings.**

- ✅ **DO** put in `.env`: API keys, client secrets, database passwords, tokens
- ❌ **DON'T** put in `.env`: Timeouts, limits, feature flags, configuration values

**Why:** Settings belong in `config/settings/` where they are:
- Version controlled
- Environment-specific (dev.py, stage.py, prod.py)
- Type-checked and validated
- Documented with comments

**If a value can be committed to the repository, it goes in settings, not `.env`.**

---

## GIT WORKTREES

When using git worktrees for parallel development, **symlink the `.env` file** from the main repository to keep settings in one location:

```bash
# From within the worktree directory, get the main repo path and create symlink
MAIN_REPO=$(git worktree list | head -1 | awk '{print $1}')
ln -s "$MAIN_REPO/.env" .env
```

**Why:** This ensures all worktrees share the same secrets and development settings, avoiding:
- Duplicated secrets across multiple `.env` files
- Inconsistent configuration between worktrees
- Forgotten updates when secrets change

**Note:** The `.env` file is in `.gitignore`, so the symlink won't be committed.

---

## CELERY ARCHITECTURE

For comprehensive Celery documentation, see:
- [Celery Architecture](docs/celery_architecture.md) - Queue naming, state machine, decorators
- [Celery Tasks Reference](docs/celery_tasks_reference.md) - Complete task listing

### Queue Naming Convention

Queues follow the pattern: `<protocol>:<mode>:<function>`

- **Protocol:** `none`, `http`, `dock`, `mail` (system access required)
- **Mode:** `ro` (read-only), `rw` (read-write)
- **Function:** `default`, `downloads`, `checks-orch`, `checks-fast`, etc.

Example: `dock:ro:checks-fast` = Docker access, read-only, fast check operations

### Debugging: Worker Restart Is Not the Issue

**The development environment auto-restarts Celery workers on code changes. Worker restart is not the problem.**

When you see Celery errors like "unregistered task", the issue is your code - not a missing restart:

```python
# ❌ This does NOT register a new task name:
scan_and_queue = process_check_queue  # Just a Python variable!

# ✅ The config must reference the actual decorated function:
CELERY_BEAT_SCHEDULE = {
    "my-task": {
        "task": "app.tasks.process_check_queue",  # Must match @shared_task
    }
}
```
