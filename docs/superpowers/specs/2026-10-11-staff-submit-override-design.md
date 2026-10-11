# Staff override for "Submit for Manufacturing" — Design

**Date:** 2026-10-11
**Branch:** `issue/252-submit-override`
**Issue:** #252 (mole99: "Implement an admin override for 'Submit for
Manufacturing'. This is necessary for when there's an error or inaccuracy in
the precheck that cannot be resolved immediately.")
**Status:** Approved by the coordinator 2026-10-11, with its two additions (audit log with reason; closed-shuttle rule) folded in below.

## Decisions already made

| Decision | Choice | Source |
| --- | --- | --- |
| Who may override | Every staff user (`is_staff`) | Tim, issues-03, 11 Oct 2026 |
| What is recorded | Who overrode and a required reason, on the project; history keeps it | coordinator brief |
| Where it is shown | On the project page, naming who and when | coordinator brief |
| Audit | Every override writes a staff audit-log entry carrying the reason | coordinator, spec review |
| Minimum reason length | 20 characters | coordinator, spec review |
| No processed layout | Override refused | coordinator, spec review (matches #352: no project reaches the reticle without a layout) |
| Owner email | None | coordinator, spec review (#249 parked) |

## Problem

`Project.submit()` refuses unless the latest file revision is manufacturable
(rule 1 of `docs/manufacturable_vs_submitted.md`). When the precheck is wrong
(a false DRC error, a precheck bug), nobody can submit the design until the
precheck is fixed, which may be after the shuttle's deadline. Staff can
already submit on an owner's behalf (the normal Submit button), but only
under the same rule.

## Approach

Add a staff-only override path that skips **only** the manufacturability
requirement, records the reason, and makes the override visible to everyone
who sees the project. Everything else that makes a revision submittable
stays enforced.

**Rejected:** a per-check "force pass" flag (marking a failed check as
passed). It would falsify the check result that the precheck logs, the admin
summary and the reticle package's `check_results.csv` all report. The
override belongs to the *submission*, not the check.

**Rejected:** recording the override on `ProjectFile`. The coordinator asked
for it on the project. The project's simple_history keeps every past override
when a later submission replaces it.

## Design

### 1. Model (`wafer_space/projects/models.py`, one migration)

New fields on `Project` (system fields, never in `ProjectForm`):

- `submission_override_by = ForeignKey(User, null=True, blank=True,
  on_delete=PROTECT, related_name="+")`: who overrode. `PROTECT`, like
  `ProjectAccessLog.admin_user`, so an audit trail cannot be deleted with
  the user.
- `submission_override_reason = TextField(blank=True)`: required at least
  20 characters when set (enforced in the form and the model method).

Both stay empty for normal submissions. The time of the override is the
existing `submitted_at`.

New methods beside `can_submit()` / `submit()`:

- `can_override_submit(user) -> tuple[bool, str]`. Refuses when:
  - the user is not staff;
  - the project is archived;
  - `_latest_file_problem()` reports a problem (no active file, download not
    complete, hash not verified). These stay mandatory;
  - the latest revision has no finished check. There is nothing to override:
    wait for the check;
  - the latest finished check produced no processed layout
    (`output_gds` empty). The reticle package
    (`shuttles/services/reticle_package.py`) takes each project's layout
    from that file, so an override without it would put nothing on the
    wafer;
  - `can_submit()` already passes. Use the normal Submit; the override
    button is not shown.
- `override_submit(user, reason)`: validates with `can_override_submit` and
  the reason length, then performs the same locked write as `submit()`
  (`select_for_update` on the active revision, `submitted_file`,
  `submitted_at`, `status`) plus the two override fields.
- `submit()` (normal path) clears both override fields. A later normal
  submission of a manufacturable revision is not an override. History keeps
  the earlier one.

`ProjectAccessLog` (same migration) gains `Action.SUBMIT_OVERRIDE`
("Submitted by override") and `details = TextField(blank=True)`. The
override view writes one entry with `action=SUBMIT_OVERRIDE` and the reason
in `details` for every override, including staff overriding their own
project. The read-only `ProjectAccessLogAdmin` shows `details`.

**Closed-shuttle rule (lane C, #320/#350, not yet on main).** That rule
blocks owners but never staff, and the override is staff-only, so it needs
no special case. Once #320/#350 lands, a test asserts that a staff override
on a closed shuttle behaves exactly as a staff normal Submit does.

`docs/manufacturable_vs_submitted.md` gains a short "Staff override"
paragraph under rule 1: the one sanctioned exception, who may use it, and
what is recorded.

### 2. View and URL

`ProjectOverrideSubmitView` at `<uuid:pk>/submit-override/`: POST only;
`LoginRequiredMixin`, `ProjectOwnerOrStaffMixin`,
`RefuseArchivedProjectMixin`, plus a staff check (403 for owners who are not
staff). It uses a small `SubmitOverrideForm` (one required `reason`
textarea, minimum 20 characters). On success it shows "Submitted for
manufacturing by staff override." and redirects to the project page. On
refusal it shows the reason as an error. Staff access to another user's
project is audit-logged by the existing mixin.

The guard test of #307 (`test_archive_read_only.py`) gains the new URL under
"refused on archived".

### 3. Project page (`project_detail.html`)

- **Staff only**, where the disabled Submit button is: when
  `can_override_submit` passes, a "Submit anyway (staff override)" button
  opens an inline form (no new JavaScript beyond Bootstrap's collapse). The
  form has the required reason and a confirm dialog that names the failing
  check result.
- **Everyone who can see the project** (owner and staff): when
  `submitted_file` was submitted by override, the Submitted File card shows
  a warning banner: "Submitted by staff override — <user> on <date>:
  <reason>", plus the revision's real check verdict (not hidden).

### 4. Reticle package and admin

- `reticle_package.py` README projects table: the status column reads, for
  example, `failed (staff override)` for an overridden project, so whoever
  builds the reticle sees it. `check_results.csv` keeps its columns
  unchanged (it may be consumed by external tooling); the README is the
  human-facing marker.
- `ProjectAdmin`: both fields read-only, and a list filter "submitted by
  override".
- Admin summary page: a small "override" badge next to the status.

## Error handling

| Situation | Result |
| --- | --- |
| Non-staff POST | 403 |
| Archived project | the read-only refusal from #307 |
| Reason missing or too short | form error, nothing saved |
| Any `can_override_submit` refusal | error message, nothing saved |
| Active revision replaced between page load and POST | the same "file was replaced during submission" error as `submit()` |

## Testing

- Model: each refusal of `can_override_submit`; `override_submit` sets
  `submitted_file`, `submitted_at`, `status` and both override fields;
  normal `submit()` clears them; history records the override; the reason
  length is enforced.
- View: a staff override succeeds and is audit-logged; owner (non-staff)
  gets 403; stranger 403; archived refused; GET 405; missing reason is a
  form error.
- Page: override button for staff only and only when allowed; the override
  banner is shown to the owner.
- Reticle package: the README marks the overridden project.
- Browser test (headless): staff opens a project with a failed check that
  has an output layout, submits by override with a reason, and sees the
  banner. The owner, logged in, sees the same banner.

## Open questions for the coordinator (defaults in brackets)

1. Minimum reason length [20 characters].
2. Refuse the override when the failed check produced no processed layout
   [yes, refuse; otherwise the project silently has no layout in the
   reticle].
3. Notify the owner by email when staff override-submit their project
   [no; there is no notification system for submissions today, and #249
   (email notifications) is parked].
