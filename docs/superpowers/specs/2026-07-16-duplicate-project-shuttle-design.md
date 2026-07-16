# Design: Admin "Duplicate Project to Another Shuttle"

- **Date:** 2026-07-16
- **Status:** Approved by user (brainstorming session);
  revised 2026-07-17 — duplication now runs asynchronously (see
  "Revision: Async Execution" below)
- **Branch:** `feature/duplicate-project-to-shuttle`

## Revision: Async Execution (2026-07-17)

Staging exposed a deployment constraint the original design missed: the
gunicorn unit runs with `ProtectSystem=strict` and both the app checkout
and `/mnt/user-files` (the target of the `wafer_space/media` symlink) in
`ReadOnlyPaths`. **The web process cannot write user files at all** —
only the Celery workers whose queue names carry `rw`
(`http:rw:downloads`, `dock:rw:checks-save`) have `ReadWritePaths` for
the user-files mount. The original synchronous copy 500'd with
`OSError: [Errno 30] Read-only file system`.

Revised flow:

- The core logic lives in `wafer_space/projects/duplication.py`
  (imports models only, like `check_operations.py`), so both the
  services layer and tasks may use it.
- The admin view pre-flights `validate_duplication()` synchronously for
  immediate error feedback, then enqueues
  `tasks_duplication.duplicate_project_task` on the
  `http:rw:downloads` queue and redirects back to the **source**
  project with a "duplication queued" message.
- The task re-validates (state may change between enqueue and
  execution), performs the same atomic copy, and records the outcome as
  admin `LogEntry` rows (ADDITION on the duplicate + CHANGE on the
  source; a CHANGE "FAILED: …" entry on the source when it fails), so
  the admin can see the result in the project's admin history.

Everything else in this design (copy semantics, validation rules,
scanner invisibility, keep-or-fail project ID) is unchanged.

## Problem

When a project manufactured (or planned) on one shuttle run should also be
manufactured on a later shuttle run (e.g. G801 → G802), there is currently no
way to carry it over. Admins must manually recreate the project, re-upload the
design file, and wait for prechecks, losing the link to the original project's
history.

## Goal

Give admins a one-click (plus confirmation) way to duplicate an existing
project onto a different shuttle from the Django admin, copying the design
file and precheck provenance, and automatically queueing a fresh
manufacturability check on the new shuttle.

## Decisions Made During Brainstorming

| Question | Decision |
|----------|----------|
| Copy depth | Metadata + latest active file + latest precheck record, then queue a fresh precheck |
| 4-char `project_id` on target | Keep the same code; **fail** the duplication if it is taken on the target shuttle |
| Grid slot on target shuttle | Not reserved; admin places the project via the existing assignment flow later |
| Starting status | `DRAFT`; the fresh precheck moves it to `(NOT_)MANUFACTURABLE` via the existing `mark_finished` flow |
| Admin UX | Button on the individual project admin change page (not a changelist action) |
| Architecture | Service-layer function + custom admin view (Approach A) |

## Architecture

```text
admin change page button
        │
        ▼
ProjectAdmin.get_urls() view  (admin/projects/project/<uuid>/duplicate/)
        │  GET: intermediate confirmation page with target-shuttle select
        │  POST: validate form
        ▼
wafer_space/projects/services/duplication_service.py
        duplicate_project_to_shuttle(*, project, target_shuttle, admin_user)
        │  single transaction.atomic() block
        ▼
models: Project, ProjectFile, ManufacturabilityCheck rows
```

Layering follows `CLAUDE.md` rules: the admin view imports the service, the
service imports models only. No task imports are needed because the periodic
check-queue scanner picks up any `ManufacturabilityCheck` in `PENDING` status.

### New/changed files

| File | Change |
|------|--------|
| `wafer_space/projects/services/duplication_service.py` | New. `duplicate_project_to_shuttle()` |
| `wafer_space/projects/exceptions.py` | Add `ProjectDuplicationError` |
| `wafer_space/projects/models.py` | Add `ManufacturabilityCheck.TriggerReason.DUPLICATED` choice |
| `wafer_space/projects/migrations/XXXX_*.py` | Migration for the choices change |
| `wafer_space/projects/admin.py` | `ProjectAdmin.get_urls()`, duplicate view, form |
| `wafer_space/templates/admin/projects/project/change_form.html` | New. Object-tools button |
| `wafer_space/templates/admin/projects/project/duplicate_confirm.html` | New. Intermediate page |
| `wafer_space/projects/tests/test_duplication_service.py` | New. Service tests |
| `wafer_space/projects/tests/test_admin_duplicate.py` | New. Admin view tests |

## Service Behaviour

`duplicate_project_to_shuttle(*, project: Project, target_shuttle: Shuttle,
admin_user: User) -> Project`

All steps run inside one `transaction.atomic()` block: either the complete
duplicate exists afterwards, or nothing was created.

