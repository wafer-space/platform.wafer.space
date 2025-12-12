# Status Metadata Refactor - Consistent Check Status Display

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Centralize ManufacturabilityCheck status presentation metadata in the model, eliminating duplicated if/elif chains across 5 templates and ensuring consistent colors, icons, and labels site-wide.

**Architecture:** Add a `StatusMeta` dataclass and `_STATUS_METADATA` dict to the `ManufacturabilityCheck.Status` enum. Provide model properties (`status_color`, `status_icon`, `status_label`, `status_show_spinner`) and a `status_badge_html()` method that returns complete badge markup. Update all templates to use these methods instead of hardcoded conditionals.

**Tech Stack:** Django 5.2+, Python dataclasses, Django templates, Bootstrap 5

**Issue:** #185 (expanded scope: consistency + all active states)

---

## Phase 1: Add Status Metadata to Model

### Task 1: Create StatusMeta Dataclass and Metadata Dict

**Files:**
- Modify: `wafer_space/projects/models.py` (around line 1289)

**Step 1: Write the test for status metadata**

Create test file for the new functionality:

```python
# wafer_space/projects/tests/test_status_metadata.py
"""Tests for ManufacturabilityCheck status metadata."""

import pytest

from wafer_space.projects.models import ManufacturabilityCheck


class TestStatusMetadata:
    """Tests for status metadata completeness and consistency."""

    def test_all_statuses_have_metadata(self):
        """Every status choice must have metadata defined."""
        for status_value, _label in ManufacturabilityCheck.Status.choices:
            meta = ManufacturabilityCheck.Status.get_metadata(status_value)
            assert meta is not None, f"Missing metadata for status: {status_value}"
            assert "color" in meta, f"Missing 'color' for status: {status_value}"
            assert "icon" in meta, f"Missing 'icon' for status: {status_value}"
            assert "label" in meta, f"Missing 'label' for status: {status_value}"
            assert "show_spinner" in meta, f"Missing 'show_spinner' for: {status_value}"

    def test_colors_are_valid_bootstrap(self):
        """Colors must be valid Bootstrap contextual colors."""
        valid_colors = {"primary", "secondary", "success", "danger", "warning", "info"}
        for status_value, _label in ManufacturabilityCheck.Status.choices:
            meta = ManufacturabilityCheck.Status.get_metadata(status_value)
            assert meta["color"] in valid_colors, (
                f"Invalid color '{meta['color']}' for status: {status_value}"
            )

    def test_icons_are_bootstrap_icons(self):
        """Icons must be valid Bootstrap icon classes."""
        for status_value, _label in ManufacturabilityCheck.Status.choices:
            meta = ManufacturabilityCheck.Status.get_metadata(status_value)
            # Icons should start with "bi-" or be empty for spinner-only
            icon = meta["icon"]
            assert icon == "" or icon.startswith("bi-"), (
                f"Invalid icon '{icon}' for status: {status_value}"
            )

    def test_show_spinner_is_boolean(self):
        """show_spinner must be a boolean."""
        for status_value, _label in ManufacturabilityCheck.Status.choices:
            meta = ManufacturabilityCheck.Status.get_metadata(status_value)
            assert isinstance(meta["show_spinner"], bool), (
                f"show_spinner must be bool for status: {status_value}"
            )
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest wafer_space/projects/tests/test_status_metadata.py -v
```

Expected: FAIL with `AttributeError: type object 'Status' has no attribute 'get_metadata'`

