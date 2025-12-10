# Slot Assignment Improvements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enhance the shuttle slot assignment dashboard with sortable columns, project owner display, manufacturing status indicators, smart autocomplete, and a reusable grid component.

**Architecture:** Client-side enhancements with minimal backend changes. Extract grid to reusable template partial. Add smart sorting logic to JavaScript for autocomplete dropdown.

**Tech Stack:** Django 5.2, Bootstrap 5, Vanilla JavaScript, pytest-selenium for browser tests.

---

## Task 1: Add Project Owner Username Column

**Files:**
- Modify: `wafer_space/shuttles/views.py:99`
- Modify: `wafer_space/shuttles/templates/shuttles/assignment_dashboard.html:127-140`
- Test: `tests/browser/test_shuttle_assignment.py`

### Step 1: Write the failing test

Add to `tests/browser/test_shuttle_assignment.py`:

```python
def test_projects_table_shows_owner_column(
    self, driver, wait, staff_user, shuttle, project_with_compliance
):
    """Test that projects table shows owner column."""
    self.perform_login(driver, staff_user.username, TEST_PASSWORD)

    driver.get(f"{self.live_server_url}/shuttles/{shuttle.name}/assign/")

    # Wait for projects table to load
    projects_table = wait.until(
        expected_conditions.presence_of_element_located((By.ID, "projects-table"))
    )

    # Check that Owner column header exists
    headers = projects_table.find_elements(By.CSS_SELECTOR, "thead th")
    header_texts = [h.text for h in headers]
    assert "Owner" in header_texts

    # Check that the owner username is shown in the table
    assert staff_user.username in projects_table.text
```

### Step 2: Run test to verify it fails

```bash
uv run pytest tests/browser/test_shuttle_assignment.py::TestShuttleAssignmentDashboard::test_projects_table_shows_owner_column -v
```

Expected: FAIL - "Owner" not in header_texts

### Step 3: Update view to add select_related for owner

In `wafer_space/shuttles/views.py`, change line 99 from:

```python
projects = shuttle.projects.all().prefetch_related("shuttle_slots")
```

to:

```python
projects = shuttle.projects.select_related("user").prefetch_related("shuttle_slots")
```

### Step 4: Add Owner column header to template

In `wafer_space/shuttles/templates/shuttles/assignment_dashboard.html`, change the table headers (around line 126-133) from:

```html
<tr>
  <th>Project ID</th>
  <th>Name</th>
  <th>Size</th>
  <th>Status</th>
  <th>Slots</th>
  <th>Actions</th>
</tr>
```

to:

```html
<tr>
  <th>Project ID</th>
  <th>Name</th>
  <th>Owner</th>
  <th>Size</th>
  <th>Status</th>
  <th>Slots</th>
  <th>Actions</th>
</tr>
```

### Step 5: Add Owner column data to table rows

In the same template, after the Name column `<td>{{ project.name }}</td>` (around line 140), add:

```html
<td>{{ project.user.username|default:"—" }}</td>
```

### Step 6: Run test to verify it passes

```bash
uv run pytest tests/browser/test_shuttle_assignment.py::TestShuttleAssignmentDashboard::test_projects_table_shows_owner_column -v
```

Expected: PASS

### Step 7: Run lint and type check

```bash
make lint-fix && make lint && make type-check
```

### Step 8: Commit

```bash
git add wafer_space/shuttles/views.py wafer_space/shuttles/templates/shuttles/assignment_dashboard.html tests/browser/test_shuttle_assignment.py
git commit -m "$(cat <<'EOF'
feat: add project owner column to assignment table

- Add Owner column between Name and Size
- Use select_related for efficient query
- Display username or "—" if no owner

Closes part of #161

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Add Manufacturable Column to Summary Stats

**Files:**
- Modify: `wafer_space/shuttles/views.py:70-88`
- Modify: `wafer_space/shuttles/templates/shuttles/assignment_dashboard.html:82-101`
- Test: `tests/browser/test_shuttle_assignment.py`

### Step 1: Write the failing test

Add to `tests/browser/test_shuttle_assignment.py`:

```python
def test_summary_shows_manufacturable_column(
    self, driver, wait, staff_user, shuttle, project_with_compliance
):
    """Test that summary table shows manufacturable column."""
    # Mark project as manufacturable
    project_with_compliance.is_manufacturable = True
    project_with_compliance.save()

    self.perform_login(driver, staff_user.username, TEST_PASSWORD)

    driver.get(f"{self.live_server_url}/shuttles/{shuttle.name}/assign/")

    # Wait for page to load
    wait.until(
        expected_conditions.presence_of_element_located(
            (By.XPATH, "//strong[text()='Summary']")
        )
    )

    # Check for Mfg column header in summary table
    page_source = driver.page_source
    assert ">Mfg<" in page_source or "Mfg</th>" in page_source
```

### Step 2: Run test to verify it fails

```bash
uv run pytest tests/browser/test_shuttle_assignment.py::TestShuttleAssignmentDashboard::test_summary_shows_manufacturable_column -v
```

Expected: FAIL - "Mfg" not found

### Step 3: Add manufacturable stats to view

In `wafer_space/shuttles/views.py`, update the stats calculation (lines 70-88). Replace:

```python
stats[slot_size] = {
    "total_slots": total_slots,
    "available_slots": available_slots,
    "projects_count": projects_count,
    "assigned_count": assigned_count,
}
```

with:

```python
# Count manufacturable projects (is_manufacturable=True)
manufacturable_projects = projects.filter(is_manufacturable=True)
manufacturable_total = manufacturable_projects.count()
manufacturable_assigned = manufacturable_projects.filter(
    shuttle_slots__isnull=False
).distinct().count()

stats[slot_size] = {
    "total_slots": total_slots,
    "available_slots": available_slots,
    "projects_count": projects_count,
    "assigned_count": assigned_count,
    "manufacturable_total": manufacturable_total,
    "manufacturable_assigned": manufacturable_assigned,
}
```

### Step 4: Add Mfg column header to summary table

In `wafer_space/shuttles/templates/shuttles/assignment_dashboard.html`, update the summary table header (around lines 84-88) from:

```html
<tr>
  <th class="py-1">Size</th>
  <th class="py-1 text-end">Proj</th>
  <th class="py-1 text-end">Slots</th>
</tr>
```

to:

```html
<tr>
  <th class="py-1">Size</th>
  <th class="py-1 text-end">Proj</th>
  <th class="py-1 text-end">Mfg</th>
  <th class="py-1 text-end">Slots</th>
