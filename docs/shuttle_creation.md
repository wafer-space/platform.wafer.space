# Creating a new shuttle run

Shuttle rows are **never** created by migrations: `ShuttleFactory` names test
shuttles `G800`, `G801`, ... in sequence, so a migration-seeded `G804` would
collide with test data. Each environment creates the row by hand in
`manage.py shell`. The grid comes from `shuttles/<name>-layout.yaml` via
`manage.py generate_shuttle_grid`. Later value changes (dates, status) go in
update-only data migrations (`Shuttle.objects.filter(name=...).update(...)`;
see `wafer_space/shuttles/migrations/0009_update_g801_g802_schedule.py`).

G803 (Run #3) was created this way on 7 Aug 2026. This page is the runbook for
G804 (Run #4).

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
| `technology_node`, `foundry`, `wafer_size` | copied from G803 | "same config as Run #3"; the script copies whatever the G803 row holds |
| `total_cost`, `cost_per_slot` | empty | Run #4 pricing is not published |
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
)
shuttle.save()
print("created", shuttle.pk, shuttle.name, shuttle.status)
print("copied from G803:", repr(shuttle.technology_node), repr(shuttle.foundry),
      repr(shuttle.wafer_size))
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
print("same as G803:", (s.technology_node, s.foundry, s.wafer_size)
      == (run3.technology_node, run3.foundry, run3.wafer_size))
print("costs:", s.total_cost, s.cost_per_slot)
print("dates:", s.submission_deadline, s.production_start_date,
      s.estimated_completion_date, s.actual_completion_date)
print("crowd_supply_url:", repr(s.crowd_supply_url))
print("slots:", sorted(Counter(s.slots.values_list("slot_size", flat=True)).items()))
```

Expected output:

```text
G804 GF180MCU Shuttle Run 4 planning shuttles/G804-layout.yaml
same as G803: True
costs: None None
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