**Step 3: Commit the failing test**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/tests/test_status_metadata.py
git commit -m "test: add failing tests for status metadata"
```

---

### Task 2: Implement StatusMeta and get_metadata()

**Files:**
- Modify: `wafer_space/projects/models.py` (add after Status class definition, around line 1299)

**Step 1: Add the metadata implementation**

Add this inside the `ManufacturabilityCheck` class, after the `Status` enum definition:

```python
    # Status presentation metadata for consistent rendering across templates
    # Maps status values to their display properties
    _STATUS_METADATA: ClassVar[dict[str, dict[str, str | bool]]] = {
        Status.PENDING: {
            "color": "warning",
            "icon": "bi-clock",
            "label": "Pending",
            "show_spinner": False,
        },
        Status.DISPATCHING: {
            "color": "info",
            "icon": "bi-send",
            "label": "Dispatching",
            "show_spinner": True,
        },
        Status.STARTING: {
            "color": "info",
            "icon": "bi-box-arrow-up",
            "label": "Starting",
            "show_spinner": True,
        },
        Status.RUNNING: {
            "color": "primary",
            "icon": "",  # Spinner only
            "label": "Running",
            "show_spinner": True,
        },
        Status.ANALYZING: {
            "color": "primary",
            "icon": "",  # Spinner only
            "label": "Analyzing",
            "show_spinner": True,
        },
        Status.FINISHED: {
            "color": "success",
            "icon": "bi-check-circle",
            "label": "Finished",
            "show_spinner": False,
        },
        Status.ERROR: {
            "color": "danger",
            "icon": "bi-exclamation-triangle",
            "label": "Error",
            "show_spinner": False,
        },
        Status.CANCELLING: {
            "color": "warning",
            "icon": "bi-x-circle",
            "label": "Cancelling",
            "show_spinner": True,
        },
        Status.CANCELLED: {
            "color": "secondary",
            "icon": "bi-x-circle",
            "label": "Cancelled",
            "show_spinner": False,
        },
    }

    @classmethod
    def get_status_metadata(cls, status: str) -> dict[str, str | bool]:
        """Return presentation metadata for a status value.

        Args:
            status: A status value (e.g., 'pending', 'running')

        Returns:
            Dict with keys: color, icon, label, show_spinner
        """
        return cls._STATUS_METADATA.get(
            status,
            {
                "color": "secondary",
                "icon": "",
                "label": status.title(),
                "show_spinner": False,
            },
        )
```

Also update the test to use `ManufacturabilityCheck.get_status_metadata()` instead of `Status.get_metadata()`.

**Step 2: Run test to verify it passes**

```bash
uv run pytest wafer_space/projects/tests/test_status_metadata.py -v
```

Expected: PASS

**Step 3: Commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/models.py wafer_space/projects/tests/test_status_metadata.py
git commit -m "feat: add status metadata dict to ManufacturabilityCheck"
```

---

### Task 3: Add Instance Properties for Status Metadata

**Files:**
- Modify: `wafer_space/projects/models.py`
- Modify: `wafer_space/projects/tests/test_status_metadata.py`

**Step 1: Write tests for instance properties**

Add to the test file:

```python
class TestStatusProperties:
    """Tests for ManufacturabilityCheck status properties."""

    @pytest.fixture
    def pending_check(self):
        """Create a check in pending status."""
        from wafer_space.projects.tests.factories import ManufacturabilityCheckFactory

        return ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )

    @pytest.fixture
    def running_check(self):
        """Create a check in running status."""
        from wafer_space.projects.tests.factories import ManufacturabilityCheckFactory

        return ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING
        )

    @pytest.mark.django_db
    def test_status_color_property(self, pending_check):
        """status_color returns the Bootstrap color for current status."""
        assert pending_check.status_color == "warning"

    @pytest.mark.django_db
    def test_status_icon_property(self, pending_check):
        """status_icon returns the Bootstrap icon class for current status."""
        assert pending_check.status_icon == "bi-clock"

    @pytest.mark.django_db
    def test_status_label_property(self, pending_check):
        """status_label returns the human-readable label."""
        assert pending_check.status_label == "Pending"

    @pytest.mark.django_db
    def test_status_show_spinner_false(self, pending_check):
        """status_show_spinner returns False for non-active statuses."""
        assert pending_check.status_show_spinner is False

    @pytest.mark.django_db
    def test_status_show_spinner_true(self, running_check):
        """status_show_spinner returns True for active statuses."""
        assert running_check.status_show_spinner is True
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest wafer_space/projects/tests/test_status_metadata.py::TestStatusProperties -v
```

Expected: FAIL with `AttributeError: 'ManufacturabilityCheck' object has no attribute 'status_color'`

**Step 3: Implement the properties**

Add to `ManufacturabilityCheck` class:

