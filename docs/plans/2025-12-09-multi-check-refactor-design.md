# ManufacturabilityCheck Multi-Check Refactor Design

**Issue:** <https://github.com/wafer-space/platform.wafer.space/issues/169>
**Branch:** `feature/manufacturability-check-refactor`
**Date:** 2025-12-09

## Summary

Refactor `ManufacturabilityCheck` from a `OneToOneField` to a `ForeignKey` relationship with `ProjectFile`, allowing multiple checks per file. This enables:

- Re-running checks when DRC rules or tools are updated
- Preserving full history of all check attempts (including system error retries)
- Better debugging with complete records of each attempt

## Design Principles

**CRITICAL - Apply throughout implementation:**

1. **NO BACKWARDS COMPATIBILITY SHIMS**
   - Don't create `project_file.manufacturability_check` as an alias
   - Don't add fallback logic like `getattr(pf, 'manufacturability_check', None) or pf.latest_manufacturability_check`
   - Fix every callsite directly

2. **NO DEAD CODE**
   - Delete `reset_for_retry()` entirely
   - Delete `retry_count` and `max_retries` fields
   - Delete any tests for removed functionality
   - Delete the code in `mark_finished()` that copies values to Project

3. **ACTIVELY SEARCH FOR OBSOLETE CODE**
   - When touching any file, look for references to removed fields/methods
   - Find tests that no longer make sense given the new model
   - Remove dead code paths that were only reached by old behavior

4. **REMIND SUBAGENTS**
   - When spawning implementation agents, explicitly state: "No backwards compatibility. Fix callsites directly. Delete obsolete code and tests."

---

## Model Changes

### ManufacturabilityCheck

**Change `project_file` from OneToOneField to ForeignKey:**

```python
project_file = models.ForeignKey(
    "ProjectFile",
    on_delete=models.CASCADE,
    related_name="manufacturability_checks",  # plural now
)
```

**Add trigger reason tracking:**

```python
class TriggerReason(models.TextChoices):
    INITIAL = "initial", "Initial Check"
    DRC_UPDATE = "drc_update", "DRC Rules Updated"
    ADMIN_RERUN = "admin_rerun", "Admin Requested Re-run"
    RETRY = "retry", "Retry After Error"

trigger_reason = models.CharField(
    max_length=20,
    choices=TriggerReason.choices,
    default=TriggerReason.INITIAL,
)
```

**Add parent check reference (flat tree structure):**

```python
parent_check = models.ForeignKey(
    "self",
    on_delete=models.CASCADE,
    null=True,
    blank=True,
    related_name="retry_checks",
    help_text="Original check this is a retry of (null if not a retry)",
)
```

**Remove fields:**
- `retry_count`
- `max_retries`

**Remove methods:**
- `reset_for_retry()`
- `can_retry()` (rewrite to use retry chain)

**Update methods:**
- `mark_finished()` - remove code that copies values to Project

### ProjectFile

**Add property:**

```python
@property
def latest_manufacturability_check(self) -> "ManufacturabilityCheck | None":
    """Get the most recent manufacturability check.

    Returns None if no checks exist yet.
    Ordered by -created_at (newest first).
    """
    return self.manufacturability_checks.first()
```

### Project

**Remove stored fields (convert to derived properties):**

```python
# REMOVE from database:
# - is_manufacturable (BooleanField)
# - manufacturability_errors (JSONField)
# - check_completed_at (DateTimeField)

@property
def is_manufacturable(self) -> bool | None:
    """Derived from latest completed check on submitted file."""
    if not self.submitted_file:
        return None
    check = self.submitted_file.latest_manufacturability_check
    if not check or check.status != ManufacturabilityCheck.Status.FINISHED:
        return None
    return check.is_manufacturable

@property
def manufacturability_errors(self) -> list[str]:
    """Derived from latest completed check."""
    if not self.submitted_file:
        return []
    check = self.submitted_file.latest_manufacturability_check
    if not check or check.status != ManufacturabilityCheck.Status.FINISHED:
        return []
    return check.errors

@property
def check_completed_at(self) -> datetime | None:
    """Derived from latest completed check."""
    if not self.submitted_file:
        return None
    check = self.submitted_file.latest_manufacturability_check
    if not check or check.status != ManufacturabilityCheck.Status.FINISHED:
        return None
    return check.analysis_completed_at
```

---

## Retry Chaining

**Flat tree structure** - all retries point to original check:

```text
Check #1 (INITIAL, parent=null) → ERROR
├── Check #2 (RETRY, parent=#1) → ERROR
├── Check #3 (RETRY, parent=#1) → ERROR
└── Check #4 (RETRY, parent=#1) → FINISHED
```

**Create retry function (in services.py):**

