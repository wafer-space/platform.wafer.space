# Archive projects — Design

**Date:** 2026-10-11
**Branch:** `issue/307-archive-projects`
**Issues:** #307 (mole99: no way to remove abandoned projects from the project
list), #244 (Tim: mark projects abandoned/obsolete), #324 (Essenceia: delete or
reconfigure a mis-configured project; the "delete" half). Related: #344 (the
unlinked delete page, deliberately not changed here).
**Status:** Approved by the coordinator 2026-10-11 with Tim's answers to
mole99-01 and mole99-03 applied.

## Problem

Users create a new project when they want to start over, and the old one stays
on `/projects/` among the active ones. mole99, 9 Oct 2026: "we really need a
way to remove projects from the project list, as it is currently unclear which
projects are active." Tim, 7 Oct 2026: "I'm against the idea of actually being
able to delete projects. I am happy to have the idea of 'archiving' or 'marking
as obsolete / abandoned'."

Tim, 11 Oct 2026 (mole99-01), word for word: "Archive button, archive items are
just always last in a person's the project list and don't appear in areas like
slot allocation and such. When a project is archived, nothing can be changed
about it and no new files can be uploaded to it. It still holds an ID for a
project - IDs should not be changing or reused."

## Requirements

| Decision | Choice | Source |
| --- | --- | --- |
| Delete anything | **No.** Every row and file stays | Tim, #307, 7 Oct |
| Who archives | Project owner, and staff on any project | Tim, mole99-01 ("Archive button") |
| Owner archiving a project with a submitted file | Refused; staff may | Tim, mole99-03 |
| Project holding a shuttle slot | Nobody may archive it until the slot assignment is removed | follows from "don't appear in slot allocation" |
| Who unarchives | Project owner, and staff on any project | Tim did not say; coordinator: keep both |
| `/projects/` list | Archived projects stay, **sorted last**, with an "Archived" badge | Tim, mole99-01 |
| While archived | Read-only: no edit, no new file, no re-check, no submit, no compliance change. Unarchive is the only write | Tim, mole99-01 |
| Slot allocation | Archived projects are not listed on, counted on, or assignable from the shuttle assignment page | Tim, mole99-01 |
| Project ID | Stays reserved; never changed or reused | Tim, mole99-01 |
| Django admin | Still shows every project; gains an `archived_at` filter | coordinator |

**Out of scope (YAGNI):** releasing project IDs; cooling-off periods; bulk
archiving; the delete page (#344); the admin summary page (staff overview of
every project; it gains an "Archived" badge only, see section 7).

## Approach

A nullable timestamp `Project.archived_at`. `NULL` means active; a value means
archived since then. A timestamp rather than a boolean, because "since when"
is the first thing staff will ask, and it costs nothing more.

**Rejected:** a new `Project.Status.ARCHIVED` value. `status` is overwritten by
check completions (see `docs/manufacturable_vs_submitted.md`); an archive
marker stored there would be lost by the next check finishing, and unarchiving
could not restore the previous status. Archiving is orthogonal to the
manufacturing state, so it gets its own field.

**Rejected:** a model-level `save()` guard that refuses every change to an
archived project. Background tasks legitimately write to the project (a check
that was already running when the project was archived still records its
result), so the guard would break them. Read-only is enforced at the user
entry points instead, from one place, with a test that fails if a new
project write view forgets it (section 4).

## Design

### 1. Model (`wafer_space/projects/models.py`)

- `archived_at = models.DateTimeField(null=True, blank=True, db_index=True,
  help_text="When the project was archived; empty while active.")`, added to
  `SYSTEM_FIELDS`, so `ProjectForm` never edits it.
- `HistoricalRecords` already tracks every field, so the admin history page
  records who archived and unarchived, and when, with no extra code.
- Property `is_archived -> bool` (`archived_at is not None`).
- Module constant `ARCHIVED_READ_ONLY_MESSAGE = "This project is archived and
  cannot be changed. Unarchive it first."`.
- `can_submit()` gains a first check: archived → `(False,
  ARCHIVED_READ_ONLY_MESSAGE)`.
- `can_be_archived_by(user) -> tuple[bool, str]`, beside `can_submit()`:
  - already archived → `(False, "Project is already archived")`;
  - holds a shuttle slot (`shuttle_slots.exists()`) → `(False, "This project
    holds a shuttle slot. Staff must remove the slot assignment before it can
    be archived.")`;
  - owner who is not staff and `submitted_file` is set → `(False, "This project
    has a file submitted for manufacturing. Contact staff to archive it.")`;
  - otherwise `(True, "")`.
- `archive()` and `unarchive()` set or clear `archived_at` and save only
  `archived_at` and `updated_at`. They hold no permission logic.

One migration adds the column to `Project` and `HistoricalProject`.

### 2. Shuttle slots (`wafer_space/shuttles/models.py`)

