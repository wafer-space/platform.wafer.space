# Project List Shuttle/State Columns Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two fixed-width columns to the left of each row on `/projects/` — the assigned shuttle number (e.g. G801) and a colour-coded project status badge.

**Architecture:** The page stays a Bootstrap list-group; each `list-group-item` becomes a flex row with two `flex-shrink-0` cells (shuttle, status) before the existing content. The status badge lives in a new shared partial `_status_badge.html` used by both the list and detail pages. `ProjectListView` gains `select_related` to avoid N+1 queries.

**Tech Stack:** Django 5.2 templates (Bootstrap 5), pytest-django, factory-boy, djlint (via pre-commit), ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-07-16-project-list-columns-design.md`

**Branch:** `feature/project-list-status-columns` (already created; spec committed there).

**Repo conventions that apply here:**

- Before every commit: `make lint-fix && make lint && make type-check` plus the targeted tests. `make lint` does NOT run djlint — templates must go through `uv run pre-commit run --files <files>` or CI reformats them.
- Never suppress lint errors (`# noqa`, `# type: ignore`) without explicit user permission.
- Shuttle tests must pass an explicit `name=` to `ShuttleFactory` — the auto-sequence can collide with the migration-seeded G801 shuttle.
- End commit messages with the Co-Authored-By / Claude-Session trailers used in this session.

---

### Task 1: Shared status badge partial + detail page switch

The detail page (`project_detail.html:81-83`) renders the status badge with an inline `{% if %}` chain. Extract it into a partial so the list page can reuse it. This is behaviour-preserving for the detail page (the `text-wrap` class only takes effect when the badge is width-constrained, which it is not on the detail page).

**Files:**
- Create: `wafer_space/templates/projects/_status_badge.html`
- Modify: `wafer_space/templates/projects/project_detail.html:79-84`

- [ ] **Step 1: Create the partial**

Create `wafer_space/templates/projects/_status_badge.html`:

```html
{% comment %}
Colour-coded project status badge.
Usage: {% include "projects/_status_badge.html" with project=project %}
{% endcomment %}
<span class="badge text-wrap {% if project.status == 'draft' %}bg-secondary{% elif project.status == 'submitted' %}bg-primary{% elif project.status == 'manufacturable' %}bg-success{% elif project.status == 'not_manufacturable' %}bg-danger{% else %}bg-info{% endif %}">
  {{ project.get_status_display }}
</span>
```

The colour mapping is copied exactly from `project_detail.html:81` (draft=secondary, submitted=primary, manufacturable=success, not_manufacturable=danger, everything else=info). `text-wrap` overrides Bootstrap's default `white-space: nowrap` on badges so long labels ("Checking Manufacturability") can wrap inside the fixed-width list column.

- [ ] **Step 2: Use the partial in the detail page**

In `wafer_space/templates/projects/project_detail.html`, replace lines 79–84:

```html
                <p class="mb-2">
                  <strong>Status:</strong>
                  <span class="badge {% if project.status == 'draft' %}bg-secondary{% elif project.status == 'submitted' %}bg-primary{% elif project.status == 'manufacturable' %}bg-success{% elif project.status == 'not_manufacturable' %}bg-danger{% else %}bg-info{% endif %}">
                    {{ project.get_status_display }}
                  </span>
                </p>
```

with:

```html
                <p class="mb-2">
                  <strong>Status:</strong>
                  {% include "projects/_status_badge.html" with project=project %}
                </p>
```

- [ ] **Step 3: Run the detail-view tests to confirm no regression**

Run: `uv run pytest wafer_space/projects/tests/test_views.py -k "Detail" -v`
Expected: all PASS (behaviour-preserving refactor).

- [ ] **Step 4: Run djlint on the touched templates**

Run: `uv run pre-commit run --files wafer_space/templates/projects/_status_badge.html wafer_space/templates/projects/project_detail.html`
Expected: all hooks pass (djlint may reformat; if it does, it exits non-zero — re-run until clean and keep the reformatted output).

- [ ] **Step 5: Commit**

```bash
git add wafer_space/templates/projects/_status_badge.html wafer_space/templates/projects/project_detail.html
git commit -m "refactor(projects): extract status badge into shared partial"
```

---

### Task 2: List-view tests for the new columns (TDD — write failing tests first)

**Files:**
- Modify: `wafer_space/projects/tests/test_views.py:138-159` (replace two tests, add two)

The two existing tests assert the old `submitted_at`-derived badge markup (`title="Submitted for manufacturing"` / `title="Not submitted for manufacturing"`), which the new design removes.