</tr>
```

### Step 5: Add Mfg column data to summary rows

In the same template, update the summary table body rows (around lines 91-98). After the Proj column:

```html
<td class="py-1 text-end">{{ stat.assigned_count }}/{{ stat.projects_count }}</td>
```

Add:

```html
<td class="py-1 text-end">{{ stat.manufacturable_assigned }}/{{ stat.manufacturable_total }}</td>
```

### Step 6: Run test to verify it passes

```bash
uv run pytest tests/browser/test_shuttle_assignment.py::TestShuttleAssignmentDashboard::test_summary_shows_manufacturable_column -v
```

Expected: PASS

### Step 7: Run lint and type check

```bash
make lint-fix && make lint && make type-check
```

### Step 8: Commit

```bash
git add wafer_space/shuttles/views.py wafer_space/shuttles/templates/shuttles/assignment_dashboard.html tests/browser/test_shuttle_assignment.py
git commit -m "$(cat <<'EOF'
feat: add manufacturable column to summary stats

- Show X/Y format: assigned manufacturable / total manufacturable
- Per slot size breakdown matches existing columns
- Helps identify how many ready projects are assigned

Closes part of #161

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Add Manufacturing Check Icon Indicators to Grid

**Files:**
- Modify: `wafer_space/shuttles/templates/shuttles/assignment_dashboard.html:45-61`
- Create: `wafer_space/shuttles/static/shuttles/css/assignment.css`
- Test: `tests/browser/test_shuttle_assignment.py`

### Step 1: Write the failing test

Add to `tests/browser/test_shuttle_assignment.py`:

```python
def test_grid_shows_manufacturing_indicators(
    self, driver, wait, staff_user, shuttle, project_with_compliance
):
    """Test that grid cells show manufacturing status indicators."""
    # Mark project as manufacturable and assign to slot
    project_with_compliance.is_manufacturable = True
    project_with_compliance.save()
    slot = shuttle.slots.first()
    slot.reserve(project_with_compliance, staff_user)

    self.perform_login(driver, staff_user.username, TEST_PASSWORD)

    driver.get(f"{self.live_server_url}/shuttles/{shuttle.name}/assign/")

    # Wait for grid to load
    grid_table = wait.until(
        expected_conditions.presence_of_element_located((By.ID, "grid-table"))
    )

    # Find the assigned slot and check for manufacturing indicator
    assigned_slot = grid_table.find_element(
        By.CSS_SELECTOR, "td.table-success[data-slot-id]"
    )
    indicator = assigned_slot.find_element(By.CSS_SELECTOR, ".mfg-indicator")
    assert indicator is not None
    assert "✓" in indicator.text or "mfg-pass" in indicator.get_attribute("class")
```

### Step 2: Run test to verify it fails

```bash
uv run pytest tests/browser/test_shuttle_assignment.py::TestShuttleAssignmentDashboard::test_grid_shows_manufacturing_indicators -v
```

Expected: FAIL - Unable to locate element ".mfg-indicator"

### Step 3: Create CSS file for manufacturing indicators

Create `wafer_space/shuttles/static/shuttles/css/assignment.css`:

```css
/* Manufacturing status indicators for grid cells */
.slot-cell {
  position: relative;
}

.mfg-indicator {
  position: absolute;
  top: 1px;
  right: 2px;
  font-size: 0.65em;
  line-height: 1;
}

.mfg-pass {
  color: #198754; /* Bootstrap success green */
}

.mfg-fail {
  color: #dc3545; /* Bootstrap danger red */
}

.mfg-pending {
  color: #ffc107; /* Bootstrap warning yellow */
}
```

### Step 4: Add CSS link to template

In `wafer_space/shuttles/templates/shuttles/assignment_dashboard.html`, after `{% load static %}` (around line 3), add a block for extra CSS. First, find the existing `<style>` block inside the card-body (around line 21-33) and move these styles to the CSS file, then link the CSS.

At the top of the template after `{% block title %}...{% endblock title %}`, add:

```html
{% block extra_css %}
  <link rel="stylesheet" href="{% static 'shuttles/css/assignment.css' %}">
{% endblock extra_css %}
```

**Note:** Check if base.html has an `extra_css` block. If not, add the link inside `{% block content %}` before the container div.

### Step 5: Update grid cells with indicator class and icon

In `wafer_space/shuttles/templates/shuttles/assignment_dashboard.html`, update the grid cell `<td>` (around lines 46-61). Add `slot-cell` class and the manufacturing indicator span.

Change the existing `<td>` from:

```html
<td class="text-center {% if slot.project %}{% if slot.project.slot_size != slot.slot_size %}table-warning{% else %}table-success{% endif %}{% else %}table-secondary{% endif %}"
    style="cursor: pointer;
           vertical-align: middle"
    data-slot-id="{{ slot.pk }}"
    data-slot-position="{{ slot.grid_position }}"
    data-slot-size="{{ slot.slot_size }}"
    data-project-id="{% if slot.project %}{{ slot.project.pk }}{% endif %}"
    tabindex="0"
    role="button"
    aria-label="Slot {{ slot.grid_position }}{% if slot.project %}, assigned to {{ slot.project.project_id }}{% if slot.project.slot_size != slot.slot_size %} (size mismatch){% endif %}{% else %}, empty{% endif %}">
  {% if slot.project %}
    <strong class="font-monospace">{{ slot.project.project_id }}</strong>
  {% else %}
    <span class="text-muted">{{ slot.grid_position }}</span>
  {% endif %}
</td>
```

to:

```html
<td class="text-center slot-cell {% if slot.project %}{% if slot.project.slot_size != slot.slot_size %}table-warning{% else %}table-success{% endif %}{% else %}table-secondary{% endif %}"
    style="cursor: pointer;
           vertical-align: middle"
    data-slot-id="{{ slot.pk }}"
    data-slot-position="{{ slot.grid_position }}"
    data-slot-size="{{ slot.slot_size }}"
    data-project-id="{% if slot.project %}{{ slot.project.pk }}{% endif %}"
    tabindex="0"
    role="button"
    aria-label="Slot {{ slot.grid_position }}{% if slot.project %}, assigned to {{ slot.project.project_id }}{% if slot.project.slot_size != slot.slot_size %} (size mismatch){% endif %}{% else %}, empty{% endif %}">
  {% if slot.project %}
    <strong class="font-monospace">{{ slot.project.project_id }}</strong>
    <span class="mfg-indicator {% if slot.project.is_manufacturable %}mfg-pass{% elif slot.project.is_manufacturable is None %}mfg-pending{% else %}mfg-fail{% endif %}">
      {% if slot.project.is_manufacturable %}✓{% elif slot.project.is_manufacturable is None %}⏳{% else %}✗{% endif %}
    </span>
  {% else %}
    <span class="text-muted">{{ slot.grid_position }}</span>
  {% endif %}
</td>
```

### Step 6: Run test to verify it passes

```bash
uv run pytest tests/browser/test_shuttle_assignment.py::TestShuttleAssignmentDashboard::test_grid_shows_manufacturing_indicators -v
```

Expected: PASS