`ShuttleSlot.reserve()` refuses an archived project with `ValueError("Project
is archived and cannot be assigned to a slot")`. `AssignProjectView` already
turns `ValueError` into a 400 JSON error, so no view change is needed there.
The reticle package (`services/reticle_package.py`) works from slots, so
archived projects can never reach it.

### 3. Archive and unarchive views (`views.py`, `urls.py`)

- `ProjectArchiveView` at `<uuid:pk>/archive/` and `ProjectUnarchiveView` at
  `<uuid:pk>/unarchive/`, both `LoginRequiredMixin, ProjectOwnerOrStaffMixin,
  View`, POST only (GET → 405), following `ProjectSubmitView`.
- Archive refused by `can_be_archived_by` → error message, no change.
  Unarchive of an active project → info message, no change.
- Staff acting on another user's project are audit-logged by the existing
  mixin (action EDIT; the view name records which).
- Both redirect to the project detail page with a success message.

### 4. Read-only while archived, enforced in one place (`mixins.py`)

- `RefuseArchivedProjectMixin` (class-based views): in `dispatch`, after the
  owner-or-staff check, if the project is archived, add
  `ARCHIVED_READ_ONLY_MESSAGE` as an error and redirect to the project detail
  page, for every HTTP method. Applied to `ProjectUpdateView`,
  `ProjectFileSubmitURLView`, `ProjectSubmitView`.
- `refuse_if_archived(request, project) -> HttpResponse | None` (the same
  rule, for function views): applied to `check_drc_update_requeue` and
  `compliance_certification_create`. The mixin calls this function, so the
  rule and message live in one place.
- Allowed on an archived project: detail, progress and check-status (read
  only), `ProjectUnarchiveView`, staff-only `ManufacturabilityCheckCancelView`
  (stopping a check that is already running is clean-up, not a change to the
  design), and the delete page (#344 decides its fate).
- **Guard test:** a test walks every URL pattern in `projects/urls.py` that
  takes a project `pk`, and fails unless the pattern is in an explicit
  allow-list of read-only/allowed views, or a POST to it for an archived
  project is refused. A new project write view that forgets the mixin fails
  this test.

### 5. Project list (`ProjectListView`, `project_list.html`)

- `get_queryset` annotates `is_archived_sort = Q(archived_at__isnull=False)`
  (an `ExpressionWrapper` returning a boolean) and orders by
  `("is_archived_sort", "-created_at")`, so active projects come first and
  archived ones last, each group newest first as today. This applies to the
  owner's list and to staff's all-projects list.
- Each archived row: a grey "Archived" badge in the title line and the row
  muted (`text-muted`).

### 6. Project detail page (`project_detail.html`)

- Archived: a grey alert at the top, "This project was archived on <date>.
  It is read-only.", with an **Unarchive** button (POST form).
- Active: an **Archive** button in the page header beside "Admin", with a
  confirm dialog ("Archive this project? It will move to the end of your
  project list and become read-only. Nothing is deleted and you can unarchive
  it at any time."). When `can_be_archived_by` refuses, the button is disabled
  with the reason as its tooltip, as the disabled Submit button does.
- Archived: the Edit, Add/Replace file, re-check and Submit buttons are
  disabled with `ARCHIVED_READ_ONLY_MESSAGE` as their tooltip.
- No new JavaScript: plain forms with an `onsubmit` confirm, as Submit uses.

### 7. Shuttle assignment page and admin

- `ShuttleAssignmentView`: `all_projects` excludes archived projects, so they
  are neither in the counts, nor in the project table, nor in the autocomplete
  data. (Section 1 guarantees archived projects hold no slot, so the grid is
  unaffected.)
- `ProjectAdmin`: `archived_at` in `list_filter` and read-only in the change
  form.
- Admin summary page: an "Archived" badge next to the name; nothing removed.

## Error handling

- Unknown project → 404 (existing `get_object_or_404`).
- Non-owner, non-staff → 403 via `ProjectOwnerOrStaffMixin` (logged when staff).
- Archive refused by rule → error message, redirect, no change.
- Write to an archived project → error message, redirect to detail, no change.
- GET to archive or unarchive → 405.
- Assigning an archived project to a slot → 400 JSON error from `reserve()`.

## Testing

- Model: `archive()`/`unarchive()` set and clear the field; `can_submit()`
  refuses archived; `can_be_archived_by` for owner, owner with submitted file,
  staff with submitted file, project holding a slot, already archived.
- Shuttle: `reserve()` refuses archived; the assignment page omits archived
  projects from its list, counts and autocomplete data.
- Views: owner archives and unarchives; owner refused with a submitted file;
  staff archives another user's project and is audit-logged; stranger 403;
  GET 405; edit, submit-URL, submit, requeue and compliance refuse an
  archived project; the guard test over `projects/urls.py`.
- List: archived projects sort after active ones for owner and staff, and
  carry the badge.
- Browser test (headless): owner archives a project from its page; on
  `/projects/` it is last with the "Archived" badge; its page shows the Edit
  button disabled; owner unarchives it and it returns to its place.
