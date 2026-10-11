# G800 permanent test shuttle (#221): design

Date: 2026-10-11. Author: [desktop - ws-platform:6 dates]. Reviewer: the
coordinator, [desktop - ws-platform:0 coordinator].

Builds on PR #365 (the computed shuttle closed rule, #320/#350). It is
branched from main after #365 merges.

## What Tim asked for

Tim, issues-10, on #221: "Yes, create G800 (a permanent open shuttle with
all slot sizes, marked "test only", excluded from manifests and slot
assignment)".

The coordinator added: the closed rule treats G800 as always open;
manifests, the reticle package and slot assignment exclude it.

## Success criteria

1. A user can always create a project on G800, choose any of the four slot
   sizes, upload GDS, see the manufacturability check run, and submit for
   manufacturing.
2. Wherever G800 is named, it says "Test only" plainly, along with what that
   means: checked, never manufactured.
3. G800 is open whatever its status or deadline.
4. G800 can never get into a manifest or a reticle package, and no project
   can be placed in a G800 slot. Each of these is refused with an error
   naming G800 as test only.
5. G800 is never the new-project form's default when a real shuttle is open.

## Design

### Marking: one field, not the name

`Shuttle.is_test_only = models.BooleanField(default=False,
verbose_name="Test only", help_text="Designs are checked but never
manufactured; never in manifests, reticle packages or slot assignment.")`.
It goes beside `status` in the admin.

The name G800 is a convention. The code reads only the flag, so a test
shuttle is never recognised by its name. This also avoids ShuttleFactory's
G8XX sequence, which starts at G800 in tests.

### The closed rule (from #365)

- `Shuttle.is_open_to_users(now)` returns True when `is_test_only`, before
  the status and deadline checks.
- `ShuttleQuerySet.open_to_users(now)` becomes
  `filter(Q(is_test_only=True) | (Q(status=OPEN) & (deadline null | deadline > now)))`.
- The table test from #365 gains test-only rows: open with every status and
  with a past deadline.

### Default pick

`ProjectForm._set_defaults` picks the oldest open-to-users shuttle that is
**not** test only. If G800 is the only open shuttle, there is no default and
the user picks G800 knowingly. The choice label for G800 carries "(test
only, not manufactured)" (see Display).

### Exclusions (fail loud, in the model or service that does the work)

| Path | Where | On a test-only shuttle |
|---|---|---|
| Slot assignment | `ShuttleSlot.reserve(project, user)` | `ValueError("G800 is a test-only shuttle; its projects are never placed in slots")`. `AssignProjectView` already turns `ValueError` into a 400 with the message. |
| Manifest | `Shuttle.generate_manifest()` (no caller today) | raises `ValueError` with the same wording |
| Reticle package | `services.reticle_package.generate_package` | raises `ReticlePackageError` before writing anything; the management command shows it |
| Grid generation | `generate_shuttle_grid` command | raises `CommandError`, so no slots are ever made for it |
| Assignment dashboard | `ShuttleAssignmentView` | renders a notice ("G800 is test only: no slot assignment") in place of the grid controls; the page still loads |

G800 gets **no grid**. Every slot size is offered for every shuttle already
(`ShuttleAvailableSizesView` returns all of `SlotSize`; the form uses
`SlotSize.full_label`), so "all slot sizes" holds without slots. Slots that
could never be assigned would mislead. The grid-preview page shows its
existing "no grid" state.

### Statistics (coordinator, 11 Oct 2026: "test projects never inflate Run numbers")

- `ProjectAdminSummaryView._compute_summary_stats` counts only projects
  whose shuttle is not test only. The table still lists G800 projects,
  labelled "Test only", so staff can see them.
- The assignment dashboard's per-size statistics only ever cover the
  page's own shuttle, so a real shuttle never counts G800 projects. On
  G800's own dashboard the statistics block gives way to the test-only
  notice.
- Test: with one G803 and one G800 project, the summary counts one.

### Display

- The `shuttles/_shuttle_state.html` include from #365 adds, for test-only
  shuttles, a badge with an icon and the words "Test only", plus a
  `title`/visually-hidden text "Designs are checked but never manufactured".
  The "Open" badge stays. There is no deadline text, since there is no
  deadline.
- The project form's choice label for a test-only shuttle reads
  `"G800 - <description> (test only, not manufactured)"`, via the field's
  `label_from_instance`. Existing labels are unchanged.
- The project page shows the include on the Shuttle Run line, as for any
  shuttle. On G800, the "Submit for Manufacturing" success message becomes
  "Submitted on G800 (test only): checked, not manufactured".

### Creating G800 on each environment

Rows are never created in migrations, because ShuttleFactory's sequence
starts at G800. `docs/shuttle_creation.md` gains a G800 section, run by
hetzner-ansible on Tim's word: a guarded `manage.py shell` create with
these values:

- `name="G800"`;
- `description="Test shuttle: designs are checked, never manufactured"`;
- `status=open`, `is_test_only=True`;
- no dates, no CrowdSupply URL, no website URL;
- technology node, foundry and wafer size copied from G803;
- no grid.

The section also has a check script with its expected output, and an undo
that refuses if projects exist.

### Out of scope

- Periodic clearing of G800 projects (#221's open question 2).
- Excluding G800 projects from staff counts (open question 3); they appear,
  labelled.
- Auto-recreating G800 (open question 1). The guarded create in the runbook
  is idempotent.

## Testing

- **Rule:** test-only rows in the table test (every status, past deadline:
  all open); the QuerySet agrees.
- **Form:**
  - G800 is offered even when no real shuttle is open;
  - it is never the default while a real shuttle is open;
  - its label carries "(test only, not manufactured)".
- **Exclusions:**
  - `reserve` raises on a G800 slot (built directly in the test);
  - `AssignProjectView` POST returns 400 with the message;
  - `generate_manifest` raises;
  - `generate_package` raises and creates no output directory.
- **Display:** "Test only" appears on the shuttle list, detail and
  assignment pages, the project page and the edit form.
- **Flow:** a project on G800 can upload (mocked download, as existing tests
  do) and submit for manufacturing; `submitted_file` is set.
- **Browser:** the owner creates a project on G800, picking the "(test only,
  not manufactured)" choice, and sees "Test only" on the project page.
- **Runbook:** scripts A, check and undo run against a local database, and
  their output matches the document.

## Questions

None blocking. Two choices are worth the coordinator's eye:

- no grid for G800, which means no assignable slots;
- G800 is never the default.
