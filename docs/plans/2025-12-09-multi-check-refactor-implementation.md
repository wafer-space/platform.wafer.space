# ManufacturabilityCheck Multi-Check Refactor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refactor ManufacturabilityCheck from OneToOneField to ForeignKey, enabling multiple checks per ProjectFile with full history preservation.

**Architecture:** Add `trigger_reason` and `parent_check` fields to track why checks were created and link retries. Convert Project's stored manufacturability fields to derived properties. Replace `reset_for_retry()` with `create_retry_check()` service function.

**Tech Stack:** Django 5.2+, PostgreSQL, pytest, factory-boy

---

## Critical Instructions for Implementation

**REPEAT THESE TO YOURSELF AND ALL SUBAGENTS:**

1. **NO BACKWARDS COMPATIBILITY** - Do not create aliases, shims, or fallback logic. Fix every callsite directly.
2. **DELETE OBSOLETE CODE** - When removing functionality, delete tests for it too. Search actively for dead code.
3. **NO FALLBACK PATTERNS** - Never write `getattr(x, 'old', None) or x.new`. Just use `x.new`.
4. **FIX, DON'T HIDE** - If code breaks, fix the caller. Don't add compatibility layers.

When spawning subagents, include: *"No backwards compatibility. Fix callsites directly. Delete obsolete code and tests."*

---

## Task 1: Add TriggerReason Enum and trigger_reason Field

**Files:**
- Modify: `wafer_space/projects/models.py:1137-1160`
- Create: `wafer_space/projects/migrations/00XX_add_trigger_reason.py`
- Test: `wafer_space/projects/tests/test_models.py`

**Step 1: Write the failing test**

Add to `wafer_space/projects/tests/test_models.py`:

```python
class TestManufacturabilityCheckTriggerReason:
    """Tests for ManufacturabilityCheck.TriggerReason and trigger_reason field."""

    def test_trigger_reason_choices_exist(self):
        """TriggerReason enum has expected choices."""
        choices = ManufacturabilityCheck.TriggerReason.choices
        assert ("initial", "Initial Check") in choices
        assert ("drc_update", "DRC Rules Updated") in choices
        assert ("admin_rerun", "Admin Requested Re-run") in choices
        assert ("retry", "Retry After Error") in choices

    def test_trigger_reason_default_is_initial(self):
        """New checks default to INITIAL trigger reason."""
        check = ManufacturabilityCheckFactory()
        assert check.trigger_reason == ManufacturabilityCheck.TriggerReason.INITIAL

    def test_trigger_reason_can_be_set(self):
        """trigger_reason can be set to any valid choice."""
        check = ManufacturabilityCheckFactory(
            trigger_reason=ManufacturabilityCheck.TriggerReason.DRC_UPDATE
        )
        assert check.trigger_reason == ManufacturabilityCheck.TriggerReason.DRC_UPDATE
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckTriggerReason -v`
Expected: FAIL with "TriggerReason not defined"

**Step 3: Implement TriggerReason enum and field**

In `wafer_space/projects/models.py`, inside `ManufacturabilityCheck` class, after the `Status` class (around line 1150):

```python
    class TriggerReason(models.TextChoices):
        INITIAL = "initial", "Initial Check"
        DRC_UPDATE = "drc_update", "DRC Rules Updated"
        ADMIN_RERUN = "admin_rerun", "Admin Requested Re-run"
        RETRY = "retry", "Retry After Error"
```

Add field after `status` field (around line 1222):

```python
    trigger_reason = models.CharField(
        max_length=20,
        choices=TriggerReason.choices,
        default=TriggerReason.INITIAL,
        help_text="Why this check was triggered",
    )
```

**Step 4: Create migration**

Run: `uv run python manage.py makemigrations projects --name add_trigger_reason`

**Step 5: Apply migration**

Run: `uv run python manage.py migrate`

