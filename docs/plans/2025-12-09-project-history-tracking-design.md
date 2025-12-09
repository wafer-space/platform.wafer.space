# Project History Tracking Design

**Issue:** <https://github.com/wafer-space/platform.wafer.space/issues/176>
**Date:** 2025-12-09
**Status:** Approved

## Summary

Add automatic change history tracking for the `Project` model using django-simple-history.

## Decision

**Package:** django-simple-history 3.10.1

**Rationale:**
- Most widely adopted (2.4k stars, 371k+ weekly downloads)
- Trivial setup - add `history = HistoricalRecords()` to model
- Excellent admin integration via `SimpleHistoryAdmin`
- Built-in diffing with `diff_against()`
- Queryable history tables using standard Django ORM
- Active maintenance by django-commons

**Documentation:**
- Quick Start: <https://django-simple-history.readthedocs.io/en/stable/quick_start.html>
- Admin Integration: <https://django-simple-history.readthedocs.io/en/latest/admin.html>
- GitHub: <https://github.com/django-commons/django-simple-history>

## Scope

**In scope:** Project model only

**Out of scope (future work):** ProjectFile, ManufacturabilityCheck - these will need different handling

## Implementation

### Step 1: Add Dependency

```bash
uv add django-simple-history
```

### Step 2: Update Settings

`config/settings/base.py`:

```python
INSTALLED_APPS = [
    # ...
    "simple_history",
]

MIDDLEWARE = [
    # ...
    "simple_history.middleware.HistoryRequestMiddleware",
]
```

### Step 3: Update Project Model

`wafer_space/projects/models.py`:

```python
from simple_history.models import HistoricalRecords

class Project(models.Model):
    # ... existing fields ...

    history = HistoricalRecords()
```

### Step 4: Run Migrations

```bash
uv run python manage.py makemigrations
uv run python manage.py migrate
```

### Step 5: Populate History for Existing Records

```bash
uv run python manage.py populate_history --auto
```

### Step 6: Update Admin

`wafer_space/projects/admin.py`:

```python
from simple_history.admin import SimpleHistoryAdmin

@admin.register(Project)
class ProjectAdmin(SimpleHistoryAdmin):
    # ... existing configuration ...
```

## Testing Strategy

Tests in `wafer_space/projects/tests/test_models.py`:

1. **History creation on save** - Verify a history record is created when Project is saved
2. **History creation on update** - Verify changes are tracked with correct field values
3. **History user tracking** - Verify the user who made the change is recorded
4. **History deletion tracking** - Verify delete operations are recorded

### Bulk Operations

Verified: No `QuerySet.update()` or `bulk_create()` calls exist on the Project model.

If added in future, use:
- `bulk_create_with_history()`
- `bulk_update_with_history()`

## Migration Considerations

### For Existing Production Data

The `populate_history --auto` command creates one initial history record per existing Project:
- `history_type = "+"` (created)
- `history_user = None` (no user context available)
- `history_date` = time when populate_history runs

### Deployment Strategy

1. Deploy code with new migration
2. Run `migrate` to create the `HistoricalProject` table
3. Run `populate_history --auto` to backfill existing records

The history table is independent and doesn't block normal operations.

## Files to Modify

| File | Change |
|------|--------|
| `pyproject.toml` | Add `django-simple-history` dependency |
| `config/settings/base.py` | Add to `INSTALLED_APPS` and `MIDDLEWARE` |
| `wafer_space/projects/models.py` | Add `history = HistoricalRecords()` to Project |
| `wafer_space/projects/admin.py` | Change `ProjectAdmin` to inherit from `SimpleHistoryAdmin` |
| `wafer_space/projects/tests/test_models.py` | Add history tracking tests |

## Acceptance Criteria

- [ ] Install django-simple-history
- [ ] Add `HistoricalRecords()` to Project model
- [ ] Add history middleware for user tracking
- [ ] Update ProjectAdmin to use SimpleHistoryAdmin
- [ ] Run migrations
- [ ] Populate history for existing Project records (deployment step)
- [ ] Add tests for history tracking
