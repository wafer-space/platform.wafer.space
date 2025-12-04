# Slot Assignment Page Improvements Design

**Date:** 2025-12-04
**Status:** Approved
**GitHub Issue:** <https://github.com/wafer-space/platform.wafer.space/issues/161>

## Overview

Improvements to the shuttle slot assignment page (`/shuttles/<name>/assign/`) to enhance usability with sortable columns, better project information display, manufacturing status indicators, and improved slot selection UX.

## Requirements Summary

| Feature | Description |
|---------|-------------|
| Column sorting | Client-side JS sorting by clicking table headers |
| Username column | Show project owner in project table |
| Manufacturable in summary | Add X/Y column to summary stats table |
| Grid indicators | Icon overlay showing manufacturing check status |
| Autocomplete dropdown | Smart-sorted project search in slot modal |
| Reusable grid | Extract grid to template partial with configurable click handler |
| Grid slot picker | Replace dropdown in assign modal with mini-grid |

## Feature Details

### 1. Column Sorting (Client-side JS)

**Behavior:**
- Click column header to sort ascending
- Click again to toggle descending
- Click again to return to original order
- Visual indicator: ▲ (ascending) / ▼ (descending)

**Sortable columns:**

| Column | Sort Type |
|--------|-----------|
| Project ID | Alphabetical |
| Name | Alphabetical |
| Owner | Alphabetical (new column) |
| Size | Custom order: 1x1 > 0p5x1 > 1x0p5 > 0p5x0p5 |
| Status | Custom order: Ready > Failed > Pending |

**Implementation:**
- Add `data-sortable` attribute to `<th>` elements
- Add `data-sort-value` to `<td>` cells for custom sort values
- ~50 lines of vanilla JS in `assignment_dashboard.js`

### 2. Username Column

**Display:** Project owner's username (`project.owner.username`)

**Position:** Between "Name" and "Size" columns

**Fallback:** "—" if no owner

**View change:**
```python
projects = shuttle.projects.select_related('owner')
```

### 3. Manufacturable Column in Summary Stats

**Current summary table:**

| Size | Projects | Slots |
|------|----------|-------|

**New summary table:**

| Size | Projects | Manufacturable | Slots |
|------|----------|----------------|-------|
| 1×1 | 3/5 | 2/3 | 4/8 |

Where **2/3** = 2 manufacturable projects assigned / 3 total manufacturable projects of that size.

**View change:**
```python
stats[size] = {
    # existing...
    'manufacturable_assigned': projects.filter(
        slot_size=size,
        is_manufacturable=True,
        shuttle_slots__isnull=False
    ).distinct().count(),
    'manufacturable_total': projects.filter(
        slot_size=size,
        is_manufacturable=True
    ).count(),
}
```

### 4. Grid Manufacturing Check Indicators

**Visual:** Icon overlay in top-right corner of occupied grid cells

| Status | Icon | Color |
|--------|------|-------|
| Pass | ✓ | Green (#198754) |
| Fail | ✗ | Red (#dc3545) |
| Pending | ⏳ | Yellow (#ffc107) |

**CSS:**
```css
.slot-cell {
  position: relative;
}
.mfg-indicator {
  position: absolute;
  top: 2px;
  right: 2px;
  font-size: 0.7em;
}
```

**Template:**
```html
{% if slot.project %}
  <span class="mfg-indicator mfg-{{ slot.project.is_manufacturable|yesno:'pass,fail,pending' }}">
    {% if slot.project.is_manufacturable %}✓{% elif slot.project.is_manufacturable == False %}✗{% else %}⏳{% endif %}
  </span>
{% endif %}
```

### 5. Autocomplete Dropdown for Slot Modal

**Replaces:** `<select>` dropdown with all projects

**New behavior:** Text input that filters and shows sorted results

**Sorting priority (highest to lowest):**

| Priority | Criteria |
|----------|----------|
| 1 | Unassigned + same size + manufacturable |
| 2 | Unassigned + same size + failed |
| 3 | Unassigned + same size + pending |
| 4 | Already assigned + same size |
| 5 | Unassigned + different size + manufacturable |
| 6 | Unassigned + different size + failed |
| 7 | Unassigned + different size + pending |
| 8 | Already assigned + different size |

**Within each group:** Sort alphabetically by project ID.

**Display format:**
```text
PROJ01 ✓  My Project
PROJ02 ✓  Ready One
            ─ ─ ─
PROJ05 ✗  Broken One
            ─ ─ ─
PROJ03 ⏳  Checking...
            ─ ─ ─
PROJ06 ✓  Taken (A3, B1)
═══════════════════════
PROJ04 ✓  Big Project [1×1]
            ─ ─ ─
PROJ07 ✗  Wrong Size [1×1]
```

**Visual elements:**
- Manufacturing icon next to project ID
- Small visual breaks between status groups
- Larger break between same-size and different-size sections
- Size badge shown only for different-size projects
- Slot positions shown for assigned projects (supports multiple slots)

**Keyboard support:** ↑/↓ navigation, Enter to select, Escape to close

### 6. Reusable Grid Component

**Extract grid to:** `shuttles/templates/shuttles/_grid.html`

**Usage:**
```html
{% include "shuttles/_grid.html" with click_handler="showSlotModal" %}
{% include "shuttles/_grid.html" with click_handler="selectSlotAndSubmit" %}
```

**Grid cells:**
```html
<td class="slot-cell"
    data-slot-id="{{ slot.id }}"
    data-click-handler="{{ click_handler }}">
```

**JS initialization:**
```javascript
document.querySelectorAll('.slot-cell').forEach(cell => {
  const handler = window[cell.dataset.clickHandler];
  cell.addEventListener('click', () => handler(cell));
});
```

**Same visual appearance everywhere** - only click behavior differs.

### 7. Grid Slot Picker in Assign Modal

**Replaces:** `<select>` dropdown of available slots

**New behavior:** Embedded grid component

**Click flow:**
1. User clicks "Assign" on project row
2. Modal opens showing project info and the grid
3. User clicks desired slot in grid
4. `selectSlotAndSubmit(cell)` triggers assignment via existing AJAX

**Function:**
```javascript
function selectSlotAndSubmit(cell) {
  const slotId = cell.dataset.slotId;
  const projectId = document.getElementById('assign-project-id').value;
  doAssignment(projectId, slotId);
}
```

## Files to Modify

| File | Changes |
|------|---------|
| `shuttles/views.py` | Add `select_related('owner')`, manufacturable stats |
| `shuttles/templates/shuttles/assignment_dashboard.html` | Add columns, refactor grid to include |
| `shuttles/templates/shuttles/_grid.html` | New partial (extracted from dashboard) |
| `shuttles/static/shuttles/js/assignment_dashboard.js` | Sorting, autocomplete, grid handlers |
| `shuttles/static/shuttles/css/assignment.css` | Icon overlay styles (if separate file) |

## Error Handling

- **Assignment failures:** Existing AJAX error handling continues to work
- **Empty autocomplete:** Show "No matching projects" message
- **Size mismatch:** Existing warning system unchanged

## No Backend API Changes

All data already available in context. Changes are:
- Query optimization (`select_related`)
- Additional computed stats in context
- Template restructuring
- JavaScript enhancements

## Testing Considerations

- Existing browser tests in `tests/browser/test_shuttle_assignment.py`
- Add tests for column sorting behavior
- Add tests for autocomplete filtering
- Verify grid click handlers work in both contexts