**Step 6: Run test to verify it passes**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckTriggerReason -v`
Expected: PASS

**Step 7: Commit**

```bash
git add wafer_space/projects/models.py wafer_space/projects/migrations/ wafer_space/projects/tests/test_models.py
git commit -m "feat: add TriggerReason enum and trigger_reason field to ManufacturabilityCheck"
```

---

## Task 2: Add parent_check Self-Referential ForeignKey

**Files:**
- Modify: `wafer_space/projects/models.py:1208-1220`
- Create: `wafer_space/projects/migrations/00XX_add_parent_check.py`
- Test: `wafer_space/projects/tests/test_models.py`

**Step 1: Write the failing test**

Add to `wafer_space/projects/tests/test_models.py`:

```python
class TestManufacturabilityCheckParentCheck:
    """Tests for ManufacturabilityCheck.parent_check field."""

    def test_parent_check_null_by_default(self):
        """New checks have null parent_check."""
        check = ManufacturabilityCheckFactory()
        assert check.parent_check is None

    def test_parent_check_can_reference_another_check(self):
        """parent_check can reference another ManufacturabilityCheck."""
        original = ManufacturabilityCheckFactory()
        retry = ManufacturabilityCheckFactory(
            project=original.project,
            project_file=original.project_file,
            parent_check=original,
            trigger_reason=ManufacturabilityCheck.TriggerReason.RETRY,
        )
        assert retry.parent_check == original
        assert retry in original.retry_checks.all()

    def test_retry_checks_reverse_relation(self):
        """Original check can access its retries via retry_checks."""
        original = ManufacturabilityCheckFactory()
        retry1 = ManufacturabilityCheckFactory(
            project=original.project,
            project_file=original.project_file,
            parent_check=original,
        )
        retry2 = ManufacturabilityCheckFactory(
            project=original.project,
            project_file=original.project_file,
            parent_check=original,
        )
        assert original.retry_checks.count() == 2
        assert retry1 in original.retry_checks.all()
        assert retry2 in original.retry_checks.all()

    def test_cascade_delete_removes_retries(self):
        """Deleting original check cascades to retries."""
        original = ManufacturabilityCheckFactory()
        retry = ManufacturabilityCheckFactory(
            project=original.project,
            project_file=original.project_file,
            parent_check=original,
        )
        retry_id = retry.id
        original.delete()
        assert not ManufacturabilityCheck.objects.filter(id=retry_id).exists()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckParentCheck -v`
Expected: FAIL with "parent_check not defined"

**Step 3: Implement parent_check field**

In `wafer_space/projects/models.py`, add after `trigger_reason` field:

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

**Step 4: Create and apply migration**

Run: `uv run python manage.py makemigrations projects --name add_parent_check && uv run python manage.py migrate`

**Step 5: Run test to verify it passes**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckParentCheck -v`
Expected: PASS

**Step 6: Commit**

```bash
git add wafer_space/projects/models.py wafer_space/projects/migrations/ wafer_space/projects/tests/test_models.py
git commit -m "feat: add parent_check self-referential FK for retry chaining"
```

---

## Task 3: Convert project_file from OneToOneField to ForeignKey

**Files:**
- Modify: `wafer_space/projects/models.py:1213-1217`
- Create: `wafer_space/projects/migrations/00XX_convert_project_file_to_fk.py`
- Test: `wafer_space/projects/tests/test_models.py`

**Step 1: Write the failing test**

Add to `wafer_space/projects/tests/test_models.py`:

```python
class TestManufacturabilityCheckMultiplePerFile:
    """Tests for multiple ManufacturabilityChecks per ProjectFile."""

    def test_multiple_checks_allowed_per_file(self):
        """Can create multiple checks for the same ProjectFile."""
        project_file = ProjectFileFactory()
        check1 = ManufacturabilityCheckFactory(
            project=project_file.project,
            project_file=project_file,
        )
        check2 = ManufacturabilityCheckFactory(
            project=project_file.project,
            project_file=project_file,
        )
        assert check1.project_file == project_file
        assert check2.project_file == project_file
        assert project_file.manufacturability_checks.count() == 2

    def test_manufacturability_checks_ordered_by_created_at_desc(self):
        """Checks are ordered by -created_at (newest first)."""
        project_file = ProjectFileFactory()
        check1 = ManufacturabilityCheckFactory(
            project=project_file.project,
            project_file=project_file,
        )
        check2 = ManufacturabilityCheckFactory(
            project=project_file.project,
            project_file=project_file,
        )
        checks = list(project_file.manufacturability_checks.all())
        # check2 created after check1, so check2 should be first
        assert checks[0] == check2
        assert checks[1] == check1
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckMultiplePerFile -v`
Expected: FAIL with IntegrityError (OneToOne constraint violation)

**Step 3: Modify field from OneToOneField to ForeignKey**

In `wafer_space/projects/models.py`, change (around line 1213):

```python
    # BEFORE:
    project_file = models.OneToOneField(
        "ProjectFile",
        on_delete=models.CASCADE,
        related_name="manufacturability_check",
    )

    # AFTER:
    project_file = models.ForeignKey(
        "ProjectFile",
        on_delete=models.CASCADE,
        related_name="manufacturability_checks",
    )
```

**Step 4: Create and apply migration**

Run: `uv run python manage.py makemigrations projects --name convert_project_file_to_fk && uv run python manage.py migrate`

**Step 5: Run test to verify it passes**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestManufacturabilityCheckMultiplePerFile -v`
Expected: PASS

**Step 6: Commit**

```bash
git add wafer_space/projects/models.py wafer_space/projects/migrations/
git commit -m "feat: convert ManufacturabilityCheck.project_file to ForeignKey

