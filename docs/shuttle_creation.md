# Creating a new shuttle run

Shuttle rows are **never** created by migrations: `ShuttleFactory` names test
shuttles `G800`, `G801`, ... in sequence, so a migration-seeded `G804` would
collide with test data. Each environment creates the row by hand in
`manage.py shell`. The grid comes from `shuttles/<name>-layout.yaml` via
`manage.py generate_shuttle_grid`. Later value changes (dates, status) go in
update-only data migrations (`Shuttle.objects.filter(name=...).update(...)`;
see `wafer_space/shuttles/migrations/0009_update_g801_g802_schedule.py`).

G803 (Run #3) was created this way on 7 Aug 2026 (commit bb0d89e added its layout; the row was created by hand on each environment). This page is the runbook for
G804 (Run #4) and for G800, the permanent test shuttle.

## G804: GF180MCU Run #4

Tim, 11 Oct 2026: "We don't have dates yet, but should still create the new
entry in the platform with the same config as Run #3."

| Field | Value | Why |
|---|---|---|
| `name` | `G804` | |
| `description` | `GF180MCU Shuttle Run 4` | same pattern as G801 to G803 |
| `status` | `planning` | not open: the project form offers only `open` shuttles, so owners cannot pick G804 yet. Staff can already duplicate projects onto it (the admin's duplicate action accepts `planning`). |
| `submission_deadline`, `production_start_date`, `estimated_completion_date`, `actual_completion_date` | empty | no published dates yet |
| `crowd_supply_url` | empty | no CrowdSupply campaign page yet |
| `technology_node`, `foundry`, `wafer_size`, `total_cost`, `cost_per_slot` | copied from G803 | "same config as Run #3": the script copies whatever the G803 row holds (the production read of 11 Oct 2026 did not include these columns). If Run #4's pricing differs, update the cost fields when it is published. |
| grid | `shuttles/G804-layout.yaml` | identical to G803's: 6 x 9 = 54 slots (18 full, 18 half-height, 9 half-width, 9 quarter) |

### Order

1. Merge the PR that adds `shuttles/G804-layout.yaml` and deploy it. The
   grid command reads the YAML from the deployed checkout, so it must be there
   first.
2. test-platform.wafer.space: restore it from a fresh production backup, then
   run steps A to C below and check the result.
3. platform.wafer.space: steps A to C.

Run every command from the application checkout (the directory holding
`manage.py`, so that the relative `shuttles/` path resolves), as the
application user, with the environment's `.env` loaded. These are the same
conditions as any other `manage.py shell` read.

### A. Create the row

Pipe this into `manage.py shell`. It refuses to run if `G804` already exists, fails
if `G803` does not, and `Shuttle.save()` runs `full_clean()`, so a bad value
fails loudly.

```python
from wafer_space.shuttles.models import Shuttle

if Shuttle.objects.filter(name="G804").exists():
    raise SystemExit("G804 already exists; not creating it again")

run3 = Shuttle.objects.get(name="G803")
shuttle = Shuttle(
    name="G804",
    description="GF180MCU Shuttle Run 4",
    status=Shuttle.Status.PLANNING,
    technology_node=run3.technology_node,
    foundry=run3.foundry,
    wafer_size=run3.wafer_size,
    total_cost=run3.total_cost,
    cost_per_slot=run3.cost_per_slot,
)
shuttle.save()
print("created", shuttle.pk, shuttle.name, shuttle.status)
```

### B. Generate the grid

```bash
.venv/bin/python manage.py generate_shuttle_grid G804 --dry-run
.venv/bin/python manage.py generate_shuttle_grid G804
```

The dry run must report "Would create 54 slots for G804" and "Grid dimensions:
6 rows x 9 columns". The real run must report "Created 54 slots for G804".

### C. Check

Pipe this into `manage.py shell`:

```python
from collections import Counter
from wafer_space.shuttles.models import Shuttle

s = Shuttle.objects.get(name="G804")
print(s.name, s.description, s.status, s.grid_config_file)
run3 = Shuttle.objects.get(name="G803")
for field in ("technology_node", "foundry", "wafer_size", "total_cost",
              "cost_per_slot"):
    print(field, repr(getattr(run3, field)), repr(getattr(s, field)),
          getattr(run3, field) == getattr(s, field))
print("dates:", s.submission_deadline, s.production_start_date,
      s.estimated_completion_date, s.actual_completion_date)
print("crowd_supply_url:", repr(s.crowd_supply_url))
print("slots:", sorted(Counter(s.slots.values_list("slot_size", flat=True)).items()))
```

Expected output (each copied field prints G803's value, G804's value and `True`):

```text
G804 GF180MCU Shuttle Run 4 planning shuttles/G804-layout.yaml
technology_node <G803 value> <same value> True
foundry <G803 value> <same value> True
wafer_size <G803 value> <same value> True
total_cost <G803 value> <same value> True
cost_per_slot <G803 value> <same value> True
dates: None None None None
crowd_supply_url: ''
slots: [('0p5x0p5', 9), ('0p5x1', 9), ('1x0p5', 18), ('1x1', 18)]
```

Then, as a staff user in a browser:

- `/shuttles/` lists G804 with status "Planning" and no deadline.
- `/shuttles/G804/` shows no dates and 54 available slots.
- `/shuttles/G804/assign/` shows the 6 x 9 grid.
- The new-project form's shuttle list does **not** contain G804.

### Undo (before any project uses it)

Deleting the row also deletes its slots (`ShuttleSlot.shuttle` cascades). This
script refuses to delete if any project points at G804:

```python
from wafer_space.projects.models import Project
from wafer_space.shuttles.models import Shuttle

s = Shuttle.objects.get(name="G804")
if Project.objects.filter(shuttle=s).exists():
    raise SystemExit("projects use G804; not deleting")
print(s.delete())
```

### Later: dates and opening

When wafer.space and CrowdSupply publish Run #4's dates, add an update-only
data migration that sets `submission_deadline` to 23:59:59 AoE (UTC-12) of the
published GDS deadline, sets `crowd_supply_url`, and sets `status` to `open`
when submissions should start. Pages show the deadline in AoE (the
`aoe_deadline` filter in `wafer_space/shuttles/templatetags/shuttle_dates.py`).

## G800: permanent test shuttle

Tim, 11 Oct 2026 (issues-10, on #221): "Yes, create G800 (a permanent open
shuttle with all slot sizes, marked "test only", excluded from manifests and
slot assignment)".

What `is_test_only` does (the code reads only the flag, never the name):

- The shuttle is always open to users, whatever its status or deadline, so
  anyone can create a project on it, upload GDS, see the manufacturability
  check run, and submit.
- It is never the new-project form's default; its choice reads
  "G800 - ... (test only, not manufactured)". Every page that names it shows
  a "Test only" badge.
- Slot assignment (`ShuttleSlot.reserve`), the manifest, the reticle package
  and `generate_shuttle_grid` all refuse it with an error naming it as test
  only. Its assignment page shows a notice instead of a grid.
- The admin project summary lists its projects, labelled "Test only", but
  leaves them out of the counts.

| Field | Value | Why |
|---|---|---|
| `name` | `G800` | the convention for the test shuttle |
| `description` | `Test shuttle: designs are checked, never manufactured` | says what it is wherever the name appears |
| `status` | `open` | users can always use it (the flag keeps it open anyway) |
| `is_test_only` | `True` | |
| dates, `crowd_supply_url`, `website_url` | empty | nothing is made, sold or published |
| `technology_node`, `foundry`, `wafer_size` | copied from G803 | checks run against the current process |
| grid | none | slot assignment refuses it; slots that could never be assigned would mislead. Every slot size is offered regardless (the form offers all of `SlotSize` for every shuttle). |

### Order

Deploy the code with migration `shuttles.0013_shuttle_is_test_only` first,
then on test-platform.wafer.space (restored from a fresh production backup)
and then platform.wafer.space, run A and then C. There is no step B: G800 has
no grid. Same conditions as for G804: from the application checkout, as the
application user, with the environment's `.env` loaded.

### A. Create the row

Pipe this into `manage.py shell`. Running it again is safe: it refuses if
`G800` exists. It fails if `G803` does not, and `Shuttle.save()` runs
`full_clean()`.

```python
from wafer_space.shuttles.models import Shuttle

if Shuttle.objects.filter(name="G800").exists():
    raise SystemExit("G800 already exists; not creating it again")

run3 = Shuttle.objects.get(name="G803")
shuttle = Shuttle(
    name="G800",
    description="Test shuttle: designs are checked, never manufactured",
    status=Shuttle.Status.OPEN,
    is_test_only=True,
    technology_node=run3.technology_node,
    foundry=run3.foundry,
    wafer_size=run3.wafer_size,
)
shuttle.save()
print("created", shuttle.pk, shuttle.name, shuttle.status, shuttle.is_test_only)
```

### C. Check

Pipe this into `manage.py shell`:

```python
from wafer_space.shuttles.models import Shuttle

s = Shuttle.objects.get(name="G800")
print(s.name, s.status, "test_only:", s.is_test_only, "open:", s.is_open_to_users())
print(s.description)
run3 = Shuttle.objects.get(name="G803")
for field in ("technology_node", "foundry", "wafer_size"):
    print(field, getattr(run3, field) == getattr(s, field))
print("dates:", s.submission_deadline, s.production_start_date,
      s.estimated_completion_date, s.actual_completion_date)
print("urls:", repr(s.crowd_supply_url), repr(s.website_url))
print("slots:", s.slots.count())
print("default pick is G800:",
      Shuttle.objects.open_to_users().filter(is_test_only=False)
      .order_by("created_at").first() == s)
```

Expected output:

```text
G800 open test_only: True open: True
Test shuttle: designs are checked, never manufactured
technology_node True
foundry True
wafer_size True
dates: None None None None
urls: '' ''
slots: 0
default pick is G800: False
```

Then, in a browser:

- As a user, the new-project form offers
  "G800 - Test shuttle: designs are checked, never manufactured (test only,
  not manufactured)", and it is not pre-selected while a real run is open.
- As staff, `/shuttles/` shows G800 with "Open" and "Test only", and
  `/shuttles/G800/assign/` shows "G800 is test only: no slot assignment".

### Undo (before any project uses it)

```python
from wafer_space.projects.models import Project
from wafer_space.shuttles.models import Shuttle

s = Shuttle.objects.get(name="G800")
if Project.objects.filter(shuttle=s).exists():
    raise SystemExit("projects use G800; not deleting")
print(s.delete())
```