```python
    @property
    def status_color(self) -> str:
        """Return Bootstrap color for current status (e.g., 'primary', 'warning')."""
        meta = self.get_status_metadata(self.status)
        return str(meta["color"])

    @property
    def status_icon(self) -> str:
        """Return Bootstrap icon class for current status (e.g., 'bi-clock')."""
        meta = self.get_status_metadata(self.status)
        return str(meta["icon"])

    @property
    def status_label(self) -> str:
        """Return human-readable label for current status."""
        meta = self.get_status_metadata(self.status)
        return str(meta["label"])

    @property
    def status_show_spinner(self) -> bool:
        """Return True if current status should display a spinner."""
        meta = self.get_status_metadata(self.status)
        return bool(meta["show_spinner"])
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest wafer_space/projects/tests/test_status_metadata.py -v
```

Expected: PASS

**Step 5: Commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/models.py wafer_space/projects/tests/test_status_metadata.py
git commit -m "feat: add status_color, status_icon, status_label, status_show_spinner properties"
```

---

### Task 4: Add status_badge_html() Method

**Files:**
- Modify: `wafer_space/projects/models.py`
- Modify: `wafer_space/projects/tests/test_status_metadata.py`

**Step 1: Write tests for badge HTML generation**

Add to the test file:

```python
class TestStatusBadgeHtml:
    """Tests for status_badge_html() method."""

    @pytest.fixture
    def pending_check(self):
        """Create a check in pending status."""
        from wafer_space.projects.tests.factories import ManufacturabilityCheckFactory

        return ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )

    @pytest.fixture
    def running_check(self):
        """Create a check in running status."""
        from wafer_space.projects.tests.factories import ManufacturabilityCheckFactory

        return ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING
        )

    @pytest.mark.django_db
    def test_badge_includes_color_class(self, pending_check):
        """Badge HTML includes Bootstrap color class."""
        html = pending_check.status_badge_html()
        assert "bg-warning" in html

    @pytest.mark.django_db
    def test_badge_includes_icon(self, pending_check):
        """Badge HTML includes icon when defined."""
        html = pending_check.status_badge_html()
        assert "bi-clock" in html

    @pytest.mark.django_db
    def test_badge_includes_label(self, pending_check):
        """Badge HTML includes status label."""
        html = pending_check.status_badge_html()
        assert "Pending" in html

    @pytest.mark.django_db
    def test_badge_includes_spinner_when_active(self, running_check):
        """Badge HTML includes spinner for active statuses."""
        html = running_check.status_badge_html()
        assert "spinner-border" in html

    @pytest.mark.django_db
    def test_badge_no_spinner_when_inactive(self, pending_check):
        """Badge HTML excludes spinner for inactive statuses."""
        html = pending_check.status_badge_html()
        assert "spinner-border" not in html

    @pytest.mark.django_db
    def test_badge_is_marked_safe(self, pending_check):
        """Badge HTML is marked safe for template rendering."""
        from django.utils.safestring import SafeString

        html = pending_check.status_badge_html()
        assert isinstance(html, SafeString)
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest wafer_space/projects/tests/test_status_metadata.py::TestStatusBadgeHtml -v
```

Expected: FAIL with `AttributeError: 'ManufacturabilityCheck' object has no attribute 'status_badge_html'`

**Step 3: Implement status_badge_html()**

Add to `ManufacturabilityCheck` class:

```python
    def status_badge_html(self) -> str:
        """Return complete Bootstrap badge HTML for current status.

        Returns:
            SafeString containing badge HTML, safe for template rendering.

        Example output:
            <span class="badge bg-warning"><i class="bi-clock"></i> Pending</span>
        """
        from django.utils.html import format_html
        from django.utils.safestring import mark_safe

        color = self.status_color
        icon = self.status_icon
        label = self.status_label
        show_spinner = self.status_show_spinner

        # Build icon/spinner HTML
        if show_spinner:
            icon_html = (
                '<span class="spinner-border spinner-border-sm" '
                'role="status" aria-hidden="true"></span>'
            )
        elif icon:
            icon_html = f'<i class="{icon}"></i>'
        else:
            icon_html = ""

        # Add text-dark class for warning background (better contrast)
        text_class = " text-dark" if color == "warning" else ""

        # Combine into badge
        if icon_html:
            badge_html = (
                f'<span class="badge bg-{color}{text_class}">'
                f"{icon_html} {label}</span>"
            )
        else:
            badge_html = f'<span class="badge bg-{color}{text_class}">{label}</span>'

        return mark_safe(badge_html)
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest wafer_space/projects/tests/test_status_metadata.py -v
```

Expected: PASS

**Step 5: Run full test suite**

```bash
make lint-fix && make lint && make type-check && make test
```

Expected: All tests pass

**Step 6: Commit**

```bash
git add wafer_space/projects/models.py wafer_space/projects/tests/test_status_metadata.py
git commit -m "feat: add status_badge_html() method for consistent badge rendering"
```

---

## Phase 2: Update Templates to Use Model Methods

### Task 5: Update _manufacturability_check.html

**Files:**
- Modify: `wafer_space/templates/projects/_manufacturability_check.html`

**Step 1: Replace the status badge if/elif chain (lines 9-70)**

Replace the entire status badge section with:

```django
{# Status badge - uses model method for consistency #}
<p class="mb-2">
  <strong>Status:</strong>
  {{ check.status_badge_html }}
  {# Cancel button for in-progress checks #}
  {% if check.is_cancellable %}
    <form method="post"
          action="{% url 'projects:cancel_check' pk=check.project.pk check_id=check.pk %}"
          class="d-inline ms-2"
          onsubmit="return confirm('Are you sure you want to cancel this manufacturability check?');">
      {% csrf_token %}
      <button type="submit" class="btn btn-sm btn-outline-danger">
        <i class="bi bi-x-circle"></i> Cancel
      </button>
    </form>
  {% endif %}
</p>
```

**Note:** The FINISHED status has special logic (manufacturable vs not, warnings). We need to handle this. Update the `status_badge_html()` method OR add a separate method for detailed badges. For now, keep the FINISHED special case in the template:

```django
{# Status badge - uses model method for consistency #}
<p class="mb-2">
  <strong>Status:</strong>
  {% if check.status == 'finished' %}
    {# Finished has special display based on result #}
    {% if check.is_manufacturable %}
      {% if check.warnings %}
        <span class="badge bg-warning text-dark">
          <i class="bi bi-exclamation-triangle"></i> Manufacturable with Warnings
        </span>
      {% else %}
        <span class="badge bg-success">
          <i class="bi bi-check-circle"></i> Manufacturable - Clean
        </span>
      {% endif %}
    {% else %}
      <span class="badge bg-danger">
        <i class="bi bi-x-circle"></i> Not Manufacturable
      </span>
    {% endif %}
  {% else %}
    {{ check.status_badge_html }}
  {% endif %}
  {# Cancel button for in-progress checks #}
  {% if check.is_cancellable %}
    <form method="post"
          action="{% url 'projects:cancel_check' pk=check.project.pk check_id=check.pk %}"
          class="d-inline ms-2"
          onsubmit="return confirm('Are you sure you want to cancel this manufacturability check?');">
      {% csrf_token %}
      <button type="submit" class="btn btn-sm btn-outline-danger">
        <i class="bi bi-x-circle"></i> Cancel
      </button>
    </form>
  {% endif %}
</p>
```

**Step 2: Run tests**

```bash
make lint-fix && make test
```

Expected: All tests pass

**Step 3: Commit**

```bash
git add wafer_space/templates/projects/_manufacturability_check.html
git commit -m "refactor: use status_badge_html in _manufacturability_check.html"
```

---

### Task 6: Update _file_badges.html

**Files:**
- Modify: `wafer_space/templates/projects/_file_badges.html`

**Step 1: Replace manufacturability check badge section (lines 10-41)**

Replace with:

```django
{# Manufacturability check status badge (most relevant) #}
{% with check=file.latest_manufacturability_check %}
  {% if check %}
    {% if check.status == 'finished' %}
      {# Finished has special display based on result #}
      {% if check.is_manufacturable %}
        <span class="badge bg-success">
          <i class="bi bi-check-circle"></i> Manufacturable
        </span>
      {% else %}
        <span class="badge bg-danger">
          <i class="bi bi-x-circle"></i> Not Manufacturable
        </span>
      {% endif %}
    {% else %}
      {{ check.status_badge_html }}
    {% endif %}
  {% endif %}
{% endwith %}
```

**Step 2: Run tests**

```bash
make lint-fix && make test
```

**Step 3: Commit**

```bash
git add wafer_space/templates/projects/_file_badges.html
git commit -m "refactor: use status_badge_html in _file_badges.html"
```

---

### Task 7: Update _file_display.html

**Files:**
- Modify: `wafer_space/templates/projects/_file_display.html`

**Step 1: Replace card header badge (around line 162)**

Replace the status badge in the card header with model method usage.

**Step 2: Replace history section badge (around line 219)**

Replace the history badge rendering with model method usage.

**Step 3: Run tests**

```bash
make lint-fix && make test
```

**Step 4: Commit**

```bash
git add wafer_space/templates/projects/_file_display.html
git commit -m "refactor: use status_badge_html in _file_display.html"
```

---

### Task 8: Update manufacturability_check_status.html - Recent Table

**Files:**
- Modify: `wafer_space/templates/projects/manufacturability_check_status.html`

**Step 1: Replace recent checks table status badges (lines 173-204)**

Replace with:

```django
<td>{{ check.status_badge_html }}</td>
```

**Step 2: Run tests**

```bash
make lint-fix && make test
```

**Step 3: Commit**

```bash
git add wafer_space/templates/projects/manufacturability_check_status.html
git commit -m "refactor: use status_badge_html in admin status recent table"
```

---

## Phase 3: Add Active Status Sections to Admin Page

### Task 9: Create Active Sections Configuration

**Files:**
- Modify: `wafer_space/projects/views.py`

**Step 1: Write test for active sections context**

Add to `wafer_space/projects/tests/test_views_admin_summary.py`:

```python
def test_check_status_includes_active_sections(self):
    """Test that active status sections are included in context."""
    response = self.client.get(self.url)

    assert response.status_code == 200
    assert "active_sections" in response.context

    # Should have sections for all active statuses
    sections = response.context["active_sections"]
    status_values = [s["status"] for s in sections]
    assert "running" in status_values
    assert "dispatching" in status_values
    assert "starting" in status_values
    assert "analyzing" in status_values
    assert "pending" in status_values
    assert "cancelling" in status_values
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest wafer_space/projects/tests/test_views_admin_summary.py -v -k active_sections
```

**Step 3: Implement active_sections in view**

Update `ManufacturabilityCheckAdminStatusView.get()` to build active sections:

```python
def get(self, request):
    """Display manufacturability check status dashboard."""
    # Get counts by status
    status_counts = {}
    for status_value, status_label in ManufacturabilityCheck.Status.choices:
        count = ManufacturabilityCheck.objects.filter(status=status_value).count()
        status_counts[status_value] = {
            "label": status_label,
            "count": count,
        }

    # Get recent checks (last 50)
    recent_checks = ManufacturabilityCheck.objects.select_related(
        "project",
        "project__user",
        "project_file",
    ).order_by("-id")[:50]

    # Build active sections - one for each non-terminal status
    # Order: Running first (most important), then by workflow order
    active_status_order = [
        ManufacturabilityCheck.Status.RUNNING,
        ManufacturabilityCheck.Status.ANALYZING,
        ManufacturabilityCheck.Status.STARTING,
        ManufacturabilityCheck.Status.DISPATCHING,
        ManufacturabilityCheck.Status.PENDING,
        ManufacturabilityCheck.Status.CANCELLING,
    ]

    active_sections = []
    for status in active_status_order:
        checks = (
            ManufacturabilityCheck.objects.filter(status=status)
            .select_related(
                "project",
                "project__user",
                "project_file",
            )
            .order_by("-created_at")
        )
        if checks.exists():
            meta = ManufacturabilityCheck.get_status_metadata(status)
            active_sections.append({
                "status": status,
                "label": meta["label"],
                "color": meta["color"],
                "icon": meta["icon"],
                "show_spinner": meta["show_spinner"],
                "checks": checks,
                "count": checks.count(),
            })

    return render(
        request,
        "projects/manufacturability_check_status.html",
        {
            "status_counts": status_counts,
            "recent_checks": recent_checks,
            "active_sections": active_sections,
        },
    )
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest wafer_space/projects/tests/test_views_admin_summary.py -v -k active_sections
```

**Step 5: Commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/views.py wafer_space/projects/tests/test_views_admin_summary.py
git commit -m "feat: add active_sections context to admin check status view"
```

---

### Task 10: Update Template to Use Active Sections Loop

**Files:**
- Modify: `wafer_space/templates/projects/manufacturability_check_status.html`

**Step 1: Replace hardcoded RUNNING and PENDING sections with loop**

Replace lines 31-145 (the Running Checks and Pending Checks sections) with:

```django
{# Active Status Sections - generated from active_sections context #}
{% for section in active_sections %}
  <div class="card mb-4 border-{{ section.color }}">
    <div class="card-header bg-{{ section.color }}{% if section.color == 'warning' %} text-dark{% else %} text-white{% endif %}">
      <h5 class="mb-0">
        {% if section.show_spinner %}
          <span class="spinner-border spinner-border-sm me-2"
                role="status"
                aria-hidden="true"></span>
        {% elif section.icon %}
          <i class="{{ section.icon }}"></i>
        {% endif %}
        {{ section.label }} ({{ section.count }})
      </h5>
    </div>
    <div class="card-body">
      <div class="table-responsive">
        <table class="table table-striped table-hover mb-0">
          <thead>
            <tr>
              <th>Project</th>
              <th>User</th>
              <th>File</th>
              <th>Created</th>
              <th>Waiting</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {% for check in section.checks %}
              <tr>
                <td>
                  <a href="{% url 'projects:detail' pk=check.project.pk %}">{{ check.project.name }}</a>
                </td>
                <td>{{ check.project.user.username }}</td>
                <td>
                  {% if check.project_file %}
                    <code>{{ check.project_file.processed_filename|default:check.project_file.original_filename }}</code>
                  {% else %}
                    <span class="text-muted">-</span>
                  {% endif %}
                </td>
                <td>{{ check.created_at|date:"Y-m-d H:i:s" }}</td>
                <td>{{ check.created_at|timesince }}</td>
                <td>
                  <a href="{% url 'admin:projects_manufacturabilitycheck_change' check.pk %}"
                     class="btn btn-sm btn-outline-secondary">
                    <i class="bi bi-pencil"></i>
                  </a>
                </td>
              </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>
  </div>
{% empty %}
  <div class="alert alert-info">
    <i class="bi bi-info-circle"></i> No checks currently in progress.
  </div>
{% endfor %}
```

**Step 2: Run tests**

```bash
make lint-fix && make test
```

**Step 3: Commit**

```bash
git add wafer_space/templates/projects/manufacturability_check_status.html
git commit -m "feat: replace hardcoded sections with active_sections loop

Shows all active statuses (RUNNING, ANALYZING, STARTING, DISPATCHING, PENDING, CANCELLING)
with consistent styling from model metadata.

Closes #185"
```

---

## Phase 4: Final Verification

### Task 11: Full Test Suite and Manual Verification

**Step 1: Run all quality checks**

```bash
make check-all
```

Expected: All checks pass

**Step 2: Verify visual consistency**

The admin status page should now show sections for ALL active statuses (when checks exist in those states), in this order:
1. Running (primary/blue, spinner)
2. Analyzing (primary/blue, spinner)
3. Starting (info/cyan, spinner)
4. Dispatching (info/cyan, spinner)
5. Pending (warning/yellow, clock icon)
6. Cancelling (warning/yellow, spinner)

**Step 3: Create PR or merge**

Use `superpowers:finishing-a-development-branch` skill to complete the work.

---

## Summary

| Phase | Task | Description | Files Changed |
|-------|------|-------------|---------------|
| 1 | 1 | Create test for status metadata | `test_status_metadata.py` |
| 1 | 2 | Implement `_STATUS_METADATA` dict | `models.py` |
| 1 | 3 | Add instance properties | `models.py`, `test_status_metadata.py` |
| 1 | 4 | Add `status_badge_html()` method | `models.py`, `test_status_metadata.py` |
| 2 | 5 | Update `_manufacturability_check.html` | template |
| 2 | 6 | Update `_file_badges.html` | template |
| 2 | 7 | Update `_file_display.html` | template |
| 2 | 8 | Update admin recent table | template |
| 3 | 9 | Add `active_sections` to view | `views.py`, tests |
| 3 | 10 | Replace hardcoded sections with loop | template |
| 4 | 11 | Final verification | - |

## Consistency Achieved

After this refactor:
- **Single source of truth**: All colors, icons, labels defined in `_STATUS_METADATA`
- **Consistent everywhere**: `status_badge_html()` used across all templates
- **All active states visible**: Admin page shows RUNNING, ANALYZING, STARTING, DISPATCHING, PENDING, CANCELLING
- **Easy to maintain**: Adding a new status = add one entry to metadata dict
- **Testable**: Unit tests verify all statuses have required metadata
