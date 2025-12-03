# Project Admin Summary Page Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a staff-only summary page at `/projects/admin/summary/` displaying all projects in a sortable table.

**Architecture:** Django ListView with server-side sorting via query parameters. Uses `select_related` and `Prefetch` for optimized queries. Template uses Bootstrap table styling with clickable headers.

**Tech Stack:** Django 5.2, pytest-django, factory-boy

---

## Task 1: Create Basic View Test

**Files:**
- Create: `wafer_space/projects/tests/test_views_admin_summary.py`

**Step 1: Write the failing test for view access**

```python
"""Tests for ProjectAdminSummaryView."""

import pytest
from django.urls import reverse

from wafer_space.projects.tests.factories import ProjectFactory
from wafer_space.users.tests.factories import UserFactory


@pytest.mark.django_db
class TestProjectAdminSummaryView:
    """Tests for the admin summary view."""

    def test_staff_can_access(self, client):
        """Staff users can access the summary page."""
        staff_user = UserFactory(is_staff=True)
        client.force_login(staff_user)

        response = client.get(reverse("projects:admin_summary"))

        assert response.status_code == 200

    def test_non_staff_cannot_access(self, client):
        """Non-staff users are forbidden."""
        regular_user = UserFactory(is_staff=False)
        client.force_login(regular_user)

        response = client.get(reverse("projects:admin_summary"))

        assert response.status_code == 403

    def test_anonymous_redirected_to_login(self, client):
        """Anonymous users are redirected to login."""
        response = client.get(reverse("projects:admin_summary"))

        assert response.status_code == 302
        assert "/accounts/login/" in response.url
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/projects/tests/test_views_admin_summary.py -v`
Expected: FAIL with "NoReverseMatch" (URL doesn't exist yet)

**Step 3: Commit the failing test**

```bash
git add wafer_space/projects/tests/test_views_admin_summary.py
git commit -m "test: add failing tests for admin summary view access"
```

---

## Task 2: Create View and URL

**Files:**
- Modify: `wafer_space/projects/views.py`
- Modify: `wafer_space/projects/urls.py`

**Step 1: Add the view class**

In `wafer_space/projects/views.py`, add import at top with other imports:

```python
from django.contrib.auth.mixins import UserPassesTestMixin
```

Then add the view class (after the existing admin views, around line 400+):

```python
class ProjectAdminSummaryView(LoginRequiredMixin, UserPassesTestMixin, ListView):
    """Staff-only summary of all projects with sortable columns."""

    template_name = "projects/admin_summary.html"
    context_object_name = "projects"

    def test_func(self):
        """Only staff users can access this view."""
        return self.request.user.is_staff

    def get_queryset(self):
        """Return all projects with optimized queries."""
        return Project.objects.select_related("user", "shuttle").all()
```

**Step 2: Add URL pattern**

In `wafer_space/projects/urls.py`, add the import and URL pattern.

Add to imports:
```python
from .views import ProjectAdminSummaryView
```

Add URL pattern (after the existing `admin/check-status/` path):
```python
    path("admin/summary/", ProjectAdminSummaryView.as_view(), name="admin_summary"),
```

**Step 3: Create minimal template**

Create `wafer_space/templates/projects/admin_summary.html`:

```html
{% extends "base.html" %}

{% block title %}Project Summary{% endblock %}

{% block content %}
<h1>Project Summary</h1>
<p>{{ projects|length }} projects</p>
{% endblock %}
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest wafer_space/projects/tests/test_views_admin_summary.py -v`
Expected: All 3 tests PASS

**Step 5: Run linting**

Run: `make lint-fix && make lint && make type-check`
Expected: No errors

**Step 6: Commit**

```bash
git add wafer_space/projects/views.py wafer_space/projects/urls.py wafer_space/templates/projects/admin_summary.html
git commit -m "feat: add ProjectAdminSummaryView with staff-only access"
```

---

## Task 3: Add Test for Table Content

**Files:**
- Modify: `wafer_space/projects/tests/test_views_admin_summary.py`

**Step 1: Add test for table columns**

Add to the test class:

```python
    def test_displays_project_data(self, client):
        """Summary page displays project data in table."""
        staff_user = UserFactory(is_staff=True)
        # Create a project with known data
        owner = UserFactory(username="testowner", email="owner@example.com")
        project = ProjectFactory(
            name="Test Project",
            user=owner,
            slot_size="1x1",
        )
        client.force_login(staff_user)

        response = client.get(reverse("projects:admin_summary"))

        assert response.status_code == 200
        content = response.content.decode()
        assert "Test Project" in content
        assert "testowner" in content
        assert "owner@example.com" in content
        assert "1x1" in content

    def test_displays_all_projects(self, client):
        """Summary page shows all projects, not just user's own."""
        staff_user = UserFactory(is_staff=True)
        other_user = UserFactory()
        ProjectFactory(name="Staff Project", user=staff_user)
        ProjectFactory(name="Other Project", user=other_user)
        client.force_login(staff_user)

        response = client.get(reverse("projects:admin_summary"))

        content = response.content.decode()
        assert "Staff Project" in content
        assert "Other Project" in content
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/projects/tests/test_views_admin_summary.py::TestProjectAdminSummaryView::test_displays_project_data -v`
Expected: FAIL (table content not in template yet)

**Step 3: Commit the failing test**

```bash
git add wafer_space/projects/tests/test_views_admin_summary.py
git commit -m "test: add failing tests for summary table content"
```

---

## Task 4: Implement Table Template

**Files:**
- Modify: `wafer_space/templates/projects/admin_summary.html`

**Step 1: Update template with full table**

Replace content of `wafer_space/templates/projects/admin_summary.html`:

```html
{% extends "base.html" %}

{% block title %}Project Summary{% endblock %}

{% block content %}
<div class="container-fluid mt-4">
  <h1>Project Summary</h1>
  <p class="text-muted">{{ projects|length }} project{{ projects|length|pluralize }}</p>

  <table class="table table-striped table-hover">
    <thead class="table-light">
      <tr>
        <th>Project ID</th>
        <th>Size</th>
        <th>Name</th>
        <th>Owner</th>
        <th>Email</th>
        <th>Precheck Status</th>
        <th>Manufacturable</th>
      </tr>
    </thead>
    <tbody>
      {% for project in projects %}
      <tr>
        <td>{{ project.full_id|default:"-" }}</td>
        <td>{{ project.slot_size }}</td>
        <td>{{ project.name }}</td>
        <td>{{ project.user.username }}</td>
        <td>{{ project.user.email }}</td>
        <td>-</td>
        <td>-</td>
      </tr>
      {% empty %}
      <tr>
        <td colspan="7" class="text-center text-muted">No projects found.</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
```

**Step 2: Run tests to verify they pass**

Run: `uv run pytest wafer_space/projects/tests/test_views_admin_summary.py -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add wafer_space/templates/projects/admin_summary.html
git commit -m "feat: add table displaying project data"
```

---

## Task 5: Add Precheck Status to Query

**Files:**
- Modify: `wafer_space/projects/views.py`
- Modify: `wafer_space/templates/projects/admin_summary.html`
- Modify: `wafer_space/projects/tests/test_views_admin_summary.py`

**Step 1: Add test for precheck status display**

Add to the test class in `test_views_admin_summary.py`:

```python
    def test_displays_precheck_status(self, client):
        """Summary page displays manufacturability check status."""
        from wafer_space.projects.models import ManufacturabilityCheck
        from wafer_space.projects.tests.factories import ProjectFileFactory

        staff_user = UserFactory(is_staff=True)
        project = ProjectFactory(name="Checked Project")
        # Create active file with manufacturability check
        project_file = ProjectFileFactory(project=project, is_active=True)
        ManufacturabilityCheck.objects.create(
            project=project,
            project_file=project_file,
            status="FINISHED",
            is_manufacturable=True,
        )
        client.force_login(staff_user)

        response = client.get(reverse("projects:admin_summary"))

        content = response.content.decode()
        assert "Finished" in content
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/projects/tests/test_views_admin_summary.py::TestProjectAdminSummaryView::test_displays_precheck_status -v`
Expected: FAIL (status not displayed yet)

**Step 3: Update view with prefetch**

In `wafer_space/projects/views.py`, update `get_queryset` method:

```python
    def get_queryset(self):
        """Return all projects with optimized queries."""
        from django.db.models import Prefetch

        from wafer_space.projects.models import ProjectFile

        return Project.objects.select_related("user", "shuttle").prefetch_related(
            Prefetch(
                "files",
                queryset=ProjectFile.objects.filter(is_active=True).select_related(
                    "manufacturability_check"
                ),
                to_attr="active_files",
            )
        )
```

**Step 4: Update template to display precheck status**

In `wafer_space/templates/projects/admin_summary.html`, update the table body:

```html
    <tbody>
      {% for project in projects %}
      <tr>
        <td>{{ project.full_id|default:"-" }}</td>
        <td>{{ project.slot_size }}</td>
        <td>{{ project.name }}</td>
        <td>{{ project.user.username }}</td>
        <td>{{ project.user.email }}</td>
        {% with active_file=project.active_files.0 %}
          {% if active_file and active_file.manufacturability_check %}
            <td>{{ active_file.manufacturability_check.get_status_display }}</td>
            <td>
              {% if active_file.manufacturability_check.is_manufacturable is True %}
                <span class="text-success">✓</span>
              {% elif active_file.manufacturability_check.is_manufacturable is False %}
                <span class="text-danger">✗</span>
              {% else %}
                -
              {% endif %}
            </td>
          {% else %}
            <td>-</td>
            <td>-</td>
          {% endif %}
        {% endwith %}
      </tr>
      {% empty %}
      <tr>
        <td colspan="7" class="text-center text-muted">No projects found.</td>
      </tr>
      {% endfor %}
    </tbody>
```

**Step 5: Run tests to verify they pass**

Run: `uv run pytest wafer_space/projects/tests/test_views_admin_summary.py -v`
Expected: All tests PASS

**Step 6: Commit**

```bash
git add wafer_space/projects/views.py wafer_space/templates/projects/admin_summary.html wafer_space/projects/tests/test_views_admin_summary.py
git commit -m "feat: display precheck status and manufacturability"
```

---

## Task 6: Add Sorting - Tests

**Files:**
- Modify: `wafer_space/projects/tests/test_views_admin_summary.py`

**Step 1: Add sorting tests**

Add to the test class:

```python
    def test_default_sort_by_name(self, client):
        """Default sort is by name ascending."""
        staff_user = UserFactory(is_staff=True)
        ProjectFactory(name="Zebra Project")
        ProjectFactory(name="Alpha Project")
        client.force_login(staff_user)

        response = client.get(reverse("projects:admin_summary"))

        content = response.content.decode()
        alpha_pos = content.find("Alpha Project")
        zebra_pos = content.find("Zebra Project")
        assert alpha_pos < zebra_pos, "Alpha should appear before Zebra"

    def test_sort_by_name_descending(self, client):
        """Sort by name descending with -name parameter."""
        staff_user = UserFactory(is_staff=True)
        ProjectFactory(name="Zebra Project")
        ProjectFactory(name="Alpha Project")
        client.force_login(staff_user)

        response = client.get(reverse("projects:admin_summary") + "?sort=-name")

        content = response.content.decode()
        alpha_pos = content.find("Alpha Project")
        zebra_pos = content.find("Zebra Project")
        assert zebra_pos < alpha_pos, "Zebra should appear before Alpha"

    def test_sort_by_owner(self, client):
        """Sort by owner username."""
        staff_user = UserFactory(is_staff=True)
        user_a = UserFactory(username="alice")
        user_z = UserFactory(username="zack")
        ProjectFactory(name="Zack Project", user=user_z)
        ProjectFactory(name="Alice Project", user=user_a)
        client.force_login(staff_user)

        response = client.get(reverse("projects:admin_summary") + "?sort=owner")

        content = response.content.decode()
        alice_pos = content.find("Alice Project")
        zack_pos = content.find("Zack Project")
        assert alice_pos < zack_pos, "Alice's project should appear first"

    def test_sort_indicator_in_header(self, client):
        """Current sort column shows indicator."""
        staff_user = UserFactory(is_staff=True)
        client.force_login(staff_user)

        response = client.get(reverse("projects:admin_summary") + "?sort=name")

        content = response.content.decode()
        # Should have ascending indicator on name column
        assert "▲" in content or "sort=-name" in content
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest wafer_space/projects/tests/test_views_admin_summary.py::TestProjectAdminSummaryView::test_default_sort_by_name -v`
Expected: FAIL (no sorting implemented yet)

**Step 3: Commit failing tests**

```bash
git add wafer_space/projects/tests/test_views_admin_summary.py
git commit -m "test: add failing tests for table sorting"
```

---

## Task 7: Implement Sorting Logic

**Files:**
- Modify: `wafer_space/projects/views.py`

**Step 1: Add sorting to get_queryset**

Update the view in `wafer_space/projects/views.py`:

```python
class ProjectAdminSummaryView(LoginRequiredMixin, UserPassesTestMixin, ListView):
    """Staff-only summary of all projects with sortable columns."""

    template_name = "projects/admin_summary.html"
    context_object_name = "projects"

    SORT_FIELDS = {
        "full_id": ("shuttle__name", "project_id"),
        "size": ("slot_size",),
        "name": ("name",),
        "owner": ("user__username",),
        "email": ("user__email",),
    }
    DEFAULT_SORT = "name"

    def test_func(self):
        """Only staff users can access this view."""
        return self.request.user.is_staff

    def get_sort_params(self):
        """Parse sort parameter and return (field, descending)."""
        sort = self.request.GET.get("sort", self.DEFAULT_SORT)
        descending = sort.startswith("-")
        field = sort.lstrip("-")
        if field not in self.SORT_FIELDS:
            field = self.DEFAULT_SORT
            descending = False
        return field, descending

    def get_queryset(self):
        """Return all projects with optimized queries and sorting."""
        from django.db.models import Prefetch

        from wafer_space.projects.models import ProjectFile

        qs = Project.objects.select_related("user", "shuttle").prefetch_related(
            Prefetch(
                "files",
                queryset=ProjectFile.objects.filter(is_active=True).select_related(
                    "manufacturability_check"
                ),
                to_attr="active_files",
            )
        )

        field, descending = self.get_sort_params()
        order_fields = self.SORT_FIELDS[field]
        if descending:
            order_fields = tuple(f"-{f}" for f in order_fields)
        return qs.order_by(*order_fields)

    def get_context_data(self, **kwargs):
        """Add sort information to context."""
        context = super().get_context_data(**kwargs)
        field, descending = self.get_sort_params()
        context["current_sort"] = field
        context["sort_descending"] = descending
        return context
```

**Step 2: Run tests to verify they pass**

Run: `uv run pytest wafer_space/projects/tests/test_views_admin_summary.py -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add wafer_space/projects/views.py
git commit -m "feat: add server-side sorting for summary table"
```

---

## Task 8: Add Sortable Headers to Template

**Files:**
- Modify: `wafer_space/templates/projects/admin_summary.html`

**Step 1: Update template with clickable headers**

Replace the template content:

```html
{% extends "base.html" %}

{% block title %}Project Summary{% endblock %}

{% block content %}
<div class="container-fluid mt-4">
  <h1>Project Summary</h1>
  <p class="text-muted">{{ projects|length }} project{{ projects|length|pluralize }}</p>

  <table class="table table-striped table-hover">
    <thead class="table-light">
      <tr>
        <th>
          <a href="?sort={% if current_sort == 'full_id' and not sort_descending %}-{% endif %}full_id" class="text-decoration-none text-dark">
            Project ID
            {% if current_sort == 'full_id' %}{% if sort_descending %}▼{% else %}▲{% endif %}{% endif %}
          </a>
        </th>
        <th>
          <a href="?sort={% if current_sort == 'size' and not sort_descending %}-{% endif %}size" class="text-decoration-none text-dark">
            Size
            {% if current_sort == 'size' %}{% if sort_descending %}▼{% else %}▲{% endif %}{% endif %}
          </a>
        </th>
        <th>
          <a href="?sort={% if current_sort == 'name' and not sort_descending %}-{% endif %}name" class="text-decoration-none text-dark">
            Name
            {% if current_sort == 'name' %}{% if sort_descending %}▼{% else %}▲{% endif %}{% endif %}
          </a>
        </th>
        <th>
          <a href="?sort={% if current_sort == 'owner' and not sort_descending %}-{% endif %}owner" class="text-decoration-none text-dark">
            Owner
            {% if current_sort == 'owner' %}{% if sort_descending %}▼{% else %}▲{% endif %}{% endif %}
          </a>
        </th>
        <th>
          <a href="?sort={% if current_sort == 'email' and not sort_descending %}-{% endif %}email" class="text-decoration-none text-dark">
            Email
            {% if current_sort == 'email' %}{% if sort_descending %}▼{% else %}▲{% endif %}{% endif %}
          </a>
        </th>
        <th>Precheck Status</th>
        <th>Manufacturable</th>
      </tr>
    </thead>
    <tbody>
      {% for project in projects %}
      <tr>
        <td>{{ project.full_id|default:"-" }}</td>
        <td>{{ project.slot_size }}</td>
        <td>{{ project.name }}</td>
        <td>{{ project.user.username }}</td>
        <td>{{ project.user.email }}</td>
        {% with active_file=project.active_files.0 %}
          {% if active_file and active_file.manufacturability_check %}
            <td>{{ active_file.manufacturability_check.get_status_display }}</td>
            <td>
              {% if active_file.manufacturability_check.is_manufacturable is True %}
                <span class="text-success">✓</span>
              {% elif active_file.manufacturability_check.is_manufacturable is False %}
                <span class="text-danger">✗</span>
              {% else %}
                -
              {% endif %}
            </td>
          {% else %}
            <td>-</td>
            <td>-</td>
          {% endif %}
        {% endwith %}
      </tr>
      {% empty %}
      <tr>
        <td colspan="7" class="text-center text-muted">No projects found.</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
```

**Step 2: Run all tests**

Run: `uv run pytest wafer_space/projects/tests/test_views_admin_summary.py -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add wafer_space/templates/projects/admin_summary.html
git commit -m "feat: add clickable sort headers with indicators"
```

---

## Task 9: Final Verification

**Step 1: Run full test suite**

Run: `make test`
Expected: All tests pass

**Step 2: Run linting and type checking**

Run: `make lint-fix && make lint && make type-check`
Expected: No errors

**Step 3: Manual verification (optional)**

Run: `make runserver`
Visit: `http://localhost:8081/projects/admin/summary/`
Verify: Table displays, sorting works, staff-only access

**Step 4: Final commit if any fixes needed**

If any fixes were made, commit them.

---

## Summary

| Task | Description | Tests |
|------|-------------|-------|
| 1 | Create access control tests | 3 tests |
| 2 | Create view, URL, minimal template | - |
| 3 | Add table content tests | 2 tests |
| 4 | Implement full table template | - |
| 5 | Add precheck status display | 1 test |
| 6 | Add sorting tests | 4 tests |
| 7 | Implement sorting logic | - |
| 8 | Add sortable headers | - |
| 9 | Final verification | - |

**Total new tests:** ~10 tests
**Files created:** 2 (test file, template)
**Files modified:** 2 (views.py, urls.py)
