# Scope Automatic DRC Re-runs by Shuttle Status — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the automatic DRC re-run task from re-checking designs whose shuttle is in `production`/`completed`/`cancelled`, while leaving no-shuttle drafts, all pre-fab shuttle states, and the manual "Recheck with Latest" button fully unaffected.

**Architecture:** Add one classmethod `Shuttle.Status.drc_recheck_excluded()` as the single source of truth for the excluded states, then add a single `.exclude(...)` clause to the candidate queryset inside the automatic `checks_drc_update_requeue` task. The shared model method `create_check_drc_update()` is deliberately untouched so the manual path stays unrestricted.

**Tech Stack:** Django 5.2, PostgreSQL, Celery, pytest-django, factory-boy, ruff, mypy. Package manager: `uv`. All commands run from the worktree root `.worktrees/issue/270-drc-requeue-shuttle-scope/`.

**Spec:** `docs/superpowers/specs/2026-06-25-drc-requeue-shuttle-scope-design.md`

**Issue:** <https://github.com/wafer-space/platform.wafer.space/issues/270>

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `wafer_space/shuttles/models.py` | Modify (~after line 71) | Add `Shuttle.Status.drc_recheck_excluded()` classmethod — single source of truth for excluded states. |
| `wafer_space/shuttles/tests/test_models.py` | Create | Direct contract test for the new classmethod. |
| `wafer_space/projects/tasks_checks.py` | Modify (import block; queryset at 727-735) | Import `Shuttle`; add `.exclude(...)` to the automatic candidate queryset. |
| `wafer_space/projects/tests/test_tasks.py` | Modify (add import; new test in `TestChecksDrcUpdateRequeue` ~line 2183) | Parametrized scope test across all shuttle states + no-shuttle draft. |
| `wafer_space/projects/tests/test_models.py` | Modify (add import; new test in `TestCreateCheckDrcUpdate` ~line 3091) | Regression guard: manual path works in every shuttle state. |

**No-cycle note (verified):** `tasks_checks.py` importing `from wafer_space.shuttles.models import Shuttle` is safe. `shuttles.models` imports `projects.models`, but `projects.models` references the shuttle FK by **string** (`"shuttles.Shuttle"`, `models.py:197`) and does not import `shuttles`, so the dependency is one-directional. This is a legitimate top-level import, not a circular-import workaround.

**Shared digest constants** (reuse the exact strings already used throughout these test files to avoid digest-length surprises):
- Outdated: `sha256:old123456789012345678901234567890123456789012345678901234567`
- Latest:  `sha256:new456789012345678901234567890123456789012345678901234567890`

---

## Task 1: Add `Shuttle.Status.drc_recheck_excluded()` classmethod

**Files:**
- Create: `wafer_space/shuttles/tests/test_models.py`
- Modify: `wafer_space/shuttles/models.py` (insert after line 71, immediately below the `CANCELLED` choice, inside the `Status` class)

- [ ] **Step 1: Write the failing test**

Create `wafer_space/shuttles/tests/test_models.py`:

```python
"""Tests for shuttles app models."""

from __future__ import annotations

import pytest

from wafer_space.shuttles.models import Shuttle

pytestmark = pytest.mark.django_db


class TestShuttleStatusDrcRecheckExcluded:
    """Tests for Shuttle.Status.drc_recheck_excluded()."""

    def test_returns_terminal_and_in_fab_states(self):
        """Excluded set is exactly production, completed, cancelled."""
        assert Shuttle.Status.drc_recheck_excluded() == [
            Shuttle.Status.IN_PRODUCTION,
            Shuttle.Status.COMPLETED,
            Shuttle.Status.CANCELLED,
        ]

    def test_pre_fab_states_are_not_excluded(self):
        """Pre-fab states remain eligible for automatic re-runs."""
        excluded = set(Shuttle.Status.drc_recheck_excluded())
        for status in (
            Shuttle.Status.PLANNING,
            Shuttle.Status.OPEN,
            Shuttle.Status.FULL,
            Shuttle.Status.LOCKED,
        ):
            assert status not in excluded
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/shuttles/tests/test_models.py -v`
Expected: FAIL with `AttributeError: type object 'Status' has no attribute 'drc_recheck_excluded'`

- [ ] **Step 3: Write minimal implementation**

In `wafer_space/shuttles/models.py`, add the classmethod inside `class Status(models.TextChoices)` directly after the `CANCELLED = "cancelled", "Cancelled"` line (line 71):

```python
        @classmethod
        def drc_recheck_excluded(cls) -> list[str]:
            """Shuttle statuses excluded from AUTOMATIC DRC re-runs.

            Designs in these states are in fabrication, already manufactured,
            or abandoned, so re-running DRC after a precheck-version bump
            serves no purpose. This gates only the automatic requeue task
            (checks_drc_update_requeue); the manual "Recheck with Latest"
            action is never blocked by shuttle status. See issue #270.
            """
            return [cls.IN_PRODUCTION, cls.COMPLETED, cls.CANCELLED]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest wafer_space/shuttles/tests/test_models.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Lint and type-check**

Run: `make lint-fix && make lint && make type-check`
Expected: clean (no errors). Fix any root causes — do NOT add `# noqa`/`# type: ignore`.