- [ ] **Step 1: Replace the two indicator tests and add shuttle/status tests**

In `wafer_space/projects/tests/test_views.py`, replace `test_shows_submitted_indicator` (lines 138–149) and `test_shows_not_submitted_indicator` (lines 151–159) with:

```python
    def test_shows_submitted_status_badge(self):
        """Submitted projects show the Submitted status badge column."""
        self.project1.status = Project.Status.SUBMITTED
        self.project1.submitted_at = timezone.now()
        self.project1.save()
        self.client.login(username="testuser", password=TEST_PASSWORD)

        response = self.client.get(reverse("projects:list"))

        assert response.status_code == HTTP_OK
        content = response.content.decode()
        assert "Submitted" in content
        assert "bg-primary" in content

    def test_shows_draft_status_badge(self):
        """Draft projects show the Draft status badge column."""
        self.client.login(username="testuser", password=TEST_PASSWORD)

        response = self.client.get(reverse("projects:list"))

        assert response.status_code == HTTP_OK
        content = response.content.decode()
        assert "Draft" in content
        assert 'title="Not submitted for manufacturing"' not in content

    def test_shows_full_status_display_name(self):
        """The status column uses the full status field, not just Draft/Submitted."""
        self.project1.status = Project.Status.MANUFACTURABLE
        self.project1.save()
        self.client.login(username="testuser", password=TEST_PASSWORD)

        response = self.client.get(reverse("projects:list"))

        assert response.status_code == HTTP_OK
        content = response.content.decode()
        assert "Manufacturable" in content
        assert "bg-success" in content

    def test_shows_shuttle_name_when_assigned(self):
        """Projects assigned to a shuttle show the shuttle name column."""
        shuttle = ShuttleFactory(name="G850")
        ProjectFactory(
            user=self.user,
            name="Shuttle Project",
            shuttle=shuttle,
            project_id="TST1",
        )
        self.client.login(username="testuser", password=TEST_PASSWORD)

        response = self.client.get(reverse("projects:list"))

        assert response.status_code == HTTP_OK
        content = response.content.decode()
        assert "G850" in content
```

Add the import to the top-of-file import block (its sorted position is after `from wafer_space.shuttles.models import ShuttleSlot`, line 25; `make lint-fix` will fix placement if needed):

```python
from wafer_space.shuttles.tests.factories import ShuttleFactory
```

Notes:
- `ShuttleFactory(name="G850")` — explicit name per repo convention (migration-seeded G801 collision).
- `shuttle` is a core field set at creation via the factory, which is allowed; only post-creation mutation is restricted.
- Do NOT touch `test_packaging_badges_use_consistent_color` (lines 120–136): its `"bg-info" not in content` and `count("badge bg-secondary") >= 2` assertions still hold — both listed projects are drafts, whose new status badges are also `bg-secondary`.

- [ ] **Step 2: Run the new tests to verify they fail for the right reason**

Run: `uv run pytest wafer_space/projects/tests/test_views.py::TestProjectListView -v`
Expected: `test_shows_draft_status_badge` FAILS (old template still renders `title="Not submitted for manufacturing"`); `test_shows_full_status_display_name` FAILS ("Manufacturable" not rendered anywhere). `test_shows_submitted_status_badge` and `test_shows_shuttle_name_when_assigned` may pass incidentally ("Submitted"/"bg-primary" appear in the old badge markup; no strict column assertion) — that is acceptable; the two hard failures prove the template work is needed.

- [ ] **Step 3: Commit the failing tests**

```bash
git add wafer_space/projects/tests/test_views.py
git commit -m "test(projects): expect shuttle and status columns in project list"
```

---

### Task 3: List template columns + view select_related

**Files:**
- Modify: `wafer_space/templates/projects/project_list.html:33-71`
- Modify: `wafer_space/projects/views.py:63-77` (`ProjectListView.get_queryset`)

- [ ] **Step 1: Add select_related to the list queryset**

In `wafer_space/projects/views.py`, `ProjectListView.get_queryset`, change both return statements:

```python
        if user.is_staff:
            # Staff users see all projects
            return (
                Project.objects.all()
                .select_related("user", "shuttle")
                .order_by("-created_at")
            )

        # Regular users see only their own projects
        return (
            Project.objects.filter(user=user)
            .select_related("user", "shuttle")
            .order_by("-created_at")
        )
```

(`user` is added to the regular branch too: the template compares `project.user == request.user` per row, which otherwise triggers one query per project.)

- [ ] **Step 2: Rewrite the list-group item as a flex row**

