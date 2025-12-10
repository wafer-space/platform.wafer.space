# Project History Tracking Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add automatic change history tracking for the Project model using django-simple-history.

**Architecture:** Add `HistoricalRecords()` field to Project model, which creates a shadow table (`HistoricalProject`) that stores a copy of the row after each change. Middleware captures the user making changes. Admin inherits from `SimpleHistoryAdmin` for viewing/reverting history.

**Tech Stack:** django-simple-history 3.10.1, Django 5.2+, PostgreSQL

---

### Task 1: Add django-simple-history Dependency

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add the dependency**

Run:
```bash
cd /home/tim/github/wafer-space/platform/.worktrees/project-history-tracking && uv add django-simple-history
```

Expected: `pyproject.toml` updated with `django-simple-history` in dependencies

**Step 2: Verify installation**

Run:
```bash
cd /home/tim/github/wafer-space/platform/.worktrees/project-history-tracking && uv run python -c "import simple_history; print(simple_history.__version__)"
```

Expected: Version number printed (e.g., `3.10.1`)

**Step 3: Commit**

```bash
cd /home/tim/github/wafer-space/platform/.worktrees/project-history-tracking && git add pyproject.toml uv.lock && git commit -m "deps: add django-simple-history for Project history tracking"
```

---

### Task 2: Add simple_history to INSTALLED_APPS

**Files:**
- Modify: `config/settings/base.py:103-118`

**Step 1: Add to THIRD_PARTY_APPS**

In `config/settings/base.py`, find the `THIRD_PARTY_APPS` list (line 103) and add `"simple_history"` at the end:

```python
THIRD_PARTY_APPS = [
    "crispy_forms",
    "crispy_bootstrap5",
    "allauth",
    "allauth.account",
    "allauth.mfa",
    "allauth.socialaccount",
    # Social providers
    "allauth.socialaccount.providers.github",
    "allauth.socialaccount.providers.gitlab",
    "allauth.socialaccount.providers.openid_connect",  # LinkedIn uses OpenID Connect
    "allauth.socialaccount.providers.google",
    "allauth.socialaccount.providers.discord",
    # Background job processing
    "django_celery_results",
    # History tracking
    "simple_history",
]
```

**Step 2: Verify syntax**

Run:
```bash
cd /home/tim/github/wafer-space/platform/.worktrees/project-history-tracking && uv run python -c "from config.settings.base import INSTALLED_APPS; print('simple_history' in INSTALLED_APPS)"
```

Expected: `True`

**Step 3: Commit**

```bash
cd /home/tim/github/wafer-space/platform/.worktrees/project-history-tracking && git add config/settings/base.py && git commit -m "settings: add simple_history to INSTALLED_APPS"
```

---

### Task 3: Add HistoryRequestMiddleware

**Files:**
- Modify: `config/settings/base.py:174-186`

**Step 1: Add middleware**

In `config/settings/base.py`, find the `MIDDLEWARE` list (line 174) and add the history middleware at the end:

```python
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "wafer_space.legal.middleware.TOSAcceptanceMiddleware",
    # History tracking - captures user for each change
    "simple_history.middleware.HistoryRequestMiddleware",
]
```

**Step 2: Verify syntax**

Run:
```bash
cd /home/tim/github/wafer-space/platform/.worktrees/project-history-tracking && uv run python -c "from config.settings.base import MIDDLEWARE; print('simple_history.middleware.HistoryRequestMiddleware' in MIDDLEWARE)"
```

Expected: `True`

**Step 3: Commit**

```bash
cd /home/tim/github/wafer-space/platform/.worktrees/project-history-tracking && git add config/settings/base.py && git commit -m "settings: add HistoryRequestMiddleware for user tracking"
```

---

### Task 4: Add HistoricalRecords to Project Model

**Files:**
- Modify: `wafer_space/projects/models.py:13` (imports)
- Modify: `wafer_space/projects/models.py:134` (after estimated_cost field)

**Step 1: Add import**

In `wafer_space/projects/models.py`, add the import after line 12 (after `from django.utils import timezone`):

```python
from simple_history.models import HistoricalRecords
```

**Step 2: Add history field to Project**

In `wafer_space/projects/models.py`, add the history field after the `estimated_cost` field (around line 134), before the `class Meta`:

```python
    # Manufacturing details
    estimated_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )

    # Change history tracking
    history = HistoricalRecords()

    class Meta:
```

**Step 3: Verify syntax**

Run:
```bash
cd /home/tim/github/wafer-space/platform/.worktrees/project-history-tracking && uv run python -c "from wafer_space.projects.models import Project; print(hasattr(Project, 'history'))"
```

Expected: `True`

**Step 4: Commit**

```bash
cd /home/tim/github/wafer-space/platform/.worktrees/project-history-tracking && git add wafer_space/projects/models.py && git commit -m "feat: add HistoricalRecords to Project model"
```

