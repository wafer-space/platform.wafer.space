# Shuttle closed-to-users rule (#320, #350): design

Date: 2026-10-11. Author: [desktop - ws-platform:6 dates]. Reviewer: the
coordinator, [desktop - ws-platform:0 coordinator].

## What Tim asked for

- #320 (shuttle open/closed semantics), Tim's answer issues-09: "Computed:
  closed after deadline or status not open".
- #350 (past shuttles as closed, linked to the website), Tim, 11 Oct 2026:
  "The platform should also show past shuttles as closed and link to
  https://wafer.space/ws-run1/ and https://wafer.space/ws-run2/".
- The coordinator's brief: one rule in one place on `Shuttle`, used by:
  - the project-creation form,
  - file submission,
  - submission for manufacturing,
  - the slot pages,
  - everywhere a shuttle is shown.

  Past shuttles are labelled closed in plain words and linked to their run
  page through a `website_url` field set by an update-only migration. The
  creation form never offers a closed shuttle. G800 (#221, later) must count
  as always open.

## Success criteria

1. One definition: a shuttle is **open** exactly when `status == open` and
   its submission deadline, if set, has not passed. Otherwise it is
   **closed**. No other code decides openness.
2. A non-staff user cannot, on a closed shuttle:
   - create a project,
   - upload a design file,
   - submit for manufacturing,
   - change chip-on-board.
3. Staff can still do all of these (dates-03, default).
4. Owners keep editing name, description, visibility, licence, repository URL
   and CrowdSupply order number on a closed shuttle.
5. Every page that names a project's shuttle shows "Closed" (lock icon and
   the word) or the open deadline, and links to the run page when one is
   known.
6. G801 links to <https://wafer.space/ws-run1/> and G802 to
   <https://wafer.space/ws-run2/>. G803 has no page yet (404 on 11 Oct 2026).

## The rule

In `wafer_space/shuttles/models.py`:

```python
class ShuttleQuerySet(models.QuerySet["Shuttle"]):
    def open_to_users(self, now: datetime | None = None) -> ShuttleQuerySet:
        now = now or timezone.now()
        return self.filter(status=Shuttle.Status.OPEN).filter(
            Q(submission_deadline__isnull=True) | Q(submission_deadline__gt=now)
        )

class Shuttle(models.Model):
    objects = ShuttleQuerySet.as_manager()

    def is_open_to_users(self, now: datetime | None = None) -> bool:
        now = now or timezone.now()
        return self.status == self.Status.OPEN and (
            self.submission_deadline is None or now < self.submission_deadline
        )

    @property
    def is_closed(self) -> bool:  # for templates
        return not self.is_open_to_users()
```

- Boundary: the shuttle is closed from the stored deadline instant onwards
  (`now >= deadline`). This matches the existing staff-assignment warning
  (`ShuttleSlot` assignment, "Shuttle submission deadline has passed").
  Deadlines are stored as 23:59:59 AoE, so a shuttle stays open until the
  last second of the published day.
