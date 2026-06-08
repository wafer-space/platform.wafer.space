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
  `CORE_FIELDS`. Mirrors the precheck's `WS_COB`.

No new field on `ManufacturabilityCheck`. The precheck command reads
`chip_on_board` **live from `check.project`** (see §2), matching how
`--slot`/`--id` already read `check.project.slot_size`/`full_id`
(`tasks_checks.py:1057-1058`). Because toggling CoB cancels any in-flight check
and queues a new one (§3), a running check's project value is stable, so a live
read always reflects what the check was queued with — no snapshot is needed. (A
per-check snapshot could be added later if historical CoB labelling of finished
checks becomes necessary; out of scope here.)

### 2. Precheck command wiring

In `tasks_checks.py` `do_starting`, where the command list is built (the same
place `--slot`/`--id` are appended from `check.project.slot_size`/`full_id`),
append `"--cob"` iff `check.project.chip_on_board` is True. `store_true` → no
value.

### 3. Re-check on toggle (service layer)

Queuing a task must not happen in `models.py` (layering rule: models never
import tasks). A service method owns this:

- A new `ProjectService.set_chip_on_board(project, *, value, user)` in
  `wafer_space/projects/services/project_service.py`. (The existing
  `ProjectFileService` in `services/file_service.py` owns the file-replacement
  variant of this cancel+re-check logic; the shared cancel step —
  `check.is_cancellable` → `check.mark_cancelling(...)` guarded by
  `InvalidStateTransitionError` — should be reused rather than duplicated.)
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
   queues a manufacturability check (`COB_CHANGE`).
3. `do_starting` builds the precheck command with `--cob` read live from
   `check.project.chip_on_board`.
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
  `CORE_FIELDS` immutability).
- **Service:** toggling CoB on a project with a running/finished check cancels
  the check and queues a new `COB_CHANGE` check; toggling on a DRAFT only
  persists; no re-check when the submitted value is unchanged.
- **Command builder:** `--cob` appended iff `check.project.chip_on_board` is
  True; absent otherwise; placed alongside `--slot`/`--id`.
- **View/form:** the checkbox renders on create + edit; POSTing it sets the flag
  and invokes the service.

## Out of scope

- The CoB compatibility **rules** (already implemented in the precheck image).
- A CoB-specific result breakdown UI — CoB failures surface as normal
  manufacturability errors; a dedicated breakdown can be a follow-up.
- Per-shuttle or per-slot CoB eligibility constraints.

## Follow-ups

- Update issue #259 to reference the real `--cob` flag.