BREAKING: Changes from OneToOneField to ForeignKey.
All code using project_file.manufacturability_check must be updated."
```

---

## Task 4: Add latest_manufacturability_check Property to ProjectFile

**Files:**
- Modify: `wafer_space/projects/models.py:693-728`
- Test: `wafer_space/projects/tests/test_models.py`

**Step 1: Write the failing test**

Add to `wafer_space/projects/tests/test_models.py`:

```python
class TestProjectFileLatestManufacturabilityCheck:
    """Tests for ProjectFile.latest_manufacturability_check property."""

    def test_latest_manufacturability_check_returns_none_when_no_checks(self):
        """Returns None when no checks exist."""
        project_file = ProjectFileFactory()
        assert project_file.latest_manufacturability_check is None

    def test_latest_manufacturability_check_returns_newest(self):
        """Returns the most recently created check."""
        project_file = ProjectFileFactory()
        check1 = ManufacturabilityCheckFactory(
            project=project_file.project,
            project_file=project_file,
        )
        check2 = ManufacturabilityCheckFactory(
            project=project_file.project,
            project_file=project_file,
        )
        # check2 is newer
        assert project_file.latest_manufacturability_check == check2

    def test_latest_manufacturability_check_with_single_check(self):
        """Returns the only check when just one exists."""
        project_file = ProjectFileFactory()
        check = ManufacturabilityCheckFactory(
            project=project_file.project,
            project_file=project_file,
        )
        assert project_file.latest_manufacturability_check == check
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestProjectFileLatestManufacturabilityCheck -v`
Expected: FAIL with "latest_manufacturability_check not defined"

**Step 3: Implement the property**

In `wafer_space/projects/models.py`, add to `ProjectFile` class (after line 793):

```python
    @property
    def latest_manufacturability_check(self) -> "ManufacturabilityCheck | None":
        """Get the most recent manufacturability check.

        Returns None if no checks exist yet.
        Ordered by -created_at (newest first).
        """
        return self.manufacturability_checks.first()
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestProjectFileLatestManufacturabilityCheck -v`
Expected: PASS

**Step 5: Commit**

```bash
git add wafer_space/projects/models.py wafer_space/projects/tests/test_models.py
git commit -m "feat: add latest_manufacturability_check property to ProjectFile"
```

---

## Task 5: Update All Code References to Use latest_manufacturability_check

**Files:**
- Modify: `wafer_space/projects/views.py:176,338,438,493,794`
- Modify: `wafer_space/projects/services.py:352`
- Modify: `wafer_space/projects/tasks_checks.py:618-622`
- Modify: `wafer_space/templates/projects/_file_display.html:61`
- Modify: `wafer_space/templates/projects/_file_badges.html:10`
- Modify: `wafer_space/templates/projects/admin_summary.html:178-183`

**Step 1: Run existing tests to establish baseline**

Run: `uv run pytest wafer_space/projects/tests/ -v --tb=short 2>&1 | head -100`

Note any failures - these indicate code that now breaks.

**Step 2: Update views.py**

Search and replace in `wafer_space/projects/views.py`:

```python
# Line 176: Change:
check = active_file.manufacturability_check
# To:
check = active_file.latest_manufacturability_check

# Line 338: Change:
check = active_file.manufacturability_check
# To:
check = active_file.latest_manufacturability_check

# Line 438: Change:
check = active_file.manufacturability_check
# To:
check = active_file.latest_manufacturability_check

# Line 493: Change:
check = active_file.manufacturability_check
# To:
check = active_file.latest_manufacturability_check

# Line 794: Change:
active_file.manufacturability_check
# To:
active_file.latest_manufacturability_check
```

Also remove any `try/except ManufacturabilityCheck.DoesNotExist` blocks - they're not needed since the property returns None.

**Step 3: Update services.py**

In `wafer_space/projects/services.py` line 352:

```python
# Change:
check = active_file.manufacturability_check
# To:
check = active_file.latest_manufacturability_check
```

**Step 4: Update tasks_checks.py**

In `wafer_space/projects/tasks_checks.py` lines 618-622, change the query:

```python
# BEFORE:
files_needing_checks = ProjectFile.objects.filter(
    is_active=True,
    hash_verified=True,
).exclude(
    manufacturability_check__isnull=False,
)

# AFTER:
files_needing_checks = ProjectFile.objects.filter(
    is_active=True,
    hash_verified=True,
).exclude(
    manufacturability_checks__isnull=False,
)
```

**Step 5: Update templates**

In `wafer_space/templates/projects/_file_display.html` line 61:

```html
<!-- BEFORE: -->
{% with check=file.manufacturability_check %}

<!-- AFTER: -->
{% with check=file.latest_manufacturability_check %}
```

In `wafer_space/templates/projects/_file_badges.html` line 10:

```html
<!-- BEFORE: -->
{% with check=file.manufacturability_check %}

<!-- AFTER: -->
{% with check=file.latest_manufacturability_check %}
```

In `wafer_space/templates/projects/admin_summary.html` lines 178-183:

```html
<!-- BEFORE: -->
{% if active_file and active_file.manufacturability_check %}
  <td>{{ active_file.manufacturability_check.get_status_display }}</td>
  ...
  {% if active_file.manufacturability_check.is_manufacturable is True %}

<!-- AFTER: -->
{% if active_file and active_file.latest_manufacturability_check %}
  <td>{{ active_file.latest_manufacturability_check.get_status_display }}</td>
  ...
  {% if active_file.latest_manufacturability_check.is_manufacturable is True %}
```

**Step 6: Run tests to verify**

Run: `uv run pytest wafer_space/projects/tests/ -v --tb=short`
Expected: All tests pass

**Step 7: Commit**

```bash
git add wafer_space/projects/views.py wafer_space/projects/services.py wafer_space/projects/tasks_checks.py wafer_space/templates/
git commit -m "refactor: update all code to use latest_manufacturability_check

