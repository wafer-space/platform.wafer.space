# Reticle Stitcher Integration Design

**Issue:** <https://github.com/wafer-space/platform.wafer.space/issues/223>

**Date:** 2025-12-16

## Overview

A Django management command that generates a directory package for the external reticle stitcher tool. The package contains CSV files describing the shuttle layout and project metadata, plus hardlinked GDS files organized by project.

## Command Interface

```bash
./manage.py generate_reticle_package G801 --output /path/to/G801 [--allow-pending]
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `shuttle_name` | Yes | Shuttle ID (e.g., "G801") |
| `--output`, `-o` | Yes | Output directory path |
| `--allow-pending` | No | Allow projects without completed checks (skip + warn) |

### Behavior

- Validates shuttle exists and has assigned projects
- **Fails immediately** if output directory already exists
- Creates directory structure with all output files
- Uses hardlinks for GDS files (falls back to copy if cross-filesystem)
- Prints summary on success (projects included, skipped, warnings)

### Exit Codes

- `0` = Success
- `1` = Error (shuttle not found, output exists, validation failure, etc.)

## Output Directory Structure

```text
G801/
├── README.md           # Human-readable summary with ASCII layout
├── tilemap.csv         # Grid of project CODEs at tile resolution
├── manifest.csv        # Project-slot mapping for reticle stitcher
├── summary.csv         # Project details overview
├── checks.csv          # Manufacturability check details for all projects
├── MOLE/
│   ├── info.json       # Complete project data dump
│   └── MOLE_TOP.gds    # Hardlinked GDS file (named by top_cell)
├── KIAN/
│   ├── info.json
│   └── KIAN_MAIN.gds
└── CAFE/
    ├── info.json
    └── CAFE_DIE.gds
```

## CSV File Formats

All CSV files are sorted by CODE (first column).

### tilemap.csv

A grid of project CODEs at tile resolution. No headers, empty string for unoccupied tiles.

**Tile mapping from slots:**

- 1×1 slot = 2×2 tiles (CODE repeated in 4 cells)
- 0.5×1 slot = 1×2 tiles (CODE in 2 cells, vertically)
- 1×0.5 slot = 2×1 tiles (CODE in 2 cells, horizontally)
- 0.5×0.5 slot = 1×1 tile (CODE in 1 cell)

**Example (simplified 4×4 tile grid):**

```csv
MOLE,MOLE,KIAN,KIAN
MOLE,MOLE,KIAN,KIAN
CAFE,CAFE,,
CAFE,CAFE,,
```

### manifest.csv

For the reticle stitcher tool.

**Columns:** `CODE,PROJECT,SLOT,TOP,HASH_SHA256,LAYOUT`

| Column | Description |
|--------|-------------|
| CODE | 4-char project_id (e.g., "MOLE") |
| PROJECT | Project name |
| SLOT | Slot size: `1x1`, `0p5x1`, `1x0p5`, or `0p5x0p5` |
| TOP | Top cell name from `project_file.top_cell` |
| HASH_SHA256 | SHA256 hash from `manufacturability_check.output_gds_sha256` |
| LAYOUT | Relative path: `{CODE}/{top_cell}.gds` |

**Note:** If a project is assigned to multiple slots, there will be multiple rows with the same CODE but different SLOT values, all pointing to the same LAYOUT file.

### summary.csv

Project overview.

**Columns:** `CODE,PROJECT_NAME,PROJECT_URL,SLOT,STATUS,TOP_CELL,SUBMITTED_AT,REPOSITORY_URL`

### checks.csv

Manufacturability check details for all projects with assigned slots (even those without completed checks).

**Columns:** `CODE,PROJECT_NAME,CHECK_STATUS,CHECK_WARNINGS,CHECK_ERRORS,CHECK_VERSION,CHECK_RUNTIME_SECONDS,CHECK_URL,INPUT_FILE_URL,INPUT_MD5,INPUT_SHA256`

**CHECK_STATUS values:**

- `manufacturable` - Check passed clean
- `manufacturable_with_warnings` - Check passed with warnings
- `not_manufacturable` - Check failed
- `no_check` - No completed check yet

## README.md Contents

```markdown
# G801 Reticle Package

**Generated:** 2025-12-16 14:32:05 UTC
**Host:** platform.wafer.space
**Code Revision:** v1.2.3-45-gabcdef1

## Shuttle Summary

| Slot Type | Total | Assigned | Submitted | Check Pass | Check Warn | Check Fail | Latest Ver |
|-----------|-------|----------|-----------|------------|------------|------------|------------|
| 1x1       | 24    | 18       | 12        | 10         | 2          | 1          | 11         |
| 0.5x1     | 8     | 6        | 4         | 3          | 1          | 0          | 4          |
| ...       |       |          |           |            |            |            |            |

Current precheck version: gf180mcu-precheck v2.1.0

## Shuttle Layout

    A   B   C   D   E   F
  +---+---+---+---+---+---+
1 |MOLE   |KIAN   |       |
  |☑ ✔ ★  |☑ ⚠ ★  |       |
  +---+---+---+---+---+---+
2 |       |       |CAFE   |
  |       |       |☐ ? ·  |
  +---+---+---+---+---+---+

Legend: [Submitted] [Check] [Version]
  ☑ Submitted    ☐ Not submitted
  ✔ Pass         ⚠ Warnings      ✘ Fail    ? No check
  ★ Current      ☆ Outdated      · N/A