- [ ] **Step 6: Commit**

```bash
git add wafer_space/shuttles/models.py wafer_space/shuttles/tests/test_models.py
git commit -m "feat: add Shuttle.Status.drc_recheck_excluded() for DRC re-run scope (#270)"
```

---

## Task 2: Scope the automatic requeue task by shuttle status

**Files:**
- Modify: `wafer_space/projects/tests/test_tasks.py` (add import near line 55-59; new test in `TestChecksDrcUpdateRequeue`, ~line 2183)
- Modify: `wafer_space/projects/tasks_checks.py` (import block; queryset at lines 727-735)

- [ ] **Step 1: Write the failing test**

In `wafer_space/projects/tests/test_tasks.py`, add the Shuttle model import alongside the existing shuttles import (`from wafer_space.shuttles.tests.factories import ShuttleFactory` at line 59):

```python
from wafer_space.shuttles.models import Shuttle
```

Then add this test method to the `TestChecksDrcUpdateRequeue` class (it already has `setup_method` creating `self.project`/`self.project_file`, but this test builds its own designs so it does not use them):

```python
    @pytest.mark.parametrize(
        ("shuttle_status", "expected_created"),
        [
            (None, 1),
            (Shuttle.Status.PLANNING, 1),
            (Shuttle.Status.OPEN, 1),
            (Shuttle.Status.FULL, 1),
            (Shuttle.Status.LOCKED, 1),
            (Shuttle.Status.IN_PRODUCTION, 0),
            (Shuttle.Status.COMPLETED, 0),
            (Shuttle.Status.CANCELLED, 0),
        ],
    )
    def test_scopes_by_shuttle_status(self, shuttle_status, expected_created):
        """Automatic requeue skips production/completed/cancelled shuttles only.

        Drives the task with exactly one outdated candidate so the
        one-check-per-run throttle cannot hide which design was chosen
        (issue #270).
        """
        shuttle = (
            ShuttleFactory(status=shuttle_status)
            if shuttle_status is not None
            else None
        )
        project = ProjectFactory(shuttle=shuttle)
        project_file = ProjectFileFactory(project=project, is_active=True)
        ManufacturabilityCheckFactory(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:old123456789012345678901234567890123456789012345678901234567",
            container_started_at=timezone.now() - timedelta(hours=2),
        )
        # Establish a newer latest digest via an unrelated design so the
        # design under test is outdated. This establisher uses the latest
        # digest, so it is never itself a candidate.
        establisher_file = ProjectFileFactory()
        ManufacturabilityCheckFactory(
            project_file=establisher_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:new456789012345678901234567890123456789012345678901234567890",
            container_started_at=timezone.now(),
        )
        cache.clear()

        result = checks_drc_update_requeue()

        assert result["created"] == expected_created
        drc_update_exists = ManufacturabilityCheck.objects.filter(
            project_file=project_file,
            trigger_reason=ManufacturabilityCheck.TriggerReason.DRC_UPDATE,
        ).exists()
        assert drc_update_exists is bool(expected_created)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest "wafer_space/projects/tests/test_tasks.py::TestChecksDrcUpdateRequeue::test_scopes_by_shuttle_status" -v`
Expected: the three excluded-status params FAIL — currently `result["created"] == 1` (and a DRC_UPDATE check exists) where the test expects `0`. The five in-scope params PASS.

- [ ] **Step 3: Write minimal implementation**

In `wafer_space/projects/tasks_checks.py`, add the import (placed/sorted by `make lint-fix` in Step 5):

```python
from wafer_space.shuttles.models import Shuttle
```

Then add the `.exclude(...)` clause to the candidate queryset (currently lines 727-735). The method chain becomes:

```python
    latest_checks = list(
        ManufacturabilityCheck.objects.filter(
            project_file__project__isnull=False,
            project_file_id=Subquery(latest_file_subquery),
        )
        .exclude(
            project_file__project__shuttle__status__in=(
                Shuttle.Status.drc_recheck_excluded()
            )
        )
        .annotate(latest_check_id=Subquery(latest_check_subquery))
        .filter(id=F("latest_check_id"))
        .select_related("project_file", "project_file__project")
    )
```

Why `.exclude()` not `.filter(status__in=included)`: a project with no shuttle has NULL `shuttle__status`, which does not match the `IN (...)` set, so `.exclude()` keeps it (Django emits `NOT (status IN (...) AND status IS NOT NULL)`). Any future shuttle status is also kept by default.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest "wafer_space/projects/tests/test_tasks.py::TestChecksDrcUpdateRequeue::test_scopes_by_shuttle_status" -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Lint and type-check (also fixes import ordering)**

Run: `make lint-fix && make lint && make type-check`
Expected: clean. `lint-fix` will sort the new `wafer_space.shuttles.models` import into the correct group.

- [ ] **Step 6: Run the full requeue test class (no regressions)**