### Validation (raise `ProjectDuplicationError`, abort before any writes)

1. Source project must be assigned to a shuttle, and `target_shuttle` must
   differ from it.
2. Target shuttle status must be one of `PLANNING`, `OPEN`, `FULL`, `LOCKED`
   (i.e. not `IN_PRODUCTION`, `COMPLETED`, or `CANCELLED`).
3. The source `project_id` must be unused on the target shuttle
   ("keep or fail").
4. The source project must have an active file (`is_active=True`) whose
   `download_status` is `COMPLETED` and whose `file` field references a
   stored file.

### Step 1 — Copy the `Project` row

Copied: `user`, `name`, `description`, `slot_size`, `is_public`,
`chip_on_board`, `repository_url`, `license_type`, `other_license_spdx_id`,
`proprietary_terms_url`, `proprietary_terms_cached`,
`proprietary_terms_cached_at`.

Set fresh: `shuttle=target_shuttle`, `project_id` (same value as source),
`status=DRAFT`, `submitted_at=None`, `submitted_file=None`.

**Not copied:** `crowd_supply_order_id` — a CrowdSupply order belongs to a
specific shuttle run, so the duplicate starts blank.

No `_current_user` is set on the new instance: `Project.clean()` skips the
core-field immutability check for instances being added (`_state.adding`),
so creation validates without it, and setting it would need a new
`# noqa: SLF001` (prohibited by repo policy without explicit permission).

### Step 2 — Copy the active `ProjectFile`

- File **bytes are copied in storage** to the new project's upload path
  (open the source `FileField`, save through Django's storage API). No
  re-download; the original `source_url` may be stale, and the bytes we
  already verified are authoritative.
- Copied fields: `file_type`, `original_url`, `source_url`, expected hashes,
  computed hashes (`hash_md5`/`hash_sha1`/`hash_sha256`), `hash_verified`,
  `handler_metadata`, `file_size`, `original_filename`, `processed_filename`,
  `top_cell`, `content_type`, `download_started_at`, `download_completed_at`.
- Set fresh: `project=<new project>`, `is_active=True`, `replaced_by=None`.
- **The duplicate must be invisible to the download recovery scanner.**
  `ensure_download_tasks_queued` (runs every 60 s) re-queues any active file
  with an empty `download_task_id`, and treats files with a task id but no
  DOWNLOADING/COMPLETED/FAILED attempt as orphaned. `download_status` is a
  property derived from the latest `DownloadAttempt`. Therefore the service
  must also:
  1. Copy the source file's latest `DownloadAttempt` row (guaranteed
     COMPLETED by validation) to the new file with `attempt_number=1`, so
     the derived `download_status` is COMPLETED and the "queued files"
     branch skips it.
  2. Set `download_task_id` to the sentinel `f"duplicated:{source_file.pk}"`
     (non-empty, self-documenting) so the "pending files" branch skips it.
- Other `DownloadAttempt` rows and `ProjectFileChunk` history are **not**
  copied — they describe the original download's transport details.

### Step 3 — Copy the latest `ManufacturabilityCheck` (provenance)

The provenance copy uses the source file's **latest FINISHED check** (the
same selection as `ProjectFile.output_check`), not simply the newest check.
A newest-but-non-terminal check (PENDING/DISPATCHING/RUNNING) must never be
copied: the periodic check scanner dispatches every PENDING row, so a copied
PENDING check would trigger a second real run, and copied active states would
reference Docker servers/containers that do not exist. Copying only FINISHED
checks guarantees the copy is inert. If the source file has no FINISHED
check, this step is skipped.

The copy is row-copied with FKs remapped to the new project/file:

- Copied: `status` (always FINISHED), `is_manufacturable`, `errors`,
  `warnings`, `processing_logs`, `error_message`, `docker_*` metadata fields,
  `tool_versions`, `precheck_version`, timing fields, `docker_exit_code`,
  and the artifact SHA-256 fields (`log_file_sha256`, `runs_archive_sha256`,
  `output_gds_sha256`, `docker_layer_sha256`) as a record of what the
  original run produced.
- **Left empty: the four artifact `FileField`s** (`log_file`, `runs_archive`,
  `output_gds`, `docker_layer_export`). Sharing storage paths with the
  original check would corrupt one check when the other's files are cleaned
  up, and physically copying multi-GB archives is not worth it for a
  provenance record.
- Set fresh: `parent_check=None`, `trigger_reason` kept from the source,
  `rerun_requested_by=None`. `created_at` is `auto_now_add`, so the copy is
  timestamped at duplication time.
- `ManufacturabilityCheckpoint` rows and the `ManufacturabilityCheckTask`
  row are **not** copied.

(`finished_status` is a derived property, not a column — it follows from
`status` + `is_manufacturable` + `warnings` automatically.)

### Step 4 — Queue a fresh check