```python
def create_retry_check(failed_check: ManufacturabilityCheck) -> ManufacturabilityCheck:
    """Create a new check as a retry of a failed one.

    Args:
        failed_check: The check that failed (must be in ERROR status)

    Returns:
        New ManufacturabilityCheck in PENDING status

    Raises:
        ValueError: If failed_check is not in ERROR status
        MaxRetriesExceededError: If retry limit reached
    """
    if failed_check.status != ManufacturabilityCheck.Status.ERROR:
        msg = f"Can only retry ERROR checks, not {failed_check.status}"
        raise ValueError(msg)

    # Find original check (handles both first retry and subsequent)
    original = failed_check.parent_check or failed_check

    # Check retry limit
    retry_count = original.retry_checks.count()
    max_retries = 3  # Could be a setting
    if retry_count >= max_retries:
        raise MaxRetriesExceededError(retry_count=retry_count, max_retries=max_retries)

    return ManufacturabilityCheck.objects.create(
        project=original.project,
        project_file=original.project_file,
        trigger_reason=ManufacturabilityCheck.TriggerReason.RETRY,
        parent_check=original,
    )
```

---

## Cancellation Strategy

New check creation does NOT cancel existing checks inline. Cleanup task handles it:

```python
from django.db.models import Exists, OuterRef

def cancel_superseded_checks():
    """Cancel in-progress checks that have been superseded by newer checks."""

    # Subquery: does a newer check exist for the same file?
    newer_exists = ManufacturabilityCheck.objects.filter(
        project_file=OuterRef('project_file'),
        created_at__gt=OuterRef('created_at'),
    )

    # Single query to find all superseded checks
    superseded = ManufacturabilityCheck.objects.filter(
        status__in=ManufacturabilityCheck.Status.in_progress(),
    ).filter(
        Exists(newer_exists)
    )

    # Iterate for mark_cancelling() (has state validation + logging)
    for check in superseded:
        check.mark_cancelling(reason="Superseded by newer check")
```

---

## Migration Strategy

**Migration 1: Add new fields (non-destructive)**

```python
operations = [
    migrations.AddField(
        model_name='manufacturabilitycheck',
        name='trigger_reason',
        field=models.CharField(max_length=20, choices=[...], default='initial'),
    ),
    migrations.AddField(
        model_name='manufacturabilitycheck',
        name='parent_check',
        field=models.ForeignKey(
            'self', null=True, blank=True,
            on_delete=models.CASCADE, related_name='retry_checks',
        ),
    ),
]
```

**Migration 2: Convert OneToOneField to ForeignKey**

```python
operations = [
    migrations.AlterField(
        model_name='manufacturabilitycheck',
        name='project_file',
        field=models.ForeignKey(
            'ProjectFile', on_delete=models.CASCADE,
            related_name='manufacturability_checks',
        ),
    ),
]
```

**Migration 3: Remove old fields from ManufacturabilityCheck**

```python
operations = [
    migrations.RemoveField('manufacturabilitycheck', 'retry_count'),
    migrations.RemoveField('manufacturabilitycheck', 'max_retries'),
]
```

**Migration 4: Remove old fields from Project**

```python
operations = [
    migrations.RemoveField('project', 'is_manufacturable'),
    migrations.RemoveField('project', 'manufacturability_errors'),
    migrations.RemoveField('project', 'check_completed_at'),
]
```

**Existing data:** All existing checks get `trigger_reason=INITIAL` and `parent_check=null`.

---

## Template & UI Updates

### Search patterns

```bash
grep -r "manufacturability_check" templates/
grep -r "is_manufacturable" templates/
grep -r "manufacturability_errors" templates/
grep -r "check_completed_at" templates/
```

### Templates to update

| Template | Changes Needed |
|----------|----------------|
| Project detail page | Show multiple checks, latest expanded, older collapsed |
| Project list/dashboard | Verify check status works with property |
| Admin templates | Update inline display for multiple checks |
| Check status fragments | Update any HTMX partials |
| Email templates | Verify any that reference check results |

### UI behavior

**Project detail page:**
- Show check history section with accordion
- Latest check prominent at top
- Retry chain visualization (show "Retry of Check #X")
- Trigger reason badge (Initial, DRC Update, Admin Re-run, Retry)

**Admin interface:**
- Update `ManufacturabilityCheckAdmin` list display and filters
- Add `trigger_reason` and `parent_check` to admin fields
- Consider inline showing retry chain

---

## Code Updates Summary

| Pattern to find | Replace with |
|-----------------|--------------|
| `project_file.manufacturability_check` | `project_file.latest_manufacturability_check` |
| `project.is_manufacturable` (field writes) | Remove - now derived |
| `project.manufacturability_errors` (field writes) | Remove - now derived |
| `project.check_completed_at` (field writes) | Remove - now derived |
| `check.reset_for_retry()` | `create_retry_check(check)` |
| `check.retry_count` | Derive from `original.retry_checks.count()` |
| `check.can_retry()` | Rewrite using retry chain |

**Delete entirely:**
- `ManufacturabilityCheck.reset_for_retry()` method
- `ManufacturabilityCheck.retry_count` field
- `ManufacturabilityCheck.max_retries` field
- Code in `mark_finished()` that writes to Project fields
- All tests for above functionality

---

## Implementation Order

1. Add new fields (trigger_reason, parent_check) - non-breaking
2. Add `latest_manufacturability_check` property to ProjectFile
3. Add derived properties to Project (alongside existing fields temporarily)
4. Update all code references to use new patterns
5. Update templates and UI
6. Convert OneToOneField to ForeignKey
7. Remove old fields and methods
8. Delete obsolete tests
9. Final cleanup pass - search for any remaining references