---

### Task 5: Create and Apply Migration

**Files:**
- Create: `wafer_space/projects/migrations/00XX_historicalproject.py` (auto-generated)

**Step 1: Create migration**

Run:
```bash
cd /home/tim/github/wafer-space/platform/.worktrees/project-history-tracking && uv run python manage.py makemigrations projects --name historicalproject
```

Expected: Migration file created in `wafer_space/projects/migrations/`

**Step 2: Apply migration**

Run:
```bash
cd /home/tim/github/wafer-space/platform/.worktrees/project-history-tracking && uv run python manage.py migrate
```

Expected: Migration applied successfully

**Step 3: Verify table exists**

Run:
```bash
cd /home/tim/github/wafer-space/platform/.worktrees/project-history-tracking && uv run python -c "from django.db import connection; cursor = connection.cursor(); cursor.execute(\"SELECT tablename FROM pg_tables WHERE tablename = 'projects_historicalproject'\"); print(cursor.fetchone())"
```

Expected: `('projects_historicalproject',)`

**Step 4: Commit**

```bash
cd /home/tim/github/wafer-space/platform/.worktrees/project-history-tracking && git add wafer_space/projects/migrations/ && git commit -m "migrations: add HistoricalProject table"
```

---

### Task 6: Update ProjectAdmin to Use SimpleHistoryAdmin

**Files:**
- Modify: `wafer_space/projects/admin.py:3` (imports)
- Modify: `wafer_space/projects/admin.py:12` (class definition)

**Step 1: Add import**

In `wafer_space/projects/admin.py`, add the import after line 3 (after `from django.contrib import admin`):

```python
from simple_history.admin import SimpleHistoryAdmin
```

**Step 2: Change ProjectAdmin base class**

In `wafer_space/projects/admin.py`, change line 12 from:

```python
class ProjectAdmin(admin.ModelAdmin):
```

to:

```python
class ProjectAdmin(SimpleHistoryAdmin):
```

**Step 3: Verify syntax**

Run:
```bash
cd /home/tim/github/wafer-space/platform/.worktrees/project-history-tracking && uv run python -c "from wafer_space.projects.admin import ProjectAdmin; from simple_history.admin import SimpleHistoryAdmin; print(issubclass(ProjectAdmin, SimpleHistoryAdmin))"
```

Expected: `True`

**Step 4: Commit**

```bash
cd /home/tim/github/wafer-space/platform/.worktrees/project-history-tracking && git add wafer_space/projects/admin.py && git commit -m "admin: use SimpleHistoryAdmin for Project history view"
```

---

### Task 7: Write Failing Test - History Created on Save

**Files:**
- Modify: `wafer_space/projects/tests/test_models.py`

**Step 1: Write the failing test**

Add at the end of `wafer_space/projects/tests/test_models.py`:

```python
@pytest.mark.django_db
class TestProjectHistory:
    """Test Project history tracking with django-simple-history."""

    def test_history_created_on_initial_save(self):
        """Verify that creating a Project creates a history record."""
        from wafer_space.projects.tests.factories import ProjectFactory

        project = ProjectFactory(name="Test Project")

        assert project.history.count() == 1
        history_record = project.history.first()
        assert history_record.name == "Test Project"
        assert history_record.history_type == "+"  # Created
```

**Step 2: Run test to verify it passes**

Run:
```bash
cd /home/tim/github/wafer-space/platform/.worktrees/project-history-tracking && uv run pytest wafer_space/projects/tests/test_models.py::TestProjectHistory::test_history_created_on_initial_save -v
```

Expected: PASS (history tracking is already set up)

**Step 3: Commit**

```bash
cd /home/tim/github/wafer-space/platform/.worktrees/project-history-tracking && git add wafer_space/projects/tests/test_models.py && git commit -m "test: verify history record created on Project save"
```

---

### Task 8: Write Test - History Tracks Updates

**Files:**
- Modify: `wafer_space/projects/tests/test_models.py`

**Step 1: Write the test**

Add to the `TestProjectHistory` class:

```python
    def test_history_tracks_field_changes(self):
        """Verify that updating a Project creates a new history record."""
        from wafer_space.projects.tests.factories import ProjectFactory

        project = ProjectFactory(name="Original Name")
        original_count = project.history.count()

        # Update the project
        project.name = "Updated Name"
        project.save()

        assert project.history.count() == original_count + 1
        latest = project.history.first()
        assert latest.name == "Updated Name"
        assert latest.history_type == "~"  # Updated
```

**Step 2: Run test**

Run:
```bash
cd /home/tim/github/wafer-space/platform/.worktrees/project-history-tracking && uv run pytest wafer_space/projects/tests/test_models.py::TestProjectHistory::test_history_tracks_field_changes -v
```