Run: `uv run pytest wafer_space/projects/tests/test_tasks.py::TestChecksDrcUpdateRequeue -v`
Expected: all PASS (existing 11 + the new parametrized 8).

- [ ] **Step 7: Commit**

```bash
git add wafer_space/projects/tasks_checks.py wafer_space/projects/tests/test_tasks.py
git commit -m "fix: scope automatic DRC re-runs to non-terminal shuttles (#270)"
```

---

## Task 3: Regression guard — manual path is never blocked by shuttle status

**Files:**
- Modify: `wafer_space/projects/tests/test_models.py` (add `ShuttleFactory` import near lines 19-21; new test in `TestCreateCheckDrcUpdate`, ~line 3091)

This task adds a test only. It documents and protects the requirement that the shuttle filter must live in the task, never in the shared `create_check_drc_update()` model method. Because we deliberately did NOT add a shuttle guard to that method, this test should pass immediately (green) — it is a guard against a future regression, so the usual "watch it fail first" step is replaced by confirming it passes on unchanged model code.

- [ ] **Step 1: Add the factory import**

In `wafer_space/projects/tests/test_models.py`, add alongside the existing factory imports (after line 21):

```python
from wafer_space.shuttles.tests.factories import ShuttleFactory
```

(`Shuttle` is already imported at line 22; `ProjectFactory`/`ProjectFileFactory`/`ManufacturabilityCheckFactory` already imported at lines 19-21.)

- [ ] **Step 2: Write the regression test**

Add to the `TestCreateCheckDrcUpdate` class:

```python
    @pytest.mark.parametrize(
        "shuttle_status",
        [
            Shuttle.Status.IN_PRODUCTION,
            Shuttle.Status.COMPLETED,
            Shuttle.Status.CANCELLED,
        ],
    )
    def test_not_blocked_by_terminal_shuttle_status(self, shuttle_status):
        """Manual re-check works in ANY shuttle state (issue #270).

        The shuttle scope filter must live only in the automatic task; the
        shared create_check_drc_update() method must never gate on shuttle
        status, or the manual "Recheck with Latest" button would break for
        these designs.
        """
        shuttle = ShuttleFactory(status=shuttle_status)
        project = ProjectFactory(shuttle=shuttle)
        project_file = ProjectFileFactory(project=project, is_active=True)
        old_check = ManufacturabilityCheckFactory(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:old123456789012345678901234567890123456789012345678901234567",
            container_started_at=timezone.now() - timedelta(hours=2),
        )
        # Newer digest elsewhere makes old_check outdated (eligible to requeue).
        ManufacturabilityCheckFactory(
            docker_image_digest="sha256:new456789012345678901234567890123456789012345678901234567890",
            container_started_at=timezone.now(),
        )
        cache.clear()

        new_check = old_check.create_check_drc_update()

        assert (
            new_check.trigger_reason
            == ManufacturabilityCheck.TriggerReason.DRC_UPDATE
        )
        assert new_check.parent_check == old_check
```

- [ ] **Step 3: Run the test to confirm it passes (guard is green)**

Run: `uv run pytest "wafer_space/projects/tests/test_models.py::TestCreateCheckDrcUpdate::test_not_blocked_by_terminal_shuttle_status" -v`
Expected: PASS (3 passed). If any FAIL, a shuttle restriction has leaked into `create_check_drc_update()` — stop and remove it.

- [ ] **Step 4: Lint and type-check**

Run: `make lint-fix && make lint && make type-check`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add wafer_space/projects/tests/test_models.py
git commit -m "test: guard manual DRC re-check against shuttle-status blocking (#270)"
```

---

## Task 4: Full verification before review

**Files:** none (verification only)

- [ ] **Step 1: Run all affected test modules**

Run:
```bash
uv run pytest \
  wafer_space/shuttles/tests/test_models.py \
  wafer_space/projects/tests/test_tasks.py \
  wafer_space/projects/tests/test_models.py -q
```
Expected: all PASS, 0 failures.

- [ ] **Step 2: Run the full quality gate**

Run: `make lint && make type-check`
Expected: clean.

- [ ] **Step 3: Broader test sweep for the two touched apps**

Run: `uv run pytest wafer_space/projects wafer_space/shuttles -q`
Expected: all PASS (note: any failure in the unrelated flaky ToS browser test is pre-existing — re-run to confirm, do not attribute to this change).

- [ ] **Step 4: Confirm the diff matches the spec**

Run: `git diff main --stat`
Expected: only the five files from the File Structure table changed (plus the spec and this plan doc).

---

## Definition of Done (maps to spec acceptance criteria)

- [ ] `Shuttle.Status.drc_recheck_excluded()` returns `[IN_PRODUCTION, COMPLETED, CANCELLED]`.
- [ ] `checks_drc_update_requeue` creates no DRC_UPDATE check for `production`/`completed`/`cancelled` designs.
- [ ] No-shuttle drafts and `planning`/`open`/`full`/`locked` designs are still eligible.
- [ ] Manual `create_check_drc_update()` succeeds in every shuttle state (regression test green).
- [ ] `make lint` and `make type-check` clean; all affected tests pass.