### Step 7: Run lint and type check

```bash
make lint-fix && make lint && make type-check
```

### Step 8: Commit

```bash
git add wafer_space/shuttles/static/shuttles/css/assignment.css wafer_space/shuttles/templates/shuttles/assignment_dashboard.html tests/browser/test_shuttle_assignment.py
git commit -m "$(cat <<'EOF'
feat: add manufacturing check indicators to grid cells

- Icon overlay in top-right corner of occupied cells
- ✓ green for manufacturable
- ✗ red for failed
- ⏳ yellow for pending
- New CSS file for indicator positioning

Closes part of #161

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Add Client-Side Column Sorting

**Files:**
- Modify: `wafer_space/shuttles/templates/shuttles/assignment_dashboard.html:126-133`
- Modify: `wafer_space/shuttles/static/shuttles/js/assignment_dashboard.js`
- Test: `tests/browser/test_shuttle_assignment.py`

### Step 1: Write the failing test

Add to `tests/browser/test_shuttle_assignment.py`:

```python
def test_table_columns_are_sortable(
    self, driver, wait, staff_user, shuttle, project_with_compliance
):
    """Test that clicking column headers sorts the table."""
    # Create a second project for sorting
    project2 = Project.objects.create(
        user=staff_user,
        name="Alpha Project",
        description="First alphabetically",
        shuttle=shuttle,
        project_id="ALPH",
        slot_size=SlotSize.FULL,
    )
    ProjectComplianceCertification.objects.create(
        project=project2,
        export_control_compliant=True,
        not_restricted_entity=True,
        end_use_statement="Test",
        certified_by=staff_user,
    )

    self.perform_login(driver, staff_user.username, TEST_PASSWORD)

    driver.get(f"{self.live_server_url}/shuttles/{shuttle.name}/assign/")

    # Wait for projects table to load
    wait.until(
        expected_conditions.presence_of_element_located((By.ID, "projects-table"))
    )

    # Find the Name header and click to sort
    name_header = driver.find_element(
        By.XPATH, "//table[@id='projects-table']//th[contains(text(), 'Name')]"
    )
    assert "sortable" in name_header.get_attribute("class") or name_header.get_attribute("data-sortable")

    name_header.click()

    # Wait a moment for sort to apply
    import time
    time.sleep(0.1)

    # Get first row's name - should be "Alpha Project" (alphabetically first)
    first_row = driver.find_element(
        By.CSS_SELECTOR, "#projects-table tbody tr:first-child"
    )
    assert "Alpha" in first_row.text
```

### Step 2: Run test to verify it fails

```bash
uv run pytest tests/browser/test_shuttle_assignment.py::TestShuttleAssignmentDashboard::test_table_columns_are_sortable -v
```

Expected: FAIL - no "sortable" class or data-sortable attribute

### Step 3: Add data-sortable attributes to column headers

In `wafer_space/shuttles/templates/shuttles/assignment_dashboard.html`, update the project table headers (around lines 126-133). Change from:

```html
<tr>
  <th>Project ID</th>
  <th>Name</th>
  <th>Owner</th>
  <th>Size</th>
  <th>Status</th>
  <th>Slots</th>
  <th>Actions</th>
</tr>
```

to:

```html
<tr>
  <th data-sortable="true" data-sort-type="text" class="sortable" style="cursor: pointer;">Project ID <span class="sort-indicator"></span></th>
  <th data-sortable="true" data-sort-type="text" class="sortable" style="cursor: pointer;">Name <span class="sort-indicator"></span></th>
  <th data-sortable="true" data-sort-type="text" class="sortable" style="cursor: pointer;">Owner <span class="sort-indicator"></span></th>
  <th data-sortable="true" data-sort-type="size" class="sortable" style="cursor: pointer;">Size <span class="sort-indicator"></span></th>
  <th data-sortable="true" data-sort-type="status" class="sortable" style="cursor: pointer;">Status <span class="sort-indicator"></span></th>
  <th>Slots</th>
  <th>Actions</th>
</tr>
```

### Step 4: Add data-sort-value attributes to table cells

In the same template, update the table body cells to include sort values. After the existing `<td>` definitions, add `data-sort-value` attributes where needed.

For the Size column, change:
```html
<td>
  <span class="badge bg-secondary">{{ project.get_slot_size_display }}</span>
</td>
```
to:
```html
<td data-sort-value="{{ project.slot_size }}">
  <span class="badge bg-secondary">{{ project.get_slot_size_display }}</span>
</td>
```

For the Status column, change:
```html
<td>
  {% if project.is_manufacturable %}
    <span class="badge bg-success">Ready</span>
  {% elif project.is_manufacturable is None %}
    <span class="badge bg-warning">Pending</span>
  {% else %}
    <span class="badge bg-danger">Failed</span>
  {% endif %}
</td>
```
to:
```html
<td data-sort-value="{% if project.is_manufacturable %}0{% elif project.is_manufacturable is None %}2{% else %}1{% endif %}">
  {% if project.is_manufacturable %}
    <span class="badge bg-success">Ready</span>
  {% elif project.is_manufacturable is None %}
    <span class="badge bg-warning">Pending</span>
  {% else %}
    <span class="badge bg-danger">Failed</span>
  {% endif %}
</td>
```

### Step 5: Add sorting JavaScript

In `wafer_space/shuttles/static/shuttles/js/assignment_dashboard.js`, add the sorting functionality. Add this before the `init()` function:

```javascript
// Column sorting state
let currentSortColumn = null;
let currentSortDirection = null; // 'asc', 'desc', or null

// Size sort order (largest to smallest)
const sizeSortOrder = {'1x1': 0, '0p5x1': 1, '1x0p5': 2, '0p5x0p5': 3};