NO BACKWARDS COMPATIBILITY - all callsites updated directly."
```

---

## Task 6: Add create_retry_check Service Function

**Files:**
- Modify: `wafer_space/projects/services.py`
- Test: `wafer_space/projects/tests/test_services.py` (create if needed)

**Step 1: Write the failing test**

Create or add to `wafer_space/projects/tests/test_services.py`:

```python
"""Tests for projects services."""

from __future__ import annotations

import pytest

from wafer_space.projects.exceptions import MaxRetriesExceededError
from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.services import create_retry_check
from wafer_space.projects.tests.factories import ManufacturabilityCheckFactory


class TestCreateRetryCheck:
    """Tests for create_retry_check service function."""

    def test_creates_new_check_in_pending_state(self):
        """Creates a new check in PENDING status."""
        failed_check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.ERROR,
        )
        retry = create_retry_check(failed_check)
        assert retry.status == ManufacturabilityCheck.Status.PENDING
        assert retry.id != failed_check.id

    def test_sets_trigger_reason_to_retry(self):
        """New check has trigger_reason=RETRY."""
        failed_check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.ERROR,
        )
        retry = create_retry_check(failed_check)
        assert retry.trigger_reason == ManufacturabilityCheck.TriggerReason.RETRY

    def test_sets_parent_check_to_original(self):
        """parent_check points to original (not the failed check if it's a retry)."""
        original = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.ERROR,
        )
        retry1 = create_retry_check(original)
        retry1.status = ManufacturabilityCheck.Status.ERROR
        retry1.save()

        retry2 = create_retry_check(retry1)
        # retry2's parent should be original, not retry1
        assert retry2.parent_check == original

    def test_preserves_project_and_project_file(self):
        """New check has same project and project_file."""
        failed_check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.ERROR,
        )
        retry = create_retry_check(failed_check)
        assert retry.project == failed_check.project
        assert retry.project_file == failed_check.project_file

    def test_raises_value_error_if_not_in_error_state(self):
        """Cannot retry a check that's not in ERROR status."""
        pending_check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING,
        )
        with pytest.raises(ValueError, match="Can only retry ERROR checks"):
            create_retry_check(pending_check)

    def test_raises_max_retries_exceeded_error(self):
        """Cannot retry beyond max_retries limit."""
        original = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.ERROR,
        )
        # Create 3 retries (max)
        for _ in range(3):
            retry = ManufacturabilityCheckFactory(
                project=original.project,
                project_file=original.project_file,
                parent_check=original,
                status=ManufacturabilityCheck.Status.ERROR,
            )

        with pytest.raises(MaxRetriesExceededError):
            create_retry_check(retry)

    def test_original_check_unchanged(self):
        """Original check is not modified."""
        failed_check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.ERROR,
            error_message="Docker timeout",
            processing_logs="Some logs",
        )
        original_status = failed_check.status
        original_logs = failed_check.processing_logs

        create_retry_check(failed_check)

        failed_check.refresh_from_db()
        assert failed_check.status == original_status
        assert failed_check.processing_logs == original_logs
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/projects/tests/test_services.py::TestCreateRetryCheck -v`
Expected: FAIL with "cannot import name 'create_retry_check'"

**Step 3: Implement create_retry_check**

In `wafer_space/projects/services.py`, add:

```python
from wafer_space.projects.exceptions import MaxRetriesExceededError


# Near the top, with other constants
MAX_MANUFACTURABILITY_CHECK_RETRIES = 3


def create_retry_check(
    failed_check: "ManufacturabilityCheck",
) -> "ManufacturabilityCheck":
    """Create a new check as a retry of a failed one.

    Args:
        failed_check: The check that failed (must be in ERROR status)

    Returns:
        New ManufacturabilityCheck in PENDING status

    Raises:
        ValueError: If failed_check is not in ERROR status
        MaxRetriesExceededError: If retry limit reached
    """
    from wafer_space.projects.models import ManufacturabilityCheck

    if failed_check.status != ManufacturabilityCheck.Status.ERROR:
        msg = f"Can only retry ERROR checks, not {failed_check.status}"
        raise ValueError(msg)

    # Find original check (handles both first retry and subsequent)
    original = failed_check.parent_check or failed_check

    # Check retry limit
    retry_count = original.retry_checks.count()
    if retry_count >= MAX_MANUFACTURABILITY_CHECK_RETRIES:
        raise MaxRetriesExceededError(
            retry_count=retry_count,
            max_retries=MAX_MANUFACTURABILITY_CHECK_RETRIES,
        )

    return ManufacturabilityCheck.objects.create(
        project=original.project,
        project_file=original.project_file,
        trigger_reason=ManufacturabilityCheck.TriggerReason.RETRY,
        parent_check=original,
    )
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest wafer_space/projects/tests/test_services.py::TestCreateRetryCheck -v`
Expected: PASS

**Step 5: Commit**

```bash
git add wafer_space/projects/services.py wafer_space/projects/tests/test_services.py
git commit -m "feat: add create_retry_check service function for retry handling"
```

---

## Task 7: Update tasks_checks.py to Use create_retry_check

**Files:**
- Modify: `wafer_space/projects/tasks_checks.py:583-603`
- Test: `wafer_space/projects/tests/test_tasks.py`

**Step 1: Update checks_retry task**

In `wafer_space/projects/tasks_checks.py`, replace the retry logic (lines 583-603):

```python
# BEFORE:
for check in error_checks:
    if check.can_retry():
        logger.info(
            "Retrying check %s (project: %s, attempt %d/%d)",
            check.id,
            check.project.name,
            check.retry_count + 1,
            check.max_retries,
        )
        check.reset_for_retry(reason="Automatic retry after error")
        retried += 1
    else:
        logger.info(
            "Check %s exhausted retries (%d/%d)",
            check.id,
            check.retry_count,
            check.max_retries,
        )
        exhausted += 1