Create a new `ManufacturabilityCheck` with:

- `project=<new project>`, `project_file=<new file>`
- `status=PENDING` (default)
- `trigger_reason=TriggerReason.DUPLICATED` (new choice:
  `"duplicated"` / `"Project Duplicated"`)
- `parent_check=<provenance copy from step 3, or None>`

The existing periodic check-queue scanner dispatches it; on completion the
existing `mark_finished` flow sets the duplicate's status to
`MANUFACTURABLE` or `NOT_MANUFACTURABLE`.

Creating this row **after** the provenance copy guarantees it is the
`latest_manufacturability_check` for the new file.

### Return value

The new `Project` instance.

## Admin UX

1. **Button** — `wafer_space/templates/admin/projects/project/change_form.html`
   overrides the `object-tools-items` block to add a
   "Duplicate to another shuttle…" link. Shown only when the user has the
   `projects.add_project` permission and the object exists.
2. **URL** — `ProjectAdmin.get_urls()` registers
   `<uuid>/duplicate/` named `projects_project_duplicate`, wrapped in
   `admin_site.admin_view()`.
3. **Intermediate page** — shows the source project summary (name, owner,
   source shuttle, `project_id`, active file, latest check result) and a form
   with a single `ModelChoiceField` of eligible target shuttles (statuses
   from the validation list, excluding the source shuttle).
4. **POST** — *(superseded — see "Revision: Async Execution")* pre-flights
   `validate_duplication()`, then enqueues `duplicate_project_task`.
   - Success: `messages.success` ("queued"), redirect back to the
     **source** project's change page; the task later writes the
     `LogEntry` ADDITION/CHANGE rows.
   - `ProjectDuplicationError` from pre-flight: `messages.error`,
     redisplay the form.
5. **Permissions** — requires `projects.add_project`; the view returns 403
   otherwise. Non-staff users never reach it (admin site login).

## Error Handling

- All service validation errors raise `ProjectDuplicationError` with a
  user-facing message; the admin view surfaces them via `messages.error`.
- The transaction guarantees no partial duplicates. Storage-file copy happens
  inside the transaction; if the subsequent DB writes fail, the orphaned
  storage file is acceptable garbage (same trade-off the existing download
  pipeline makes) — but the copy is performed as late as possible to
  minimise the window.
- Concurrent duplication with the same `project_id` onto the same shuttle is
  caught by the DB `unique_project_id_per_shuttle` constraint. The service
  catches `IntegrityError`/`ValidationError` from `full_clean()`/`save()` and
  re-raises them as `ProjectDuplicationError`, so the admin view has a single
  exception surface.

## Testing

### Service tests (`test_duplication_service.py`, factory-boy)

- Success path: every copied field matches; `crowd_supply_order_id` blank;
  status `DRAFT`; `submitted_file`/`submitted_at` empty.
- File bytes readable from the new `ProjectFile` and identical to source;
  new storage path differs from source path.
- New file has a COMPLETED `DownloadAttempt` copy and the
  `duplicated:<pk>` sentinel `download_task_id`, so its derived
  `download_status` is COMPLETED and the recovery scanner's "pending" and
  "queued" querysets both exclude it (assert against the actual querysets
  used by `ensure_download_tasks_queued`).
- Provenance check copied with artifact `FileField`s empty and SHA fields
  populated; uses the latest FINISHED check even when a newer non-terminal
  check exists; skipped cleanly when the source has no FINISHED checks.
- Fresh check exists, `PENDING`, `trigger_reason=DUPLICATED`,
  `parent_check` set to the provenance copy.
- Each validation failure raises `ProjectDuplicationError` and creates
  nothing (assert DB counts unchanged).
- `project_id` collision on target shuttle fails.
- Per repo convention, shuttle fixtures pass explicit `name=` values and
  never rely on migration-seeded shuttles (G801).

### Admin view tests (`test_admin_duplicate.py`)

- Button rendered on the change page for staff with add permission.
- GET renders the intermediate page with only eligible shuttles listed.
- POST enqueues the duplication task (eager under pytest, so the
  duplicate materialises inline), redirects to the source project's
  change page, sets the "queued" message; the task writes `LogEntry`
  rows *(superseded wording — see "Revision: Async Execution")*.
- POST with collision shows `messages.error` and redisplays.
- User without `add_project` permission gets 403.

No browser tests: the admin pages are server-rendered with no custom
JavaScript, so the Django test client covers them.

## Out of Scope

- Reserving a grid slot on the target shuttle (use the existing assignment
  flow).
- Copying `DownloadAttempt`, `ProjectFileChunk`,
  `ManufacturabilityCheckpoint`, or `ManufacturabilityCheckTask` history.
- Copying check artifact files (`log_file`, `runs_archive`, `output_gds`,
  `docker_layer_export`).
- A user-facing (non-admin) duplication flow.
- Bulk duplication from the changelist.