// Sort the projects table by column
function sortTable(columnIndex, sortType) {
  const table = document.getElementById('projects-table');
  const tbody = table.querySelector('tbody');
  const rows = Array.from(tbody.querySelectorAll('tr'));
  const headers = table.querySelectorAll('thead th');

  // Determine sort direction
  if (currentSortColumn === columnIndex) {
    if (currentSortDirection === 'asc') {
      currentSortDirection = 'desc';
    } else if (currentSortDirection === 'desc') {
      currentSortDirection = null;
    } else {
      currentSortDirection = 'asc';
    }
  } else {
    currentSortColumn = columnIndex;
    currentSortDirection = 'asc';
  }

  // Update sort indicators
  headers.forEach(function(header, idx) {
    const indicator = header.querySelector('.sort-indicator');
    if (indicator) {
      if (idx === columnIndex && currentSortDirection === 'asc') {
        indicator.textContent = ' ▲';
      } else if (idx === columnIndex && currentSortDirection === 'desc') {
        indicator.textContent = ' ▼';
      } else {
        indicator.textContent = '';
      }
    }
  });

  // If no direction, restore original order (by DOM order on page load)
  if (!currentSortDirection) {
    // Re-sort by original data-row-index if we had stored it, or just leave as-is
    // For simplicity, sort by project ID as default
    sortType = 'text';
    currentSortDirection = 'asc';
    columnIndex = 0;
  }

  // Sort rows
  rows.sort(function(a, b) {
    const aCell = a.cells[columnIndex];
    const bCell = b.cells[columnIndex];

    let aVal = aCell.dataset.sortValue || aCell.textContent.trim();
    let bVal = bCell.dataset.sortValue || bCell.textContent.trim();

    let comparison = 0;

    if (sortType === 'size') {
      comparison = (sizeSortOrder[aVal] || 99) - (sizeSortOrder[bVal] || 99);
    } else if (sortType === 'status') {
      comparison = parseInt(aVal, 10) - parseInt(bVal, 10);
    } else {
      // Text sort
      comparison = aVal.localeCompare(bVal);
    }

    return currentSortDirection === 'desc' ? -comparison : comparison;
  });

  // Re-append rows in sorted order
  rows.forEach(function(row) {
    tbody.appendChild(row);
  });
}
```

### Step 6: Add sort click handlers in init()

In the `init()` function, after the table filtering setup, add:

```javascript
// Column sorting
document.querySelectorAll('#projects-table thead th[data-sortable]').forEach(function(header, index) {
  header.addEventListener('click', function() {
    const sortType = this.dataset.sortType || 'text';
    sortTable(index, sortType);
  });
});
```

### Step 7: Run test to verify it passes

```bash
uv run pytest tests/browser/test_shuttle_assignment.py::TestShuttleAssignmentDashboard::test_table_columns_are_sortable -v
```

Expected: PASS

### Step 8: Run lint and type check

```bash
make lint-fix && make lint && make type-check
```

### Step 9: Commit

```bash
git add wafer_space/shuttles/templates/shuttles/assignment_dashboard.html wafer_space/shuttles/static/shuttles/js/assignment_dashboard.js tests/browser/test_shuttle_assignment.py
git commit -m "$(cat <<'EOF'
feat: add client-side column sorting to project table

- Click column headers to sort (asc → desc → default)
- Sort indicators ▲/▼ show current sort
- Custom sort order for Size and Status columns
- Text sort for Project ID, Name, Owner

Closes part of #161

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Refactor Grid to Reusable Template Partial

**Files:**
- Create: `wafer_space/shuttles/templates/shuttles/_grid.html`
- Modify: `wafer_space/shuttles/templates/shuttles/assignment_dashboard.html`
- Test: `tests/browser/test_shuttle_assignment.py`

### Step 1: Write the failing test

Add to `tests/browser/test_shuttle_assignment.py`:

```python
def test_grid_uses_template_partial(self, driver, wait, staff_user, shuttle):
    """Test that grid renders correctly (implies template partial works)."""
    self.perform_login(driver, staff_user.username, TEST_PASSWORD)

    driver.get(f"{self.live_server_url}/shuttles/{shuttle.name}/assign/")

    # Wait for grid to load
    grid_table = wait.until(
        expected_conditions.presence_of_element_located((By.ID, "grid-table"))
    )

    # Verify grid has click handler attribute on cells
    slot_cells = grid_table.find_elements(By.CSS_SELECTOR, "td[data-slot-id]")
    assert len(slot_cells) > 0

    # All cells should have data-click-handler attribute
    for cell in slot_cells:
        assert cell.get_attribute("data-click-handler") is not None
```

### Step 2: Run test to verify it fails

```bash
uv run pytest tests/browser/test_shuttle_assignment.py::TestShuttleAssignmentDashboard::test_grid_uses_template_partial -v
```

Expected: FAIL - data-click-handler attribute not found

### Step 3: Create the grid partial template

Create `wafer_space/shuttles/templates/shuttles/_grid.html`:

```html
{# Reusable grid component for shuttle slot visualization #}
{# Parameters: #}
{#   grid - 2D list of ShuttleSlot objects #}
{#   columns - list of column letters ['A', 'B', ...] #}
{#   click_handler - JavaScript function name to call on click #}

{% if grid %}
  <table class="table table-bordered table-sm mb-0" id="grid-table">
    <thead>
      <tr>
        <th class="text-center bg-light"></th>
        {% for col in columns %}<th class="text-center bg-light">{{ col }}</th>{% endfor %}
      </tr>
    </thead>
    <tbody>
      {% for row in grid %}
        <tr>
          <th class="text-center bg-light">{{ forloop.counter }}</th>
          {% for slot in row %}
            <td class="text-center slot-cell {% if slot.project %}{% if slot.project.slot_size != slot.slot_size %}table-warning{% else %}table-success{% endif %}{% else %}table-secondary{% endif %}"
                style="cursor: pointer;
                       vertical-align: middle"
                data-slot-id="{{ slot.pk }}"
                data-slot-position="{{ slot.grid_position }}"
                data-slot-size="{{ slot.slot_size }}"
                data-project-id="{% if slot.project %}{{ slot.project.pk }}{% endif %}"
                data-click-handler="{{ click_handler }}"
                tabindex="0"
                role="button"
                aria-label="Slot {{ slot.grid_position }}{% if slot.project %}, assigned to {{ slot.project.project_id }}{% if slot.project.slot_size != slot.slot_size %} (size mismatch){% endif %}{% else %}, empty{% endif %}">
              {% if slot.project %}
                <strong class="font-monospace">{{ slot.project.project_id }}</strong>
                <span class="mfg-indicator {% if slot.project.is_manufacturable %}mfg-pass{% elif slot.project.is_manufacturable is None %}mfg-pending{% else %}mfg-fail{% endif %}">
                  {% if slot.project.is_manufacturable %}✓{% elif slot.project.is_manufacturable is None %}⏳{% else %}✗{% endif %}
                </span>
              {% else %}
                <span class="text-muted">{{ slot.grid_position }}</span>
              {% endif %}
            </td>
          {% endfor %}
        </tr>
      {% endfor %}
    </tbody>
  </table>
{% else %}
  <div class="alert alert-info mb-0">
    No grid configured.
  </div>
{% endif %}
```

### Step 4: Update dashboard template to use include

In `wafer_space/shuttles/templates/shuttles/assignment_dashboard.html`, replace the entire grid table section (from the `{% if grid %}` around line 20 to the closing `{% endif %}` around line 71) with:

```html
{% include "shuttles/_grid.html" with grid=grid columns=columns click_handler="showSlotModal" %}
```

Also remove the inline `<style>` block for grid-table that was inside the card-body, as those styles should now be in the CSS file.

### Step 5: Update JavaScript to use data-click-handler

In `wafer_space/shuttles/static/shuttles/js/assignment_dashboard.js`, update the grid cell click handler in `init()`. Change from:

```javascript
// Grid slot cells - click and keyboard
document.querySelectorAll('#grid-table td[data-slot-id]').forEach(function(cell) {
  cell.addEventListener('click', function() {
    showSlotModal(this);
  });
  cell.addEventListener('keydown', function(event) {
    if (event.key === 'Enter' || event.key === ' ') {
      showSlotModal(this);
      event.preventDefault();
    }
  });
});
```

to:

```javascript
// Grid slot cells - click and keyboard (using configurable handler)
document.querySelectorAll('#grid-table td[data-slot-id]').forEach(function(cell) {
  var handlerName = cell.dataset.clickHandler;
  var handler = window[handlerName];
  if (handler) {
    cell.addEventListener('click', function() {
      handler(this);
    });
    cell.addEventListener('keydown', function(event) {
      if (event.key === 'Enter' || event.key === ' ') {
        handler(this);
        event.preventDefault();
      }
    });
  }
});
```

Also, make `showSlotModal` available on window by adding at the end of the IIFE, before the closing `})();`:

```javascript
// Expose functions for grid click handlers
window.showSlotModal = showSlotModal;
```

### Step 6: Move grid styles to CSS file

Add to `wafer_space/shuttles/static/shuttles/css/assignment.css`:

```css
/* Grid table styling */
#grid-table {
  border-collapse: collapse;
  font-size: 0.8rem;
  width: auto !important;
}

#grid-table th,
#grid-table td {
  border: 1px solid #333 !important;
  padding: 2px 6px !important;
}
```

### Step 7: Run test to verify it passes

```bash
uv run pytest tests/browser/test_shuttle_assignment.py::TestShuttleAssignmentDashboard::test_grid_uses_template_partial -v
```

Expected: PASS

### Step 8: Run all existing grid tests to verify no regression

```bash
uv run pytest tests/browser/test_shuttle_assignment.py -v
```

Expected: All tests PASS

### Step 9: Run lint and type check

```bash
make lint-fix && make lint && make type-check
```

### Step 10: Commit

```bash
git add wafer_space/shuttles/templates/shuttles/_grid.html wafer_space/shuttles/templates/shuttles/assignment_dashboard.html wafer_space/shuttles/static/shuttles/js/assignment_dashboard.js wafer_space/shuttles/static/shuttles/css/assignment.css tests/browser/test_shuttle_assignment.py
git commit -m "$(cat <<'EOF'
refactor: extract grid to reusable template partial

- Create _grid.html with configurable click_handler
- Update JS to read handler from data attribute
- Move grid styles to dedicated CSS file
- Prepares for grid reuse in assign modal

Closes part of #161

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Add Autocomplete Dropdown for Slot Modal

**Files:**
- Modify: `wafer_space/shuttles/views.py` (add projects_json to context)
- Modify: `wafer_space/shuttles/templates/shuttles/assignment_dashboard.html`
- Modify: `wafer_space/shuttles/static/shuttles/js/assignment_dashboard.js`
- Modify: `wafer_space/shuttles/static/shuttles/css/assignment.css`
- Test: `tests/browser/test_shuttle_assignment.py`

### Step 1: Write the failing test

Add to `tests/browser/test_shuttle_assignment.py`:

```python
def test_slot_modal_has_autocomplete_input(
    self, driver, wait, staff_user, shuttle, project_with_compliance
):
    """Test that slot modal uses autocomplete input instead of select."""
    self.perform_login(driver, staff_user.username, TEST_PASSWORD)

    driver.get(f"{self.live_server_url}/shuttles/{shuttle.name}/assign/")

    # Click a slot to open modal
    slot_cell = wait.until(
        expected_conditions.element_to_be_clickable(
            (By.CSS_SELECTOR, "td[data-slot-id]")
        )
    )
    slot_cell.click()

    # Wait for modal
    modal = wait.until(
        expected_conditions.visibility_of_element_located((By.ID, "slotModal"))
    )

    # Check for autocomplete input (not select)
    autocomplete_input = modal.find_element(By.ID, "project-search")
    assert autocomplete_input.get_attribute("type") == "text"
    assert autocomplete_input.get_attribute("autocomplete") == "off"
```

### Step 2: Run test to verify it fails

```bash
uv run pytest tests/browser/test_shuttle_assignment.py::TestShuttleAssignmentDashboard::test_slot_modal_has_autocomplete_input -v
```

Expected: FAIL - Unable to locate element with ID "project-search"

### Step 3: Add projects JSON data to view context

In `wafer_space/shuttles/views.py`, in `get_context_data()`, after the `slots_by_project` section, add:

```python
# Build projects data for autocomplete
projects_data = []
for project in projects:
    assigned_slots = [
        slot.grid_position for slot in project.shuttle_slots.all()
    ]
    projects_data.append({
        "id": project.pk,
        "project_id": project.project_id or "",
        "name": project.name,
        "slot_size": project.slot_size,
        "is_manufacturable": project.is_manufacturable,
        "is_assigned": bool(assigned_slots),
        "assigned_slots": assigned_slots,
    })
context["projects_data"] = projects_data
```

### Step 4: Add projects data JSON script to template

In `wafer_space/shuttles/templates/shuttles/assignment_dashboard.html`, after the existing `{{ slots_by_project|json_script:"slots-data" }}` line, add:

```html
{{ projects_data|json_script:"projects-data" }}
```

### Step 5: Replace select with autocomplete input in slot modal

In the template, replace the slot modal's project select section. Find:

```html
<label for="modal-project-select" class="form-label">Assign Project:</label>
<select class="form-select mb-3" id="modal-project-select">
  <option value="">-- Select a project --</option>
  {% for project in projects %}
    <option value="{{ project.pk }}"
            data-size="{{ project.slot_size }}"
            data-assigned="{% if project.shuttle_slots.exists %}true{% else %}false{% endif %}">
      {{ project.project_id }} - {{ project.name }} ({{ project.get_slot_size_display }})
      {% if project.shuttle_slots.exists %}[Already assigned]{% endif %}
    </option>
  {% endfor %}
</select>
```

Replace with:

```html
<label for="project-search" class="form-label">Assign Project:</label>
<div class="position-relative">
  <input type="text"
         class="form-control mb-2"
         id="project-search"
         placeholder="Type to search projects..."
         autocomplete="off">
  <input type="hidden" id="selected-project-id">
  <div id="project-results" class="dropdown-menu w-100" style="max-height: 300px; overflow-y: auto;"></div>
  <div id="selected-project-display" class="mb-2" style="display: none;">
    <span class="badge bg-primary" id="selected-project-badge"></span>
    <button type="button" class="btn btn-sm btn-link text-danger p-0 ms-2" id="clear-project-selection">Clear</button>
  </div>
