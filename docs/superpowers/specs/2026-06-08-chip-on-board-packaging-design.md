# Chip-on-Board (CoB) Packaging Support — Design

- **Date:** 2026-06-08
- **Issue:** [#259](https://github.com/wafer-space/platform.wafer.space/issues/259)
- **Status:** Approved design, pending spec review

## Summary

Let users request **Chip-on-Board (CoB) packaging** for a project. When CoB is
requested, the manufacturability precheck runs with the precheck's CoB option so
the design is validated against the extra CoB compatibility checks. The result
flows through the existing manufacturability pipeline.

## Background: the precheck interface (verified)

The CoB rules live in the separate precheck image repo
`wafer-space/gf180mcu-precheck` (`precheck.py`), **not** in this repo. Verified
against that repo on 2026-06-08:

- `precheck.py` already accepts **`--cob`** — an argparse `store_true` flag:
  `parser.add_argument("--cob", action="store_true", help="Use the CoB
  (Chip-On-Board) packaging option (extra checks).")`
- It threads a boolean config var **`WS_COB`** through the librelane flow,
  sitting alongside `WS_ID` (→ platform `--id`) and `WS_SLOT` (→ platform
  `--slot`).
- CoB enables **extra checks within the same flow**, so CoB failures appear as
  ordinary manufacturability errors — no new result format to parse.

> Note: issue #259 referred to a `--chip-on-board` flag; the real flag is
> `--cob`. This spec is authoritative. The issue should be updated to match.

The platform already builds the precheck command in
`wafer_space/projects/tasks_checks.py` (`do_starting`, ~line 1070) as an argument
list including `--slot <size>` and `--id <full_id>`. Adding `--cob` is exactly
parallel.

## Design decisions (agreed)

1. **Boolean, not a packaging enum.** The precheck models CoB as on/off
   (`WS_COB: bool`). A multi-value `packaging` choice field would be premature
   (YAGNI). Use a boolean `chip_on_board`.
2. **Editable with auto re-check.** `chip_on_board` is NOT a `CORE_FIELD`. A
   user may toggle it; toggling invalidates the current manufacturability check
   and re-runs it with/without `--cob`.
3. **CoB is orthogonal to slot/shuttle.** The precheck treats `WS_COB`
   independently of `WS_SLOT`. No added slot-size or shuttle eligibility
   constraints.

## Components

### 1. Data model (one migration)

- `Project.chip_on_board: BooleanField(default=False)` — editable; excluded from
  `CORE_FIELDS`. Mirrors `WS_COB`.
- `ManufacturabilityCheck.chip_on_board: BooleanField(default=False)` — a
  **snapshot** of the value the check actually ran with. Parallels the existing
  slot/DRC-version context recorded on checks; makes a finished result
  unambiguous and lets us detect when a toggle has made the latest result stale.

### 2. Precheck command wiring

In `tasks_checks.py` `do_starting`, where the command list is built, append
`"--cob"` iff the check's `chip_on_board` is True. `store_true` → no value. The
snapshot is read from the `ManufacturabilityCheck` so the command matches what
the check records.

### 3. Re-check on toggle (service layer)

Queuing a task must not happen in `models.py` (layering rule: models never
import tasks). A service method owns this:

- `ProjectService.set_chip_on_board(project, *, value, user)` (or equivalent in
  the existing project service package).
- On an actual change of value:
  - If the active file has a **cancellable** check, `check.mark_cancelling(
    reason="Chip-on-Board option changed")` (mirrors
    `file_service._handle_file_replacement`).
  - Queue a fresh manufacturability check carrying a new
    `ManufacturabilityCheck.TriggerReason.COB_CHANGE` and the new snapshot.
  - If the project is still DRAFT (no check yet), just persist the flag.

Add `COB_CHANGE = "cob_change", "Chip-on-Board Option Changed"` to
`ManufacturabilityCheck.TriggerReason`.

### 4. UI

- A "Request Chip-on-Board (CoB) packaging" checkbox on the project **create**
  and **edit** forms, with help text explaining it runs extra CoB compatibility
  checks. The view's form-save calls the service when the value changes so the
  re-check fires.
- Project detail: a badge indicating CoB requested (yes/no), reusing existing
  badge components. The manufacturability result already reflects the extra
  checks.

## Data flow

1. User checks "Request CoB" on create/edit → view → `set_chip_on_board`.
2. Service persists `Project.chip_on_board`, cancels any in-flight check, and
   queues a manufacturability check (`COB_CHANGE`) snapshotting `chip_on_board`.
3. `do_starting` builds the precheck command with `--cob` from the snapshot.
4. The precheck runs the extra CoB checks; results flow through the existing
   pipeline; the project detail page shows the CoB badge + manufacturability
   result.

## Error handling

- Toggling when no check is cancellable / project is DRAFT: persist only, no
  cancel (guarded by `is_cancellable` and `InvalidStateTransitionError`, as in
  `_handle_file_replacement`).
- The precheck `ValueError`/failure paths are unchanged; CoB failures are
  ordinary manufacturability errors.

## Testing (TDD)

- **Model:** `chip_on_board` defaults False; editable (not blocked by
  `CORE_FIELDS` immutability); snapshot field on `ManufacturabilityCheck`.
- **Service:** toggling CoB on a project with a running/finished check cancels
  the check and queues a new `COB_CHANGE` check with the correct snapshot;
  toggling on a DRAFT only persists.
- **Command builder:** `--cob` appended iff the check's `chip_on_board` is True;
  absent otherwise; placed alongside `--slot`/`--id`.
- **View/form:** the checkbox renders on create + edit; POSTing it sets the flag
  and invokes the service.

## Out of scope

- The CoB compatibility **rules** (already implemented in the precheck image).
- A CoB-specific result breakdown UI — CoB failures surface as normal
  manufacturability errors; a dedicated breakdown can be a follow-up.
- Per-shuttle or per-slot CoB eligibility constraints.

## Follow-ups

- Update issue #259 to reference the real `--cob` flag.
