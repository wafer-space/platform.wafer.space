# Scope automatic DRC re-runs by shuttle status (issue #270)

- **Issue:** <https://github.com/wafer-space/platform.wafer.space/issues/270>
- **Date:** 2026-06-25
- **Status:** Approved design

## Problem

When a new precheck (DRC) Docker image version is detected, the automatic
re-check task re-runs DRC on **every** project in the system, regardless of its
shuttle's status — including designs that are in fabrication, already
manufactured, or on cancelled shuttles. This wastes Docker capacity and lets
those re-runs compete for the dedicated DRC-update capacity pool, delaying
re-checks of designs that can still be acted on.

### Current behaviour (verified)

- **Trigger:** Celery beat task `checks_drc_update_requeue`, every 60s
  (`config/settings/base.py:520-523`).
- **Candidate selection:** `checks_drc_update_requeue()`
  (`wafer_space/projects/tasks_checks.py:696-794`). The selecting queryset
  (`tasks_checks.py:727-735`) filters only on `project_file__project__isnull=False`,
  "latest file for the project", and "latest check on that file". **No shuttle
  status condition.**
- `Project.shuttle` is nullable (`wafer_space/projects/models.py:196-203`), so
  projects with no shuttle are included too.
- The 25%-capacity / one-per-tick throttle (`tasks_checks.py:763-782`) bounds the
  *rate*, not the *scope* — the task works through every outdated design over time.

## Decision

Re-run DRC automatically for a design **unless** its shuttle is in a
terminal/in-fab state. Concretely:

| Shuttle state | Auto re-run? |
|---|---|
| no shuttle (draft) | yes |
| `planning` | yes |
| `open` | yes |
| `full` | yes |
| `locked` | yes |
| `production` | **no** |
| `completed` | **no** |
| `cancelled` | **no** |

This is a **blocklist** ("everything except production/completed/cancelled"),
chosen deliberately so that (a) projects with no shuttle stay in scope and
(b) any future shuttle status is included by default — only the three explicitly
terminal/in-fab states are ever dropped.

### Manual path is explicitly unaffected

The manual "Recheck with Latest" button (`check_drc_update_requeue` view,
`wafer_space/projects/views.py:958-974`, calling
`ManufacturabilityCheck.create_check_drc_update()`) must keep working in **every**
shuttle state. A human clicking that button has a reason (re-validating a record,
staff investigation), so shuttle status must not block it. Only the *automatic*
task is scoped.

Because `create_check_drc_update()` is the shared entry point for both the
automatic task (`tasks_checks.py:781`) and the manual view (`views.py:969`), the
scope filter MUST live in the automatic task's candidate queryset, NOT in that
shared model method — otherwise it would leak into the manual path.

## Design

### 1. Single source of truth — `Shuttle.Status.drc_recheck_excluded()`

Add a classmethod on `Shuttle.Status` (`wafer_space/shuttles/models.py`),
mirroring the existing `ManufacturabilityCheck.Status.active()` /
`.terminal()` precedent (`wafer_space/projects/models.py:1514-1532`):

```python
@classmethod
def drc_recheck_excluded(cls) -> list[str]:
    """Shuttle statuses excluded from AUTOMATIC DRC re-runs.

    Designs in these states are in fabrication, already manufactured, or
    abandoned, so re-running DRC after a precheck-version bump serves no
    purpose. This gates only the automatic requeue task; the manual
    "Recheck with Latest" action is never blocked by shuttle status.
    """
    return [cls.IN_PRODUCTION, cls.COMPLETED, cls.CANCELLED]
```

### 2. Scope the automatic task only

In `checks_drc_update_requeue()` (`tasks_checks.py:727-735`), add one clause to
the candidate queryset:

```python
.exclude(
    project_file__project__shuttle__status__in=Shuttle.Status.drc_recheck_excluded()
)
```

`.exclude()` (not `.filter(status__in=included)`) is required so that NULL-shuttle
drafts are kept: a null `shuttle__status` does not match the `IN (...)` set, so
those rows are not excluded. Terminal-shuttle designs are dropped from both the
candidate pool and the task's monitoring stats (intentional — the stats should
reflect the actionable population).

No change to `create_check_drc_update()`, the manual view, or the template.

## Testing (TDD — failing tests first)

In `wafer_space/projects/tests/test_tasks.py`:

1. **Scope test (one candidate at a time to avoid throttle flakiness):** the task
   creates at most one check per run (`tasks_checks.py:777-782`), so a single run
   with many candidates would only ever show `created=1` and could not prove which
   design was chosen. Instead, drive the task with exactly one outdated FINISHED
   check as the sole candidate, parametrized over the design's shuttle state:
   - For each **in-scope** state (`no-shuttle`, `planning`, `open`, `full`,
     `locked`): assert the run creates a DRC_UPDATE check (`created == 1`).
   - For each **excluded** state (`production`, `completed`, `cancelled`): assert
     the run creates nothing (`created == 0`, and no DRC_UPDATE check exists).

2. **Manual-path regression guard (locks in the requirement):** assert
   `create_check_drc_update()` still succeeds for a check whose shuttle is
   `production` / `completed` / `cancelled` — i.e. the manual path is NOT blocked
   by shuttle status.

Existing baseline: `test_tasks.py` = 82 passing.

## Acceptance criteria

- [ ] `Shuttle.Status.drc_recheck_excluded()` returns
      `[IN_PRODUCTION, COMPLETED, CANCELLED]`.
- [ ] `checks_drc_update_requeue` does not create DRC_UPDATE checks for designs
      whose shuttle is in `production` / `completed` / `cancelled`.
- [ ] Designs with no shuttle, or shuttle in `planning` / `open` / `full` /
      `locked`, are still eligible for automatic re-run.
- [ ] The manual "Recheck with Latest" action works in every shuttle state
      (no new shuttle-based restriction).
- [ ] Tests cover the scope matrix and the manual-path regression guard.
- [ ] `make lint`, `make type-check`, and the affected tests pass.

## Out of scope

- Hiding/altering the manual button in the UI.
- Staff-override semantics for the manual path (it is already unrestricted).
- Changes to version detection (`get_latest_precheck_digest`) or the throttle.
