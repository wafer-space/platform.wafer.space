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
(`tasks_checks.py:1057-1058`). Because toggling CoB creates a new check that
supersedes any in-flight one (§3), a running check's project value is stable, so
a live read always reflects what the check was queued with — no snapshot is
needed. (A
per-check snapshot could be added later if historical CoB labelling of finished
checks becomes necessary; out of scope here.)

### 2. Precheck command wiring

In `tasks_checks.py` `do_starting`, where the command list is built (the same
place `--slot`/`--id` are appended from `check.project.slot_size`/`full_id`),
append `"--cob"` iff `check.project.chip_on_board` is True. `store_true` → no
value.

### 3. Re-check on toggle (precheck-version-change pattern)

CoB toggling reuses the existing **precheck-version-change** mechanism, not the
file-replacement cancel path:

- Add a model method `ManufacturabilityCheck.create_check_cob_change()`,
  parallel to the existing `create_check_drc_update()` (`models.py:2269`). It
  validates that `self` is the latest check for its `project_file`, then creates
  a **new PENDING** `ManufacturabilityCheck` with
  `trigger_reason=TriggerReason.COB_CHANGE` and `parent_check=self` (chaining via
  `parent_check`/`root_check`, like DRC updates and retries). It is a plain ORM
  create — no task import and no manual cancellation. (Unlike
  `create_check_drc_update`, there are no docker-digest/version guards; the
  trigger is the user toggling, and it is valid whether the latest check is
  finished or still in progress.)
- The new pending check is dispatched by the normal check-queue processor. Any
  still-in-progress older check is auto-cancelled by the existing
  `_cancel_superseded_checks()` logic (`tasks_checks.py:1922`), which cancels an
  in-progress check once a newer check exists for the same file — exactly what
  DRC updates rely on.
- The toggle itself lives in the project edit view's form handling: persist the
  changed `Project.chip_on_board`; if the active file has a latest check, call
  `latest_check.create_check_cob_change()`. If the project has no check yet
  (DRAFT), just persist the flag — the first check reads `chip_on_board` live.

Add `COB_CHANGE = "cob_change", "Chip-on-Board Option Changed"` to
`ManufacturabilityCheck.TriggerReason`.

Because pending-check creation is pure ORM (the queue processor does the
dispatching), there is no models-import-tasks layering concern and no separate
service is required.

### 4. UI

- A "Request Chip-on-Board (CoB) packaging" checkbox on the project **create**
  and **edit** forms, with help text explaining it runs extra CoB compatibility
  checks. On save, the view creates the re-check (§3) when the value changes.
- Project detail: a badge indicating CoB requested (yes/no), reusing existing
  badge components. The manufacturability result already reflects the extra
  checks.

## Data flow

1. User checks "Request CoB" on create/edit → project edit view.
2. View persists `Project.chip_on_board`; if the active file has a latest check,
   calls `create_check_cob_change()` → a new PENDING `COB_CHANGE` check.
3. The check-queue processor dispatches the pending check; any in-progress older
   check is auto-cancelled by `_cancel_superseded_checks()`.
4. `do_starting` builds the precheck command with `--cob` read live from
   `check.project.chip_on_board`.
5. The precheck runs the extra CoB checks; results flow through the existing
   pipeline; the project detail page shows the CoB badge + manufacturability
   result.

## Error handling

- Toggling on a DRAFT project (no check yet): persist only; the first check
  reads `chip_on_board` live.
- `create_check_cob_change()` raises if called on a non-latest check (mirrors
  `create_check_drc_update`'s latest-check guard); the view only calls it on the
  active file's latest check.
- Superseding an in-progress check is handled by the existing
  `_cancel_superseded_checks()` cleanup (guarded by `InvalidStateTransitionError`),
  not by new code.
- The precheck `ValueError`/failure paths are unchanged; CoB failures are
  ordinary manufacturability errors.

## Testing (TDD)

- **Model:** `chip_on_board` defaults False; editable (not blocked by
  `CORE_FIELDS` immutability). `create_check_cob_change()` creates a PENDING
  check with `trigger_reason=COB_CHANGE` and `parent_check` set to the source
  check; raises when called on a non-latest check.
- **Toggle (view):** changing CoB on a project with a latest check creates
  exactly one new pending `COB_CHANGE` check; toggling on a DRAFT only persists;
  submitting the form with the value unchanged creates no new check.
- **Command builder:** `--cob` appended iff `check.project.chip_on_board` is
  True; absent otherwise; placed alongside `--slot`/`--id`.
- **View/form:** the checkbox renders on create + edit; POSTing it sets the flag
  and (when changed) creates the re-check.

## Out of scope

- The CoB compatibility **rules** (already implemented in the precheck image).
- A CoB-specific result breakdown UI — CoB failures surface as normal
  manufacturability errors; a dedicated breakdown can be a follow-up.
- Per-shuttle or per-slot CoB eligibility constraints.

## Follow-ups

- Update issue #259 to reference the real `--cob` flag.