## Projects

| CODE | Name | Status | Slot | Top Cell |
|------|------|--------|------|----------|
| CAFE | Cafe Chip | Assigned | 1x1 | CAFE_DIE |
| KIAN | Kian Sensor | Passing | 1x1 | KIAN_MAIN |
| MOLE | Mole Detector | Submitted | 1x1 | MOLE_TOP |
```

### Status Icons

| State | Values | Icons |
|-------|--------|-------|
| Submitted | Yes / No | ☑ / ☐ |
| Check Result | Pass / Warnings / Fail / None | ✔ / ⚠ / ✘ / ? |
| Latest Version | Current / Outdated / N/A | ★ / ☆ / · |

## info.json (Per Project)

Complete JSON dump of project data:

```json
{
  "code": "MOLE",
  "project": {
    "uuid": "...",
    "name": "Mole Detector",
    "url": "https://platform.wafer.space/projects/.../",
    "slot_size": "1x1",
    "status": "SUBMITTED",
    "submitted_at": "2025-12-15T...",
    "repository_url": "https://github.com/..."
  },
  "project_file": {
    "filename": "design.gds",
    "top_cell": "MOLE_TOP",
    "source_url": "...",
    "sha256": "..."
  },
  "manufacturability_check": {
    "status": "COMPLETED",
    "result": "manufacturable",
    "warnings_count": 2,
    "errors_count": 0,
    "version": "precheck-gf180mcu v2.1.0",
    "runtime_seconds": 127.5,
    "output_gds_sha256": "..."
  },
  "slot_positions": ["A1", "A2", "B1", "B2"]
}
```

## Data Flow

### Step 1: Load Shuttle and Grid Config

```python
shuttle = Shuttle.objects.get(name=shuttle_name)
grid_config = GridConfig(shuttle.grid_config_file)
```

### Step 2: Get All Slots (Including Empty)

```python
slots = (
    ShuttleSlot.objects
    .filter(shuttle=shuttle)
    .select_related('project', 'project__submitted_file')
    .order_by('row', 'column')
)
```

### Step 3: Find Relevant ProjectFile for Each Assigned Slot

**Without `--allow-pending`:**

```python
project_file = project.submitted_file  # Must exist
```

**With `--allow-pending`:**

```python
project_file = project.submitted_file
if not project_file:
    # Fall back to latest ProjectFile with passing check
    project_file = (
        ProjectFile.objects
        .filter(project=project, manufacturability_checks__status='COMPLETED')
        .order_by('-created_at')
        .first()
    )
```

### Step 4: Get Latest Completed ManufacturabilityCheck

```python
check = (
    ManufacturabilityCheck.objects
    .filter(project_file=project_file, status='finished')
    .order_by('-created_at')
    .first()
)
```

### Step 5: Validate Required Data

See Error Handling section.

### Step 6: Build Tilemap Grid

- Calculate tile dimensions from grid config (each slot dimension × 2)
- Place each project's CODE in the appropriate tile cells based on slot position and size

### Step 7: Write Outputs

- Create output directory and project subdirectories
- Write README.md
- Write tilemap.csv (grid data, no headers)
- Write manifest.csv, summary.csv, checks.csv (with headers, sorted by CODE)
- Write info.json per project
- Create hardlinks for GDS files

## Error Handling

### Without `--allow-pending` (Strict Mode, Default)

| Condition | Action |
|-----------|--------|
| No completed check | **Fail fast** - all assigned projects must have checks |
| Check exists but `output_gds` missing | **Fail fast** - data integrity issue |
| No `top_cell` on ProjectFile | **Fail fast** - required field |

### With `--allow-pending` (Iterative Mode)

| Condition | Action |
|-----------|--------|
| No completed check | **Skip + warn** - expected during iterative builds |
| Check exists but `output_gds` missing | **Fail fast** - data integrity issue |
| No `top_cell` on ProjectFile | **Fail fast** - required field |

## GDS File Handling

- Each `{CODE}/{top_cell}.gds` is a **hardlink** to the source `ManufacturabilityCheck.output_gds` file
- If hardlink fails (cross-filesystem), **fall back to copy** with a warning
- Duplicate projects (same project in multiple slots): single hardlink, manifest has multiple rows pointing to same file

## Implementation Notes

### File Locations

- Source GDS: `ManufacturabilityCheck.output_gds` field
- Source hash: `ManufacturabilityCheck.output_gds_sha256` field
- Top cell: `ProjectFile.top_cell` field

### Grid Dimensions

Grid dimensions are read dynamically from the shuttle's YAML config file, not hardcoded.

### Slot-to-Tile Mapping

The tilemap operates at "tile" resolution, which is 2× the "slot" resolution:

| Slot Size | Tile Size |
|-----------|-----------|
| 1×1 | 2×2 tiles |
| 0.5×1 | 1×2 tiles |
| 1×0.5 | 2×1 tiles |
| 0.5×0.5 | 1×1 tile |

## Testing Strategy

1. **Unit tests** for CSV generation functions
2. **Unit tests** for tilemap grid building
3. **Integration test** with a test shuttle and mock GDS files
4. **Test `--allow-pending`** behavior with partial data
5. **Test hardlink fallback** to copy

## Future Considerations

- OAS output format (pending issue #224)
- Web UI for triggering package generation
- Automatic package generation on shuttle lock