Expected: PASS

**Step 3: Commit**

```bash
cd /home/tim/github/wafer-space/platform/.worktrees/project-history-tracking && git add wafer_space/projects/tests/test_models.py && git commit -m "test: verify history tracks Project field changes"
```

---

### Task 9: Write Test - History Tracks User

**Files:**
- Modify: `wafer_space/projects/tests/test_models.py`

**Step 1: Write the test**

Add to the `TestProjectHistory` class:

```python
    def test_history_tracks_user_when_set(self):
        """Verify that history records the user who made the change."""
        from simple_history.models import HistoricalRecords

        from wafer_space.projects.tests.factories import ProjectFactory
        from wafer_space.users.tests.factories import UserFactory

        user = UserFactory()
        project = ProjectFactory(name="Test")

        # Simulate a change with user context
        project.name = "Changed by user"
        project._history_user = user  # Set history user directly
        project.save()

        latest = project.history.first()
        assert latest.history_user == user
```

**Step 2: Run test**

Run:
```bash
cd /home/tim/github/wafer-space/platform/.worktrees/project-history-tracking && uv run pytest wafer_space/projects/tests/test_models.py::TestProjectHistory::test_history_tracks_user_when_set -v
```

Expected: PASS

**Step 3: Commit**

```bash
cd /home/tim/github/wafer-space/platform/.worktrees/project-history-tracking && git add wafer_space/projects/tests/test_models.py && git commit -m "test: verify history tracks user who made changes"
```

---

### Task 10: Write Test - History Tracks Deletion

**Files:**
- Modify: `wafer_space/projects/tests/test_models.py`

**Step 1: Write the test**

Add to the `TestProjectHistory` class:

```python
    def test_history_tracks_deletion(self):
        """Verify that deleting a Project creates a deletion history record."""
        from wafer_space.projects.models import Project
        from wafer_space.projects.tests.factories import ProjectFactory

        project = ProjectFactory(name="To Be Deleted")
        project_id = project.id

        # Delete the project
        project.delete()

        # History should still exist for the deleted project
        history = Project.history.filter(id=project_id)
        assert history.exists()

        # Last record should be a deletion
        latest = history.first()
        assert latest.history_type == "-"  # Deleted
```

**Step 2: Run test**

Run:
```bash
cd /home/tim/github/wafer-space/platform/.worktrees/project-history-tracking && uv run pytest wafer_space/projects/tests/test_models.py::TestProjectHistory::test_history_tracks_deletion -v
```

Expected: PASS

**Step 3: Commit**

```bash
cd /home/tim/github/wafer-space/platform/.worktrees/project-history-tracking && git add wafer_space/projects/tests/test_models.py && git commit -m "test: verify history tracks Project deletion"
```

---

### Task 11: Run Full Test Suite and Quality Checks

**Files:** None (verification only)

**Step 1: Run lint-fix**

Run:
```bash
cd /home/tim/github/wafer-space/platform/.worktrees/project-history-tracking && make lint-fix
```

Expected: Code formatted successfully

**Step 2: Run lint**

Run:
```bash
cd /home/tim/github/wafer-space/platform/.worktrees/project-history-tracking && make lint
```

Expected: No errors

**Step 3: Run type-check**

Run:
```bash
cd /home/tim/github/wafer-space/platform/.worktrees/project-history-tracking && make type-check
```

Expected: No errors

**Step 4: Run full test suite**

Run:
```bash
cd /home/tim/github/wafer-space/platform/.worktrees/project-history-tracking && make test
```

Expected: All tests pass

**Step 5: Commit any lint fixes if needed**

```bash
cd /home/tim/github/wafer-space/platform/.worktrees/project-history-tracking && git add -A && git diff --cached --quiet || git commit -m "style: apply lint fixes"
```

---

### Task 12: Update Design Document with Completion Status

**Files:**
- Modify: `docs/plans/2025-12-09-project-history-tracking-design.md`

**Step 1: Update acceptance criteria**

Update the acceptance criteria section to mark completed items:

```markdown
## Acceptance Criteria

- [x] Install django-simple-history
- [x] Add `HistoricalRecords()` to Project model
- [x] Add history middleware for user tracking
- [x] Update ProjectAdmin to use SimpleHistoryAdmin
- [x] Run migrations
- [ ] Populate history for existing Project records (deployment step)
- [x] Add tests for history tracking
```

**Step 2: Commit**

```bash
cd /home/tim/github/wafer-space/platform/.worktrees/project-history-tracking && git add docs/plans/ && git commit -m "docs: mark implementation tasks complete"
```

---

## Deployment Notes

After merging this branch to main and deploying:

1. Run migrations: `uv run python manage.py migrate`
2. Populate history for existing records: `uv run python manage.py populate_history --auto`

The `populate_history` command creates initial history records for all existing Projects.
