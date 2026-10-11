# G800 permanent test shuttle (#221) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A shuttle flag `is_test_only` that keeps a shuttle open to users for
ever, labels it "Test only" everywhere, and refuses it in slot assignment,
manifests, reticle packages and grid generation (#221; Tim, issues-10).

**Architecture:**
- One BooleanField on `Shuttle`; the code reads only the flag, never the name.
- The closed rule from PR #365 (`is_open_to_users`, `open_to_users`) treats a
  test-only shuttle as open.
- Each exclusion fails loud in the model, service or command that does the
  work. Display goes through the existing `shuttles/_shuttle_state.html`.

**Tech Stack:** Django 5.2, pytest-django, factory-boy, Selenium browser tests,
uv, ruff, mypy, djlint.

**Spec:** `docs/superpowers/specs/2026-10-11-g800-test-shuttle-design.md`
(approved by the coordinator, 11 Oct 2026, with its Statistics section).

Executed inline by [desktop - ws-platform:6 dates]; no sub-agent build.

## Global Constraints

- Field: `is_test_only = models.BooleanField(default=False,
  verbose_name="Test only", help_text="Designs are checked but never
  manufactured; never in manifests, reticle packages or slot assignment.")`.
- Refusal wording: `"<name> is a test-only shuttle; its projects are never
  placed in slots"` (reserve), `"<name> is a test-only shuttle; it has no
  manifest"` (manifest), `"<name> is a test-only shuttle; it has no reticle
  package"` (package), `"<name> is a test-only shuttle; it has no grid"`
  (grid command).
- Badge words: "Test only", with title and visually-hidden text "Designs are
  checked but never manufactured".
- Form label: `"<name> - <description> (test only, not manufactured)"`.
- Submit success on a test-only shuttle: `"Submitted on <name> (test only):
  checked, not manufactured"`.
- Dashboard notice: `"<name> is test only: no slot assignment"`.
- Rows are never created in migrations. Tests use explicit shuttle names in
  G880 to G899 (ShuttleFactory's sequence collides with seeded rows).

## Review Focus

- A test-only shuttle whose status is not open (e.g. someone sets it to
  completed in the admin) must still be open to users; covered by the rule
  table in Task 1.
- A staff user posting directly to the assign endpoint for a G800 slot that
  exists (e.g. a grid generated before the flag was set) gets a 400 naming
  the reason; Task 2.
- `generate_package` on a test-only shuttle must not leave an output
  directory behind; Task 2.
- The project form for a user when G800 is the only open shuttle: G800 is
  offered, nothing is pre-selected silently as a real run; Task 3.
- The admin summary's "N projects" headline must agree with the counts below
  it, and still say how many test-only projects the table shows; Task 4.

---

### Task 1: The flag and the rule

**Files:**
- Modify: `wafer_space/shuttles/models.py` (field after `status`;
  `ShuttleQuerySet.open_to_users`; `Shuttle.is_open_to_users`)
- Create: `wafer_space/shuttles/migrations/0013_shuttle_is_test_only.py`
  (`makemigrations`; schema only)
- Modify: `wafer_space/shuttles/admin.py` (`is_test_only` after `status` in
  the first fieldset, in `list_display` and `list_filter`)
- Test: `wafer_space/shuttles/tests/test_closed_rule.py`

**Interfaces:** Produces `Shuttle.is_test_only: bool`. Later tasks read only
this.

- [ ] Step 1: add test-only rows to the rule table: a separate
  `TEST_ONLY_CASES` list (every `Shuttle.Status`, deadline None and
  `NOW - SECOND`), all expected open, parametrised through the same
  instance/queryset agreement test with `is_test_only=True`.
- [ ] Step 2: run `uv run pytest wafer_space/shuttles/tests/test_closed_rule.py`;
  expect failures (unexpected keyword `is_test_only`).
- [ ] Step 3: add the field, then:

```python
return self.filter(
    Q(is_test_only=True)
    | (
        Q(status=Shuttle.Status.OPEN)
        & (Q(submission_deadline__isnull=True) | Q(submission_deadline__gt=moment))
    )
)
```

and in `is_open_to_users`, `if self.is_test_only: return True` before the
status check (docstring names #221). `uv run python manage.py makemigrations
shuttles -n shuttle_is_test_only`.
- [ ] Step 4: tests pass; `closed_reason` stays None for test-only (one test).
- [ ] Step 5: gate, commit.

### Task 2: Exclusions

**Files:**
- Modify: `wafer_space/shuttles/models.py` (`ShuttleSlot.reserve` first
  check; `Shuttle.generate_manifest` first line)
- Modify: `wafer_space/shuttles/services/reticle_package.py`
  (`generate_package`, after the lookup, before `mkdir`)
- Modify: `wafer_space/shuttles/management/commands/generate_shuttle_grid.py`
  (`_get_shuttle` raises `CommandError`)
- Test: `wafer_space/shuttles/tests/test_test_only_shuttle.py` (new)

- [ ] Step 1: tests:
  - `reserve` on a slot of a test-only shuttle (slot made directly with
    `ShuttleSlot.objects.create`) raises `ValueError` with the wording; the
    slot stays available.
  - `AssignProjectView` POST for that slot as staff returns 400 and the
    message in `error`.
  - `generate_manifest()` raises `ValueError`.
  - `generate_package("G890", out)` raises `ReticlePackageError` and `out`
    does not exist afterwards.
  - `call_command("generate_shuttle_grid", "G890")` raises `CommandError`.
- [ ] Step 2: run; expect failures.
- [ ] Step 3: implement each check (`msg = ...; raise ...`, EM rules).
- [ ] Step 4: tests pass.
- [ ] Step 5: gate, commit.

### Task 3: Project form

**Files:**
- Modify: `wafer_space/projects/forms.py` (`_set_defaults` excludes
  test-only; a `ModelChoiceField` subclass `ShuttleChoiceField` with
  `label_from_instance`)
- Test: `wafer_space/projects/tests/test_forms_test_only_shuttle.py` (new)

- [ ] Step 1: tests (non-staff user):
  - with G891 test-only open and G892 real open, G891 is in the queryset and
    the initial is G892;
  - with only G891 open, G891 is offered and `initial` is None;
  - the choice label for G891 ends "(test only, not manufactured)"; G892's
    label is `str(shuttle)` unchanged.
- [ ] Step 2: run; expect failures.
- [ ] Step 3: implement:

```python
class ShuttleChoiceField(forms.ModelChoiceField):
    """Shuttle choices; a test-only shuttle says so in its label (#221)."""

    def label_from_instance(self, obj: Shuttle) -> str:
        label = str(obj)
        if obj.is_test_only:
            return f"{label} (test only, not manufactured)"
        return label
```

and `.filter(is_test_only=False)` in the default pick.
- [ ] Step 4: tests pass, plus the existing form tests.
- [ ] Step 5: gate, commit.

### Task 4: Display, dashboard notice, submit message, summary counts

**Files:**
- Modify: `wafer_space/shuttles/templates/shuttles/_shuttle_state.html`
- Modify: `wafer_space/shuttles/templates/shuttles/assignment_dashboard.html`
  (`{% if shuttle.is_test_only %}` notice in place of the summary and grid
  row)
- Modify: `wafer_space/projects/views.py` (`ProjectSubmitView.post` message;
  `ProjectAdminSummaryView.get_context_data` passes only real-shuttle
  projects to `_compute_summary_stats` and sets `test_only_count`)
- Modify: `wafer_space/templates/projects/admin_summary.html` (headline adds
  "plus N test only"; the full-id cell adds a "Test only" badge)
- Test: `wafer_space/shuttles/tests/test_shuttle_state_display.py`,
  `wafer_space/projects/tests/test_views_admin_summary.py`, a submit test in
  `wafer_space/projects/tests/test_closed_shuttle_views.py`

- [ ] Step 1: tests:
  - "Test only" on the shuttle list, detail and assignment pages (staff),
    the project detail page and the edit form (owner);
  - the assignment page for a test-only shuttle shows the notice and no
    `grid-table`;
  - submit on a test-only project with a manufacturable file sets
    `submitted_file` and shows the test-only message;
  - admin summary with one G893 (real) and one G894 (test-only) project:
    `summary["total"] == 1`, `test_only_count == 1`, both rows listed.
- [ ] Step 2: run; expect failures.
- [ ] Step 3: implement; `uv run pre-commit run --files` the templates.
- [ ] Step 4: tests pass.
- [ ] Step 5: gate, commit.

### Task 5: Browser test and runbook

**Files:**
- Create: `tests/browser/test_projects/test_test_only_shuttle.py` (owner
  creates a project picking the "(test only, not manufactured)" choice and
  sees "Test only" on the project page)
- Modify: `docs/shuttle_creation.md` (a G800 section: create, check, undo)

- [ ] Step 1: browser test, run, pass.
- [ ] Step 2: runbook section; run its create, check and undo scripts with
  `manage.py shell` against the worktree's dev database; the output matches
  the document; run create twice to show it is idempotent.
- [ ] Step 3: gate, commit.

### After the tasks

Playwright walk-through with screenshots on branch
`assets/pr-NNN-screenshots`, PR, independent Sonnet review, CI, then the sha
to the coordinator with "contains origin/main".