</div>
```

### Step 6: Add autocomplete CSS styles

Add to `wafer_space/shuttles/static/shuttles/css/assignment.css`:

```css
/* Autocomplete dropdown styles */
#project-results {
  position: absolute;
  top: 100%;
  left: 0;
  z-index: 1000;
}

#project-results.show {
  display: block;
}

.autocomplete-item {
  padding: 8px 12px;
  cursor: pointer;
  border-bottom: 1px solid #eee;
}

.autocomplete-item:hover,
.autocomplete-item.active {
  background-color: #f8f9fa;
}

.autocomplete-item .project-id {
  font-family: monospace;
  font-weight: bold;
}

.autocomplete-item .project-name {
  color: #666;
}

.autocomplete-item .slot-badge {
  font-size: 0.75em;
}

.autocomplete-separator {
  padding: 4px 12px;
  background-color: #f0f0f0;
  font-size: 0.8em;
  color: #666;
  border-bottom: 1px solid #ddd;
}

.autocomplete-separator.major {
  background-color: #e0e0e0;
  border-top: 2px solid #ccc;
}
```

### Step 7: Add autocomplete JavaScript

In `wafer_space/shuttles/static/shuttles/js/assignment_dashboard.js`, add the autocomplete functionality. Add this near the top, after the existing config parsing:

```javascript
// Projects data for autocomplete
const projectsData = JSON.parse(
  document.getElementById('projects-data').textContent
);

// Autocomplete state
let filteredProjects = [];
let activeIndex = -1;
```

Add these new functions before `init()`:

```javascript
// Sort projects by relevance for autocomplete
function sortProjectsForSlot(slotSize) {
  // Priority: same size > different size
  // Within size group: manufacturable > failed > pending > assigned
  return projectsData.slice().sort(function(a, b) {
    const aSameSize = a.slot_size === slotSize;
    const bSameSize = b.slot_size === slotSize;

    // Same size first
    if (aSameSize !== bSameSize) {
      return aSameSize ? -1 : 1;
    }

    // Within same size group, sort by status
    function getPriority(proj) {
      if (proj.is_assigned) return 3;
      if (proj.is_manufacturable === true) return 0;
      if (proj.is_manufacturable === false) return 1;
      return 2; // pending (null)
    }

    const aPriority = getPriority(a);
    const bPriority = getPriority(b);

    if (aPriority !== bPriority) {
      return aPriority - bPriority;
    }

    // Within same priority, sort by project_id
    return a.project_id.localeCompare(b.project_id);
  });
}

// Filter and render autocomplete results
function filterProjects(query, slotSize) {
  const sorted = sortProjectsForSlot(slotSize);
  const lowerQuery = query.toLowerCase();

  filteredProjects = sorted.filter(function(p) {
    return p.project_id.toLowerCase().includes(lowerQuery) ||
           p.name.toLowerCase().includes(lowerQuery);
  });

  renderAutocompleteResults(slotSize);
}

// Render autocomplete dropdown
function renderAutocompleteResults(slotSize) {
  const resultsDiv = document.getElementById('project-results');

  if (filteredProjects.length === 0) {
    resultsDiv.innerHTML = '<div class="autocomplete-item text-muted">No matching projects</div>';
    resultsDiv.classList.add('show');
    return;
  }

  let html = '';
  let lastSameSize = null;
  let lastStatus = null;

  filteredProjects.forEach(function(proj, index) {
    const isSameSize = proj.slot_size === slotSize;

    // Add major separator between same-size and different-size
    if (lastSameSize !== null && lastSameSize !== isSameSize) {
      html += '<div class="autocomplete-separator major">Different size</div>';
      lastStatus = null;
    }
    lastSameSize = isSameSize;

    // Add minor separator between status groups (within same size)
    const status = proj.is_assigned ? 'assigned' :
                   proj.is_manufacturable === true ? 'ready' :
                   proj.is_manufacturable === false ? 'failed' : 'pending';

    if (lastStatus !== null && lastStatus !== status && isSameSize) {
      html += '<div class="autocomplete-separator"></div>';
    }
    lastStatus = status;

    // Manufacturing icon
    const mfgIcon = proj.is_manufacturable === true ? '✓' :
                    proj.is_manufacturable === false ? '✗' : '⏳';
    const mfgClass = proj.is_manufacturable === true ? 'mfg-pass' :
                     proj.is_manufacturable === false ? 'mfg-fail' : 'mfg-pending';

    // Size badge (only for different size)
    const sizeBadge = isSameSize ? '' :
      '<span class="badge bg-secondary slot-badge ms-1">[' + getSizeLabel(proj.slot_size) + ']</span>';

    // Assigned slots display
    const assignedDisplay = proj.is_assigned ?
      '<span class="text-muted ms-1">(' + proj.assigned_slots.join(', ') + ')</span>' : '';

    html += '<div class="autocomplete-item' + (index === activeIndex ? ' active' : '') + '" ' +
            'data-index="' + index + '" data-project-id="' + proj.id + '">' +
            '<span class="project-id">' + proj.project_id + '</span> ' +
            '<span class="' + mfgClass + '">' + mfgIcon + '</span> ' +
            '<span class="project-name">' + proj.name + '</span>' +
            sizeBadge + assignedDisplay +
            '</div>';
  });

  resultsDiv.innerHTML = html;
  resultsDiv.classList.add('show');

  // Bind click handlers
  resultsDiv.querySelectorAll('.autocomplete-item[data-project-id]').forEach(function(item) {
    item.addEventListener('click', function() {
      selectProject(parseInt(this.dataset.projectId, 10));
    });
  });
}

// Select a project from autocomplete
function selectProject(projectId) {
  const project = projectsData.find(function(p) { return p.id === projectId; });
  if (!project) return;

  document.getElementById('selected-project-id').value = projectId;
  document.getElementById('project-search').value = '';
  document.getElementById('project-results').classList.remove('show');

  // Show selected display
  const display = document.getElementById('selected-project-display');
  const badge = document.getElementById('selected-project-badge');
  const mfgIcon = project.is_manufacturable === true ? '✓' :
                  project.is_manufacturable === false ? '✗' : '⏳';
  badge.textContent = project.project_id + ' ' + mfgIcon + ' - ' + project.name;
  display.style.display = 'block';

  // Check size mismatch
  const warning = document.getElementById('size-mismatch-warning');
  if (project.slot_size !== currentSlotSize) {
    warning.style.display = 'block';
  } else {
    warning.style.display = 'none';
  }

  activeIndex = -1;
}