- An open shuttle with no deadline is open. That covers G800 (#221) with no
  special case: it will be `open` and have no deadline.
- Nothing changes `status` automatically. Closure is computed. G802 is
  `production` and G801 `completed`, so both are closed today. G803 is
  `open` until 16 Dec 2026 23:59:59 AoE.
- A model test asserts that the QuerySet method and the instance method
  agree over a table of status × deadline cases.

## Who is blocked, and where

The rule says what is closed. One helper says what that means for a user, so
that views and forms do not each re-derive it.

`wafer_space/projects/services/shuttle_gate.py` (the services layer may
import models; views and forms import services):

```python
def closed_shuttle_reason(project: Project, user: User) -> str | None:
    """Why `user` may not change this project's design, or None if they may."""
```

It returns None for staff (dates-03, default) and for open shuttles.
Otherwise it returns "Shuttle G802 is closed: its GDS deadline has passed"
or "Shuttle G802 is closed (In Production)".

| User action | Where | When closed (non-staff) |
|---|---|---|
| Create a project | `ProjectForm.__init__` queryset and `_set_defaults` | `Shuttle.objects.open_to_users()` replaces `filter(status=OPEN)`. Editing keeps the project's own shuttle in the queryset (#297, unchanged). |
| Upload a design file | `ProjectFileSubmitURLView.get/post` | error message with the reason, redirect to the project page; nothing is created |
| Upload buttons | `project_detail.html` (two `submit_url` links) | replaced by a notice with the reason |
| Submit for manufacturing | `ProjectSubmitView.post` | error message with the reason; `Project.submit()` is not called |
| Submit button | `project_detail.html` (`project.can_submit`) | disabled, with the reason as its tooltip, through a view context value that combines `can_submit()` and the gate |
| Change chip-on-board | `ProjectForm._configure_fields` | field disabled for non-staff (dates-02, default); disabled fields ignore POST, so the CoB re-check never fires |
| Name, description, visibility, licence, repository URL, CrowdSupply order number | unchanged | still editable (regression tests) |
| Staff slot assignment | unchanged | still a warning only (#312, #314) |

`Project.can_submit()` stays about the file and the check, since a model has
no user. The gate is applied beside it in the two views. A test pins the
case "manufacturable, shuttle closed, owner" (blocked) and the same case
for staff (allowed).

## How it is shown

A template include, `shuttles/_shuttle_state.html`, takes `shuttle` and
renders one of:

- open with a deadline: `G803 · Open · GDS due 16 December 2026 @ 11:59 PM AoE`
  (the `aoe_deadline` filter from PR #351);
- open with no deadline: `G800 · Open`;
- closed: `G802` followed by a grey badge with a lock icon and the word
  "Closed".

Next to it go "Run page" (`website_url`) and "CrowdSupply" (`crowd_supply_url`)
links, each only when set. Staff pages keep the internal status beside it
("Closed · In Production"), because staff manage the status.

Used on:

- the shuttle list, detail and assignment pages (staff);
- the project detail "Shuttle Run" line;
- the project form's locked shuttle display (edit, non-staff).

The projects list has no shuttle column on main. PR #321 (shuttle and status
columns on the projects list) adds one; whichever of the two merges second
uses the include there. The creation form never lists a closed shuttle, so
its options need no label.

## Data

- New field: `Shuttle.website_url = models.URLField(blank=True, default="",
  verbose_name="wafer.space run page", help_text=...)`. It goes beside
  `crowd_supply_url`, in the admin's fieldset, through a schema migration.
- Update-only data migration, following `0009`'s style: G801 →
  `https://wafer.space/ws-run1/`, G802 → `https://wafer.space/ws-run2/`.
  It logs the counts, its reverse is `RunPython.noop`, and it creates
  nothing. Its test seeds rows with explicit names.
- No dates change (Tim, dates-01).

## Testing

- **Rule:**
  - a table over status × deadline (none, past, future, exactly now) for
    `is_open_to_users` and `open_to_users`, with an explicit `now`;
  - the AoE boundary: open at 16 Dec 23:59:58 AoE, closed at 23:59:59 AoE.
- **Gate:**
  - owner blocked, staff allowed, open shuttle allowed;
  - the reason text for a passed deadline and for a non-open status.
- **Form:**
  - the creation form offers only open-to-users shuttles: open with a past
    deadline is not offered, open with no deadline is;
  - the default pick skips closed shuttles;
  - chip-on-board is disabled for an owner on a closed shuttle and enabled
    for staff;
  - the other owner fields still save.
- **Views:**
  - an upload on a closed shuttle (GET and POST) is refused for the owner
    and no `ProjectFile` is created; staff are allowed;
  - a submit on a closed shuttle is refused for the owner and
    `submitted_file` stays unset; staff are allowed.
- **Display:**
  - "Closed" and the run-page link appear on the shuttle list, detail and
    assignment pages and on the project detail page for a closed shuttle;
  - the open text and deadline appear for an open one.
- **Migration:** the data step sets both URLs on seeded rows and creates
  nothing.
- **Browser (Playwright, headless):**
  - an owner on a closed shuttle sees the notice instead of the upload
    buttons, and the creation form does not list the closed shuttle;
  - screenshots go in the PR.

## Out of scope

- Countdowns and the user's time zone (#349).
- Warnings near the deadline (#347).
- Dropping the other schedule dates (#346).
- The CrowdSupply order-number warning (#348).
- The G800 test shuttle (#221; the rule already treats it as open).
- Excluding statuses from the automatic DRC re-run (PR #276, a separate
  list).
- Archiving (PR #353).
- AoE display in the Django admin.

## Open questions (defaults assumed)

- **dates-02:** may owners change chip-on-board once the shuttle is closed?
  Default: no, locked; staff can.
- **dates-03:** who may upload or submit after closing? Default: staff only;
  no per-project late allowance.
