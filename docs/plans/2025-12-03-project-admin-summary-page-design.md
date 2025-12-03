# Project Admin Summary Page Design

**Date:** 2025-12-03
**Status:** Approved

## Overview

A staff-only summary page displaying all projects in a sortable table with no pagination.

## Requirements

- **Access:** Staff users only (`is_staff=True`)
- **URL:** `/projects/admin/summary/`
- **Display:** All projects in a single page (no pagination)
- **Sorting:** Server-side via `?sort=column` query parameter

## Table Columns

| Column | Source | Sortable |
|--------|--------|----------|
| Project ID | `project.full_id` (G801XYYY format) | Yes |
| Size | `project.get_slot_size_display` | Yes |
| Name | `project.name` | Yes |
| Owner | `project.user.username` | Yes |
| Email | `project.user.email` | Yes |
| Precheck Status | `manufacturability_check.get_status_display` | Yes |
| Manufacturable | `manufacturability_check.is_manufacturable` | Yes |

### Column Display Details

**Project ID:**
- Format: `{shuttle.name}{project_id}` (e.g., "G801ABCD")
- Shows "-" if no shuttle/project_id assigned

**Size:**
- Human-readable via `get_slot_size_display`
- Examples: "Full Slot (1x1)", "Half Width (0.5x1)"

**Precheck Status:**
- Values: Pending, Dispatched, Running, Finished, Error, Cancelled
- Shows "-" if no check exists

**Manufacturable:**
- `True` → ✓ (green)
- `False` → ✗ (red)
- `None` → -

## Technical Implementation

### View

```python
class ProjectAdminSummaryView(LoginRequiredMixin, UserPassesTestMixin, ListView):
    template_name = "projects/admin_summary.html"
    context_object_name = "projects"

    def test_func(self):
        return self.request.user.is_staff
```

### Query Optimization

```python
Project.objects.select_related("user", "shuttle").prefetch_related(
    Prefetch(
        "files",
        queryset=ProjectFile.objects.filter(is_active=True)
            .select_related("manufacturability_check"),
        to_attr="active_files"
    )
)
```

### Sorting

- Default: `full_id` ascending
- Toggle: clicking same header switches ascending/descending
- Query param: `?sort=name` or `?sort=-name` (prefix `-` for descending)
- Sort indicators: ▲ (ascending) / ▼ (descending)

### Sort Field Mappings

| Column | Database Sort |
|--------|--------------|
| Project ID | `shuttle__name`, `project_id` |
| Size | `slot_size` |
| Name | `name` |
| Owner | `user__username` |
| Email | `user__email` |
| Precheck Status | Annotation on `manufacturability_check__status` |
| Manufacturable | Annotation on `manufacturability_check__is_manufacturable` |

### URL Pattern

```python
path("admin/summary/", ProjectAdminSummaryView.as_view(), name="admin_summary"),
```

## Template Structure

- Extends `base.html`
- Uses Bootstrap table styling (`table table-striped`)
- Clickable headers with sort indicators
- Empty state: "No projects found."