// Handle autocomplete keyboard navigation
function handleAutocompleteKeydown(event) {
  const resultsDiv = document.getElementById('project-results');
  if (!resultsDiv.classList.contains('show')) return;

  if (event.key === 'ArrowDown') {
    event.preventDefault();
    activeIndex = Math.min(activeIndex + 1, filteredProjects.length - 1);
    renderAutocompleteResults(currentSlotSize);
  } else if (event.key === 'ArrowUp') {
    event.preventDefault();
    activeIndex = Math.max(activeIndex - 1, 0);
    renderAutocompleteResults(currentSlotSize);
  } else if (event.key === 'Enter') {
    event.preventDefault();
    if (activeIndex >= 0 && activeIndex < filteredProjects.length) {
      selectProject(filteredProjects[activeIndex].id);
    }
  } else if (event.key === 'Escape') {
    resultsDiv.classList.remove('show');
    activeIndex = -1;
  }
}
```

### Step 8: Update showSlotModal to initialize autocomplete

Update the `showSlotModal` function to reset and initialize the autocomplete:

```javascript
function showSlotModal(cell) {
  currentSlotId = cell.dataset.slotId;
  currentSlotSize = cell.dataset.slotSize;
  const position = cell.dataset.slotPosition;
  const projectId = cell.dataset.projectId;

  document.getElementById('modal-slot-position').textContent = position;
  document.getElementById('modal-slot-size').textContent = getSizeLabel(currentSlotSize);

  // Show/hide current project section
  const currentProjectSection = document.getElementById('modal-current-project');
  if (projectId) {
    currentProjectSection.style.display = 'block';
    const strongEl = cell.querySelector('strong');
    document.getElementById('modal-current-project-id').textContent =
      strongEl ? strongEl.textContent : projectId;
  } else {
    currentProjectSection.style.display = 'none';
  }

  // Reset autocomplete
  document.getElementById('project-search').value = '';
  document.getElementById('selected-project-id').value = '';
  document.getElementById('selected-project-display').style.display = 'none';
  document.getElementById('project-results').classList.remove('show');
  document.getElementById('size-mismatch-warning').style.display = 'none';
  activeIndex = -1;

  // Pre-populate filtered list
  filterProjects('', currentSlotSize);

  const modal = new bootstrap.Modal(document.getElementById('slotModal'));
  modal.show();
}
```

### Step 9: Update assignProject to use hidden input

Update the `assignProject` function:

```javascript
function assignProject() {
  const projectId = document.getElementById('selected-project-id').value;

  if (!projectId) {
    alert('Please select a project');
    return;
  }

  doAssignment(projectId, currentSlotId);
}
```

### Step 10: Add autocomplete event listeners in init()

In `init()`, add:

```javascript
// Autocomplete input
const projectSearch = document.getElementById('project-search');
if (projectSearch) {
  projectSearch.addEventListener('input', function() {
    filterProjects(this.value, currentSlotSize);
  });
  projectSearch.addEventListener('focus', function() {
    filterProjects(this.value, currentSlotSize);
  });
  projectSearch.addEventListener('keydown', handleAutocompleteKeydown);
}

// Clear project selection
const clearBtn = document.getElementById('clear-project-selection');
if (clearBtn) {
  clearBtn.addEventListener('click', function() {
    document.getElementById('selected-project-id').value = '';
    document.getElementById('selected-project-display').style.display = 'none';
    document.getElementById('size-mismatch-warning').style.display = 'none';
    document.getElementById('project-search').focus();
  });
}

// Close autocomplete when clicking outside
document.addEventListener('click', function(event) {
  const resultsDiv = document.getElementById('project-results');
  const searchInput = document.getElementById('project-search');
  if (resultsDiv && searchInput &&
      !resultsDiv.contains(event.target) &&
      event.target !== searchInput) {
    resultsDiv.classList.remove('show');
  }
});
```

### Step 11: Run test to verify it passes

```bash
uv run pytest tests/browser/test_shuttle_assignment.py::TestShuttleAssignmentDashboard::test_slot_modal_has_autocomplete_input -v
```

Expected: PASS

### Step 12: Run all tests

```bash
uv run pytest tests/browser/test_shuttle_assignment.py -v
```

Expected: All tests PASS

### Step 13: Run lint and type check

```bash
make lint-fix && make lint && make type-check
```

### Step 14: Commit

```bash
git add wafer_space/shuttles/views.py wafer_space/shuttles/templates/shuttles/assignment_dashboard.html wafer_space/shuttles/static/shuttles/js/assignment_dashboard.js wafer_space/shuttles/static/shuttles/css/assignment.css tests/browser/test_shuttle_assignment.py
git commit -m "$(cat <<'EOF'
feat: add smart autocomplete dropdown for slot modal

- Replace select with text input autocomplete
- Smart sorting: same size > different size
- Within groups: manufacturable > failed > pending > assigned
- Visual separators between groups
- Keyboard navigation (↑/↓/Enter/Escape)
- Manufacturing status icons in results

Closes part of #161

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Replace Assign Modal Dropdown with Grid Picker

**Files:**
- Modify: `wafer_space/shuttles/templates/shuttles/assignment_dashboard.html`
- Modify: `wafer_space/shuttles/static/shuttles/js/assignment_dashboard.js`
- Test: `tests/browser/test_shuttle_assignment.py`

### Step 1: Write the failing test

Add to `tests/browser/test_shuttle_assignment.py`:

```python
def test_assign_modal_shows_grid_picker(
    self, driver, wait, staff_user, shuttle, project_with_compliance
):
    """Test that assign modal shows grid instead of dropdown."""
    self.perform_login(driver, staff_user.username, TEST_PASSWORD)

    driver.get(f"{self.live_server_url}/shuttles/{shuttle.name}/assign/")

    # Wait for projects table and click assign button
    wait.until(
        expected_conditions.presence_of_element_located((By.ID, "projects-table"))
    )

    assign_btn = driver.find_element(
        By.CSS_SELECTOR, "[data-assign-project]"
    )
    assign_btn.click()

    # Wait for assign modal
    modal = wait.until(
        expected_conditions.visibility_of_element_located((By.ID, "assignModal"))
    )

    # Check for grid in modal (not a select dropdown)
    grid_in_modal = modal.find_element(By.ID, "assign-modal-grid")
    assert grid_in_modal is not None

    # Grid should have slot cells
    slot_cells = grid_in_modal.find_elements(By.CSS_SELECTOR, "td[data-slot-id]")
    assert len(slot_cells) > 0
```

### Step 2: Run test to verify it fails

```bash
uv run pytest tests/browser/test_shuttle_assignment.py::TestShuttleAssignmentDashboard::test_assign_modal_shows_grid_picker -v
```

Expected: FAIL - Unable to locate element with ID "assign-modal-grid"

### Step 3: Update assign modal to use grid instead of dropdown

In `wafer_space/shuttles/templates/shuttles/assignment_dashboard.html`, find the assign modal section (starting around line 225). Replace the slot select dropdown with a grid include.