# AFTER:
from wafer_space.projects.exceptions import MaxRetriesExceededError
from wafer_space.projects.services import create_retry_check

for check in error_checks:
    try:
        original = check.parent_check or check
        retry_count = original.retry_checks.count()
        new_check = create_retry_check(check)
        logger.info(
            "Created retry check %s for %s (project: %s, attempt %d)",
            new_check.id,
            check.id,
            check.project.name,
            retry_count + 1,
        )
        retried += 1
    except MaxRetriesExceededError:
        original = check.parent_check or check
        retry_count = original.retry_checks.count()
        logger.info(
            "Check %s exhausted retries (%d)",
            check.id,
            retry_count,
        )
        exhausted += 1
```

**Step 2: Run existing tests**

Run: `uv run pytest wafer_space/projects/tests/test_tasks.py -v -k retry`
Expected: May fail - update tests as needed

**Step 3: Update tests for new behavior**

Find and update tests in `wafer_space/projects/tests/test_tasks.py` that test retry behavior. They should now expect:
- A new check is created (not the old one modified)
- Old check stays in ERROR state
- New check is in PENDING state with parent_check set

**Step 4: Run tests to verify**

Run: `uv run pytest wafer_space/projects/tests/test_tasks.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add wafer_space/projects/tasks_checks.py wafer_space/projects/tests/test_tasks.py
git commit -m "refactor: update checks_retry to use create_retry_check service"
```

---

## Task 8: Add cancel_superseded_checks to Cleanup Task

**Files:**
- Modify: `wafer_space/projects/tasks_checks.py`
- Test: `wafer_space/projects/tests/test_tasks.py`

**Step 1: Write the failing test**

Add to `wafer_space/projects/tests/test_tasks.py`:

```python
class TestCancelSupersededChecks:
    """Tests for cancel_superseded_checks functionality."""

    def test_cancels_older_in_progress_check_when_newer_exists(self):
        """Older in-progress check is cancelled when newer check exists."""
        project_file = ProjectFileFactory()
        old_check = ManufacturabilityCheckFactory(
            project=project_file.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
        )
        new_check = ManufacturabilityCheckFactory(
            project=project_file.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        from wafer_space.projects.tasks_checks import checks_cleanup
        checks_cleanup()

        old_check.refresh_from_db()
        assert old_check.status == ManufacturabilityCheck.Status.CANCELLING

    def test_does_not_cancel_if_no_newer_check(self):
        """In-progress check is not cancelled if no newer check exists."""
        project_file = ProjectFileFactory()
        check = ManufacturabilityCheckFactory(
            project=project_file.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
        )

        from wafer_space.projects.tasks_checks import checks_cleanup
        checks_cleanup()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.RUNNING

    def test_does_not_cancel_finished_checks(self):
        """Finished checks are not cancelled even if newer exists."""
        project_file = ProjectFileFactory()
        old_check = ManufacturabilityCheckFactory(
            project=project_file.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
        )
        ManufacturabilityCheckFactory(
            project=project_file.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        from wafer_space.projects.tasks_checks import checks_cleanup
        checks_cleanup()

        old_check.refresh_from_db()
        assert old_check.status == ManufacturabilityCheck.Status.FINISHED
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/projects/tests/test_tasks.py::TestCancelSupersededChecks -v`
Expected: FAIL (functionality not implemented)

**Step 3: Implement cancel_superseded_checks**

In `wafer_space/projects/tasks_checks.py`, add helper function and integrate into cleanup:

```python
from django.db.models import Exists, OuterRef


def _cancel_superseded_checks() -> int:
    """Cancel in-progress checks that have been superseded by newer checks.

    Returns:
        Number of checks marked for cancellation.
    """
    logger = logging.getLogger(__name__)

    # Subquery: does a newer check exist for the same file?
    newer_exists = ManufacturabilityCheck.objects.filter(
        project_file=OuterRef("project_file"),
        created_at__gt=OuterRef("created_at"),
    )

    # Find all superseded in-progress checks
    superseded = ManufacturabilityCheck.objects.filter(
        status__in=ManufacturabilityCheck.Status.in_progress(),
    ).filter(Exists(newer_exists))

    cancelled = 0
    for check in superseded:
        try:
            check.mark_cancelling(reason="Superseded by newer check")
            logger.info(
                "Marked check %s as cancelling (superseded)",
                check.id,
            )
            cancelled += 1
        except Exception:
            logger.exception("Failed to cancel superseded check %s", check.id)

    return cancelled
```

Then call from `checks_cleanup()`:

```python
def checks_cleanup() -> dict:
    # ... existing cleanup logic ...

    # Cancel superseded checks
    superseded_cancelled = _cancel_superseded_checks()

    return {
        # ... existing return values ...
        "superseded_cancelled": superseded_cancelled,
    }
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest wafer_space/projects/tests/test_tasks.py::TestCancelSupersededChecks -v`
Expected: PASS

**Step 5: Commit**

```bash
git add wafer_space/projects/tasks_checks.py wafer_space/projects/tests/test_tasks.py
git commit -m "feat: add cancel_superseded_checks to cleanup task"
```

---

## Task 9: Add Derived Properties to Project

**Files:**
- Modify: `wafer_space/projects/models.py:121-123,152-160`
- Test: `wafer_space/projects/tests/test_models.py`

**Step 1: Write the failing test**

Add to `wafer_space/projects/tests/test_models.py`:

```python
class TestProjectDerivedManufacturabilityProperties:
    """Tests for Project's derived manufacturability properties."""

    def test_is_manufacturable_returns_none_without_submitted_file(self):
        """Returns None when no submitted_file."""
        project = ProjectFactory(submitted_file=None)
        assert project.is_manufacturable is None

    def test_is_manufacturable_returns_none_without_finished_check(self):
        """Returns None when check is not FINISHED."""
        project_file = ProjectFileFactory()
        project = project_file.project
        project.submitted_file = project_file
        project.save()
        ManufacturabilityCheckFactory(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
        )
        assert project.is_manufacturable is None

    def test_is_manufacturable_returns_check_result(self):
        """Returns is_manufacturable from latest finished check."""
        project_file = ProjectFileFactory()
        project = project_file.project
        project.submitted_file = project_file
        project.save()
        check = ManufacturabilityCheckFactory(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )
        assert project.is_manufacturable is True

    def test_manufacturability_errors_empty_without_submitted_file(self):
        """Returns empty list when no submitted_file."""
        project = ProjectFactory(submitted_file=None)
        assert project.manufacturability_errors == []

    def test_manufacturability_errors_from_latest_check(self):
        """Returns errors from latest finished check."""
        project_file = ProjectFileFactory()
        project = project_file.project
        project.submitted_file = project_file
        project.save()
        errors = ["Error 1", "Error 2"]
        ManufacturabilityCheckFactory(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            errors=errors,
        )
        assert project.manufacturability_errors == errors

    def test_check_completed_at_from_latest_check(self):
        """Returns analysis_completed_at from latest finished check."""
        from django.utils import timezone

        project_file = ProjectFileFactory()
        project = project_file.project
        project.submitted_file = project_file
        project.save()
        completed_time = timezone.now()
        ManufacturabilityCheckFactory(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            analysis_completed_at=completed_time,
        )
        assert project.check_completed_at == completed_time
```

**Step 2: Run test to verify behavior (may pass if fields still exist)**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestProjectDerivedManufacturabilityProperties -v`

**Step 3: Add derived properties to Project**

In `wafer_space/projects/models.py`, add to `Project` class (replacing or alongside existing fields for now):

```python
    @property
    def is_manufacturable(self) -> bool | None:
        """Derived from latest completed check on submitted file."""
        if not self.submitted_file:
            return None
        check = self.submitted_file.latest_manufacturability_check
        if not check or check.status != "finished":
            return None
        return check.is_manufacturable

    @property
    def manufacturability_errors(self) -> list:
        """Derived from latest completed check."""
        if not self.submitted_file:
            return []
        check = self.submitted_file.latest_manufacturability_check
        if not check or check.status != "finished":
            return []
        return check.errors

    @property
    def check_completed_at(self):
        """Derived from latest completed check."""
        if not self.submitted_file:
            return None
        check = self.submitted_file.latest_manufacturability_check
        if not check or check.status != "finished":
            return None
        return check.analysis_completed_at
```

Note: At this point we have both the fields AND the properties. We'll remove the fields in a later task after updating all the code that writes to them.

**Step 4: Run test to verify it passes**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestProjectDerivedManufacturabilityProperties -v`
Expected: PASS

**Step 5: Commit**

```bash
git add wafer_space/projects/models.py wafer_space/projects/tests/test_models.py
git commit -m "feat: add derived manufacturability properties to Project

Properties coexist with fields temporarily. Fields will be removed after
code that writes to them is updated."
```

---

## Task 10: Update mark_finished to Stop Writing to Project Fields

**Files:**
- Modify: `wafer_space/projects/models.py:1593-1601`
- Modify: `wafer_space/projects/tests/test_models.py`

**Step 1: Update mark_finished**

In `wafer_space/projects/models.py`, modify `mark_finished()` to remove the Project updates:

```python
    def mark_finished(
        self,
        *,
        is_manufacturable: bool,
        errors: list[str],
        warnings: list[str],
        tool_versions: dict[str, str],
    ) -> None:
        """Transition ANALYZING -> FINISHED with analysis results.

        Args:
            is_manufacturable: Whether design is manufacturable.
            errors: List of error messages.
            warnings: List of warning messages.
            tool_versions: Tool versions used in analysis.

        Raises:
            InvalidStateTransitionError: If not in ANALYZING status.
        """
        if not self.can_transition_to(self.Status.FINISHED):
            raise InvalidStateTransitionError(
                from_status=self.status,
                to_status=self.Status.FINISHED,
            )

        self.status = self.Status.FINISHED
        self.is_manufacturable = is_manufacturable
        self.errors = errors
        self.warnings = warnings
        self.tool_versions = tool_versions
        self.analysis_completed_at = timezone.now()
        self.save(
            update_fields=[
                "status",
                "is_manufacturable",
                "errors",
                "warnings",
                "tool_versions",
                "analysis_completed_at",
            ]
        )

        # Update project status based on result
        if is_manufacturable:
            self.project.status = Project.Status.MANUFACTURABLE
        else:
            self.project.status = Project.Status.NOT_MANUFACTURABLE
        self.project.save(update_fields=["status"])

        # NOTE: Project.is_manufacturable, manufacturability_errors, check_completed_at
        # are now derived properties - no need to copy values
```

**Step 2: Find and update tests that expect field writes**

Search for tests that set or check `project.is_manufacturable = ...`:

```bash
grep -n "project.is_manufacturable\s*=" wafer_space/projects/tests/
```

Update these tests to use the derived property approach (setting up the check correctly, not the project field).

**Step 3: Run tests to verify**

Run: `uv run pytest wafer_space/projects/tests/test_models.py -v`
Expected: PASS (after updating tests)

**Step 4: Commit**

```bash
git add wafer_space/projects/models.py wafer_space/projects/tests/
git commit -m "refactor: stop copying manufacturability results to Project in mark_finished

Project.is_manufacturable, manufacturability_errors, check_completed_at
are now derived properties that read from the latest check."
```

---

## Task 11: Remove Old Fields from ManufacturabilityCheck

**Files:**
- Modify: `wafer_space/projects/models.py:1353-1354,1421-1423,1698-1736`
- Create: `wafer_space/projects/migrations/00XX_remove_retry_fields.py`
- Modify: `wafer_space/projects/tests/test_models.py`

**Step 1: Delete tests for reset_for_retry and can_retry**

Remove the entire `TestResetForRetry` class from `wafer_space/projects/tests/test_models.py` (lines ~2170-2345).

Also remove any tests for `can_retry()` method.

**Step 2: Delete reset_for_retry method**

Remove the entire `reset_for_retry()` method from `ManufacturabilityCheck` (lines 1698-1736).

**Step 3: Delete can_retry method**

Remove `can_retry()` method (lines 1421-1423).

**Step 4: Remove retry_count and max_retries fields**

Remove these fields from `ManufacturabilityCheck`:

```python
# DELETE these lines:
retry_count = models.PositiveIntegerField(default=0)
max_retries = models.PositiveIntegerField(default=3)
```

**Step 5: Create migration**

Run: `uv run python manage.py makemigrations projects --name remove_retry_fields`

**Step 6: Apply migration**

Run: `uv run python manage.py migrate`

**Step 7: Run tests to verify**

Run: `uv run pytest wafer_space/projects/tests/test_models.py -v`
Expected: PASS

**Step 8: Commit**

```bash
git add wafer_space/projects/models.py wafer_space/projects/migrations/ wafer_space/projects/tests/test_models.py
git commit -m "refactor: remove retry_count, max_retries, reset_for_retry, can_retry

These are replaced by the retry chain (parent_check relationship).
DELETED: All tests for removed functionality."
```

---

## Task 12: Remove Old Fields from Project

**Files:**
- Modify: `wafer_space/projects/models.py:121-123`
- Create: `wafer_space/projects/migrations/00XX_remove_project_manufacturability_fields.py`
- Modify: `wafer_space/projects/tests/test_models.py`
- Modify: `wafer_space/projects/tests/test_views.py`
- Modify: `wafer_space/projects/tests/test_tasks.py`

**Step 1: Find and update all tests that write to these fields**

Search:
```bash
grep -rn "\.is_manufacturable\s*=" wafer_space/projects/tests/
grep -rn "\.manufacturability_errors\s*=" wafer_space/projects/tests/
grep -rn "\.check_completed_at\s*=" wafer_space/projects/tests/
```

Update each test to:
- Create a ManufacturabilityCheck in FINISHED state with appropriate values
- Use the derived property for reading

**Step 2: Remove the database fields**

In `wafer_space/projects/models.py`, remove from `Project`:

```python
# DELETE these lines:
is_manufacturable = models.BooleanField(null=True, blank=True)
manufacturability_errors = models.JSONField(default=list, blank=True)
check_completed_at = models.DateTimeField(null=True, blank=True)
```

**Step 3: Create migration**

Run: `uv run python manage.py makemigrations projects --name remove_project_manufacturability_fields`

**Step 4: Apply migration**

Run: `uv run python manage.py migrate`

**Step 5: Run all tests**

Run: `uv run pytest wafer_space/projects/tests/ -v`
Expected: PASS

**Step 6: Commit**

```bash
git add wafer_space/projects/models.py wafer_space/projects/migrations/ wafer_space/projects/tests/
git commit -m "refactor: remove is_manufacturable, manufacturability_errors, check_completed_at fields from Project

These are now derived properties that read from the latest check.
UPDATED: All tests to set up ManufacturabilityCheck instead of Project fields."
```

---

## Task 13: Update Admin for New Fields

**Files:**
- Modify: `wafer_space/projects/admin.py:86-116`
- Test: Manual verification

**Step 1: Update ManufacturabilityCheckAdmin**

In `wafer_space/projects/admin.py`:

```python
class ManufacturabilityCheckAdmin(StaffReadOnlyAdminMixin, admin.ModelAdmin):
    """Admin for manufacturability checks."""

    list_display = [
        "project",
        "project_file",
        "status",
        "trigger_reason",  # NEW
        "is_manufacturable",
        "parent_check",  # NEW
        "container_started_at",
        "analysis_completed_at",
        "docker_image_digest",
        "rerun_requested_by",
    ]

    list_filter = [
        "status",
        "trigger_reason",  # NEW
        "is_manufacturable",
        "container_started_at",
        "analysis_completed_at",
    ]

    search_fields = [
        "project__name",
        "project__user__username",
        "docker_image",
        "parent_check__id",  # NEW
    ]

    readonly_fields = [
        "project",
        "project_file",
        "trigger_reason",  # NEW
        "parent_check",  # NEW
        "created_at",
        "dispatching_started_at",
        "starting_started_at",
        # ... rest of existing readonly_fields
    ]
```

**Step 2: Run linting**

Run: `make lint-fix && make lint`

**Step 3: Commit**

```bash
git add wafer_space/projects/admin.py
git commit -m "feat: update ManufacturabilityCheckAdmin for trigger_reason and parent_check"
```

---

## Task 14: Update Factory for New Fields

**Files:**
- Modify: `wafer_space/projects/tests/factories.py:42-51`

**Step 1: Update ManufacturabilityCheckFactory**

In `wafer_space/projects/tests/factories.py`:

```python
class ManufacturabilityCheckFactory(DjangoModelFactory[ManufacturabilityCheck]):
    """Factory for creating test ManufacturabilityCheck instances."""

    project = SubFactory(ProjectFactory)
    project_file = SubFactory(ProjectFileFactory, project=project)
    status = ManufacturabilityCheck.Status.PENDING
    trigger_reason = ManufacturabilityCheck.TriggerReason.INITIAL  # NEW
    parent_check = None  # NEW - explicit default
    docker_server_id = ""

    class Meta:
        model = ManufacturabilityCheck
```

**Step 2: Run tests**

Run: `uv run pytest wafer_space/projects/tests/ -v`
Expected: PASS

**Step 3: Commit**

```bash
git add wafer_space/projects/tests/factories.py
git commit -m "feat: update ManufacturabilityCheckFactory with trigger_reason and parent_check"
```

---

## Task 15: Final Cleanup - Search for Remaining References

**Files:**
- Various - based on search results

**Step 1: Search for old patterns**

Run these searches and fix any remaining references:

```bash
# Old singular accessor
grep -rn "\.manufacturability_check\b" wafer_space/ --include="*.py" | grep -v "manufacturability_checks"

# Old field writes
grep -rn "project\.is_manufacturable\s*=" wafer_space/
grep -rn "project\.manufacturability_errors\s*=" wafer_space/
grep -rn "project\.check_completed_at\s*=" wafer_space/

# Removed methods/fields
grep -rn "reset_for_retry" wafer_space/
grep -rn "retry_count" wafer_space/projects/models.py
grep -rn "max_retries" wafer_space/projects/models.py
grep -rn "can_retry" wafer_space/projects/models.py
```

**Step 2: Fix any remaining references**

Update each file found to use the new patterns.

**Step 3: Run full test suite**

Run: `make check-all`
Expected: All checks pass

**Step 4: Commit any remaining fixes**

```bash
git add -A
git commit -m "chore: final cleanup of old manufacturability check references"
```

---

## Task 16: Update Documentation

**Files:**
- Modify: `wafer_space/projects/docs/project_submission_system.md` (if exists)
- Modify: Any other relevant docs

**Step 1: Search for documentation files**

```bash
find . -name "*.md" -path "*/docs/*" | xargs grep -l "manufacturability" 2>/dev/null
```

**Step 2: Update documentation**

Update any documentation that references:
- `retry_count` / `max_retries`
- `reset_for_retry()`
- Old field relationships

**Step 3: Commit**

```bash
git add docs/
git commit -m "docs: update documentation for multi-check refactor"
```

---

## Summary Checklist

After completing all tasks, verify:

- [ ] `ManufacturabilityCheck` has `trigger_reason` field
- [ ] `ManufacturabilityCheck` has `parent_check` self-FK
- [ ] `ManufacturabilityCheck.project_file` is ForeignKey (not OneToOne)
- [ ] `ProjectFile.latest_manufacturability_check` property exists
- [ ] `Project.is_manufacturable` is a property (not field)
- [ ] `Project.manufacturability_errors` is a property (not field)
- [ ] `Project.check_completed_at` is a property (not field)
- [ ] `create_retry_check()` service function exists
- [ ] `reset_for_retry()` method is DELETED
- [ ] `retry_count` field is DELETED
- [ ] `max_retries` field is DELETED
- [ ] All templates use `latest_manufacturability_check`
- [ ] All tests pass: `make check-all`
- [ ] No backwards compatibility shims exist