In `wafer_space/templates/projects/project_list.html`, replace lines 34–71 (the `{% for %}` loop body) with:

```html
            {% for project in projects %}
              <div class="list-group-item list-group-item-action position-relative d-flex">
                <div class="flex-shrink-0 pe-2" style="width: 4.5rem">
                  {% if project.shuttle %}<span class="fw-semibold">{{ project.shuttle.name }}</span>{% endif %}
                </div>
                <div class="flex-shrink-0 pe-3" style="width: 9rem">
                  {% include "projects/_status_badge.html" with project=project %}
                </div>
                <div class="flex-grow-1">
                  <div class="d-flex w-100 justify-content-between">
                    <h5 class="mb-1">
                      <a href="{% url 'projects:detail' pk=project.pk %}"
                         class="stretched-link text-decoration-none text-reset">{{ project.name }}</a>
                      {% if project.user == request.user %}
                        <span class="badge bg-success ms-2">Your Project</span>
                      {% else %}
                        <span class="badge bg-info ms-2">{{ project.user.username }}'s Project</span>
                      {% endif %}
                      {% include "projects/_packaging_badge.html" with project=project %}
                    </h5>
                    <div class="text-end ms-3 text-nowrap">
                      <small class="text-muted d-block">{{ project.created_at|date:"M d, Y" }}</small>
                      {% if project.crowd_supply_order_id %}
                        <small>
                          <a href="{{ project.crowd_supply_order_url }}"
                             target="_blank"
                             rel="noopener"
                             class="position-relative"
                             style="z-index: 2"
                             title="CrowdSupply order {{ project.crowd_supply_order_id }}">
                            <i class="bi bi-box-arrow-up-right"></i> CS# {{ project.crowd_supply_order_id }}
                          </a>
                        </small>
                      {% endif %}
                    </div>
                  </div>
                  {% if project.description %}<p class="mb-1">{{ project.description|truncatewords:30 }}</p>{% endif %}
                </div>
              </div>
            {% endfor %}
```

Changes from the original loop body:
1. The item root gains `d-flex`; two fixed-width `flex-shrink-0` cells (shuttle 4.5rem, status 9rem) come first; the old content is wrapped in a `flex-grow-1` div.
2. The old inline Draft/Submitted badge (original lines 46–51, keyed on `project.submitted_at`) is **removed** — the status column replaces it.
3. Everything else (ownership badge, packaging badge, date, CS# link with its `z-index: 2` escape, description) is unchanged. The `stretched-link` still covers the whole item because the new cells are inside the same `position-relative` container.

- [ ] **Step 3: Run the list-view tests**

Run: `uv run pytest wafer_space/projects/tests/test_views.py::TestProjectListView -v`
Expected: all PASS, including the four new/replaced tests and the untouched `test_packaging_badges_use_consistent_color`.

- [ ] **Step 4: Run djlint on the template**

Run: `uv run pre-commit run --files wafer_space/templates/projects/project_list.html`
Expected: hooks pass (accept any djlint reformatting, re-run until clean). If djlint reformatted the template, re-run the Step 3 tests once more to confirm they still pass.

- [ ] **Step 5: Commit**

```bash
git add wafer_space/templates/projects/project_list.html wafer_space/projects/views.py
git commit -m "feat(projects): add shuttle and status columns to project list"
```

---

### Task 4: Full verification

- [ ] **Step 1: Run the mandatory pre-commit pipeline**

Run: `make lint-fix && make lint && make type-check`
Expected: all clean. Fix root causes of any failure — never suppress.

- [ ] **Step 2: Run the full test suite (unit + headless browser)**

Run: `make test`
Expected: PASS. Known flake: `test_tos_version_displayed` browser test is flaky on main — re-run before assuming this change broke it.

- [ ] **Step 3: Visual smoke check**

Start `make runserver` (port 8081), open `http://localhost:8081/projects/` with the Playwright MCP browser, and confirm: shuttle column shows a name for an assigned project and is empty otherwise; status badges render with correct colours; rows are still fully clickable; take a screenshot for the PR. Stop the server afterwards. (Restart the server if templates were edited after it started — the cached template loader needs the autoreloader, and `--noreload` caches templates.)

- [ ] **Step 4: Commit any remaining fixes and push**

If the working tree is dirty (e.g. djlint reformats from Step 1), commit those fixes first. Then:

```bash
git push origin feature/project-list-status-columns
```

Then create the PR (title: "Add shuttle and status columns to the projects list"), body referencing the spec and screenshot, ending with the standard generated-with footer.