Find:
```html
<label for="assign-modal-slot-select" class="form-label">Add New Assignment:</label>
<select class="form-select mb-3" id="assign-modal-slot-select">
  <option value="">-- Select a slot --</option>
  {% for row in grid %}
    {% for slot in row %}
      {% if not slot.project %}
        <option value="{{ slot.pk }}" data-size="{{ slot.slot_size }}">
          {{ slot.grid_position }} ({{ slot.get_slot_size_display }})
        </option>
      {% endif %}
    {% endfor %}
  {% endfor %}
</select>
```

Replace with:
```html
<label class="form-label">Select Slot:</label>
<div id="assign-modal-grid">
  {% include "shuttles/_grid.html" with grid=grid columns=columns click_handler="selectSlotAndSubmit" %}
</div>
```

Also remove the now-unused assign button since clicking the grid will submit directly:
```html
<button class="btn btn-primary" id="assign-from-table-btn">Assign</button>
```

Keep only the size mismatch warning, which we'll update dynamically.

### Step 4: Add selectSlotAndSubmit function

In `wafer_space/shuttles/static/shuttles/js/assignment_dashboard.js`, add the new function and expose it to window:

```javascript
// Select slot and submit assignment (used by grid picker in assign modal)
function selectSlotAndSubmit(cell) {
  const slotId = cell.dataset.slotId;
  const slotSize = cell.dataset.slotSize;

  // Check if slot is already occupied
  if (cell.dataset.projectId) {
    alert('This slot is already assigned. Please choose an empty slot.');
    return;
  }

  // Show size mismatch warning if applicable
  if (slotSize !== currentProjectSize) {
    if (!confirm('Size mismatch: Slot size does not match project size. Continue anyway?')) {
      return;
    }
  }

  doAssignment(currentProjectIdForAssign, slotId);
}

// Expose to window for grid click handler
window.selectSlotAndSubmit = selectSlotAndSubmit;
```

### Step 5: Update assignSlot function to work with grid

The `assignSlot` function needs to initialize the modal grid properly. Since the grid is rendered server-side and won't change, we just need to ensure the grid uses the correct handler.

Update the `assignSlot` function to ensure the grid is properly set up:

```javascript
function assignSlot(projectId, projectName, slotSize) {
  currentProjectIdForAssign = projectId;
  currentProjectSize = slotSize;

  document.getElementById('assign-modal-project-name').textContent = projectName;
  document.getElementById('assign-modal-project-size').textContent = getSizeLabel(slotSize);

  // Show current slot assignments
  const currentSlotsSection = document.getElementById('assign-modal-current-slots');
  const slotsList = document.getElementById('assign-modal-slots-list');
  const projectSlots = slotsByProject[projectId] || [];

  if (projectSlots.length > 0) {
    currentSlotsSection.style.display = 'block';
    slotsList.innerHTML = projectSlots.map(function(slot) {
      var isMismatch = slot.size !== slotSize;
      var badgeClass = isMismatch ? 'bg-warning' : 'bg-success';
      return '<div class="d-flex justify-content-between align-items-center mb-2">' +
        '<span class="badge ' + badgeClass + '">' + slot.position + '</span>' +
        '<span class="text-muted small">' + getSizeLabel(slot.size) +
        (isMismatch ? ' (mismatch)' : '') + '</span>' +
        '<button class="btn btn-sm btn-outline-danger" data-remove-slot-id="' + slot.id + '">' +
        'Remove</button></div>';
    }).join('');

    // Bind remove buttons
    slotsList.querySelectorAll('[data-remove-slot-id]').forEach(function(btn) {
      btn.addEventListener('click', function() {
        removeSlotFromProject(this.dataset.removeSlotId);
      });
    });
  } else {
    currentSlotsSection.style.display = 'none';
    slotsList.innerHTML = '';
  }

  // Reinitialize grid click handlers for the modal grid
  const modalGrid = document.getElementById('assign-modal-grid');
  if (modalGrid) {
    modalGrid.querySelectorAll('td[data-slot-id]').forEach(function(cell) {
      // Remove old listeners by cloning
      var newCell = cell.cloneNode(true);
      cell.parentNode.replaceChild(newCell, cell);

      // Add new listener
      newCell.addEventListener('click', function() {
        selectSlotAndSubmit(this);
      });
      newCell.addEventListener('keydown', function(event) {
        if (event.key === 'Enter' || event.key === ' ') {
          selectSlotAndSubmit(this);
          event.preventDefault();
        }
      });
    });
  }

  const modal = new bootstrap.Modal(document.getElementById('assignModal'));
  modal.show();
}
```

### Step 6: Remove old slot select change handler from init()

In `init()`, remove or comment out the old `assignSlotSelect` change handler since we're no longer using a select:

```javascript
// Remove this section:
// const assignSlotSelect = document.getElementById('assign-modal-slot-select');
// if (assignSlotSelect) { ... }
```

Also remove the `assignFromTable` button handler:
```javascript
// Remove this section:
// const assignFromTableBtn = document.getElementById('assign-from-table-btn');
// if (assignFromTableBtn) { ... }
```

### Step 7: Run test to verify it passes

```bash
uv run pytest tests/browser/test_shuttle_assignment.py::TestShuttleAssignmentDashboard::test_assign_modal_shows_grid_picker -v
```

Expected: PASS

### Step 8: Run all tests

```bash
uv run pytest tests/browser/test_shuttle_assignment.py -v
```

Expected: All tests PASS

### Step 9: Run full test suite

```bash
make test
```

Expected: All tests PASS

### Step 10: Run lint and type check

```bash
make lint-fix && make lint && make type-check
```

### Step 11: Commit

```bash
git add wafer_space/shuttles/templates/shuttles/assignment_dashboard.html wafer_space/shuttles/static/shuttles/js/assignment_dashboard.js tests/browser/test_shuttle_assignment.py
git commit -m "$(cat <<'EOF'
feat: replace assign modal dropdown with grid picker

- Reuse _grid.html partial in assign modal
- Click slot to assign directly (no separate button)
- Occupied slots show alert when clicked
- Size mismatch confirmation before assignment

Closes #161

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Final Verification

### Step 1: Run full test suite

```bash
make test
```

### Step 2: Run all quality checks

```bash
make check-all
```

### Step 3: Review changes

```bash
git log --oneline feature/slot-assignment-improvements ^main
git diff main..feature/slot-assignment-improvements --stat
```

---

## Summary

| Task | Description | Key Files |
|------|-------------|-----------|
| 1 | Add Owner column | views.py, template |
| 2 | Add Mfg column to summary | views.py, template |
| 3 | Grid manufacturing indicators | template, CSS |
| 4 | Column sorting | template, JS |
| 5 | Reusable grid partial | _grid.html, JS |
| 6 | Autocomplete dropdown | views.py, template, JS, CSS |
| 7 | Grid picker in assign modal | template, JS |

All tasks include tests, lint checks, and incremental commits following TDD principles.
