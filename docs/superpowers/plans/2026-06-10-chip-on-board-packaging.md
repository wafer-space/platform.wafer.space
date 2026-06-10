# Chip-on-Board (CoB) Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users request Chip-on-Board (CoB) packaging on a project; the manufacturability precheck then runs with `--cob`, and toggling the option re-runs the check.

**Architecture:** One new editable boolean on `Project` (`chip_on_board`), read live by the precheck command builder (like `--slot`/`--id`). Toggling it creates a new PENDING `ManufacturabilityCheck` via a new model method `create_check_cob_change()` (modelled on `create_check_drc_update()`), which explicitly cancels an in-progress check. Existing scheduled pollers (`checks_pending`, `checks_cancelling`, `checks_cleanup_orphaned_docker`) do all the async work — no new tasks, no layering changes.

**Tech Stack:** Django 5.2, pytest-django + factory-boy, Celery (PostgreSQL broker), crispy-forms templates, ruff/mypy/djlint.

**Spec:** `docs/superpowers/specs/2026-06-08-chip-on-board-packaging-design.md` — read it first.

---

## Before you start

- **Rebase gate:** the spec assumes PR #262 (`checks_cleanup_superseded`) lands first. Run `git fetch origin main` and check `git log --oneline origin/main | head -5`. If PR #262 has merged, `git rebase origin/main` before starting. If it has NOT merged yet, stop and ask the user whether to proceed anyway (the design works either way, but docstrings written in Task 3 reference the post-#262 world).
- Work in the worktree `.worktrees/feature/chip-on-board-packaging`, branch `feature/chip-on-board-packaging`.
- **Pre-commit gate for EVERY commit** (project rule, no shortcuts): `make lint-fix && make lint && make type-check && make test`. Baseline today: 1283 passed, 3 skipped.
- TDD throughout: write the failing test, watch it fail, implement, watch it pass. See @superpowers:test-driven-development.
- All new code needs type hints; never add `# noqa` / `# type: ignore`.

## File map

| File | Change |
|------|--------|
| `wafer_space/projects/models.py` | Add `Project.chip_on_board` field + `USER_FIELDS` entry; add `TriggerReason.COB_CHANGE`; add `ManufacturabilityCheck.create_check_cob_change()` |
| `wafer_space/projects/migrations/0056_*.py`, `0057_*.py` | Generated migrations (field, then choices) |
| `wafer_space/projects/tasks_checks.py` | Append `--cob` in `do_starting` command builder |
| `wafer_space/projects/forms.py` | Add `chip_on_board` to `ProjectForm.Meta` (fields/widgets/help_texts) |
| `wafer_space/templates/projects/project_form.html` | Render the checkbox (fields are rendered explicitly — adding to `Meta.fields` alone does NOT display it) |
| `wafer_space/projects/views.py` | `ProjectUpdateView.form_valid`: create re-check when the flag changes |
| `wafer_space/templates/projects/project_detail.html` | CoB badge |
| Tests | `wafer_space/projects/tests/test_models.py`, `test_tasks.py`, `test_forms.py`, `test_views.py` |

---

### Task 1: `Project.chip_on_board` field + migration

**Files:**
- Modify: `wafer_space/projects/models.py` (field after `is_public` ~line 244; `USER_FIELDS` ~line 159)
- Create: `wafer_space/projects/migrations/0056_project_chip_on_board.py` (generated)
- Test: `wafer_space/projects/tests/test_models.py`

- [ ] **Step 1: Write the failing tests**

Add near the other Project model test classes in `test_models.py` (follow the file's existing import style — `Project`, `ProjectFactory` are already imported):

```python
@pytest.mark.django_db
class TestProjectChipOnBoard:
    """Tests for the Project.chip_on_board flag."""

    def test_defaults_to_false(self):
        """chip_on_board defaults to False."""
        project = ProjectFactory()
        assert project.chip_on_board is False

    def test_is_editable_after_creation(self):
        """chip_on_board is a user field, not blocked by core-field immutability."""
        project = ProjectFactory()
        project.chip_on_board = True
        project.full_clean()  # core-field immutability is enforced in clean()
        project.save()
        project.refresh_from_db()
        assert project.chip_on_board is True

    def test_is_a_user_field(self):
        """chip_on_board is in USER_FIELDS and not in CORE_FIELDS."""
        assert "chip_on_board" in Project.USER_FIELDS
        assert "chip_on_board" not in Project.CORE_FIELDS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestProjectChipOnBoard -v`
Expected: 3 FAILED — `AttributeError` / `AssertionError` (no `chip_on_board` attribute).

- [ ] **Step 3: Add the field and USER_FIELDS entry**

In `models.py`, add `"chip_on_board"` to the `USER_FIELDS` frozenset (alongside `"is_public"`). Then add the field directly after the `is_public` field definition (~line 244):

```python
    # Chip-on-Board packaging (Issue #259)
    chip_on_board = models.BooleanField(
        default=False,
        verbose_name="Request Chip-on-Board (CoB) packaging",
        help_text=(
            "Run extra Chip-on-Board (CoB) compatibility checks during the "
            "manufacturability precheck."
        ),
    )
```

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations projects`
Expected: one new migration adding `chip_on_board` to `project` (latest existing migration is `0055_add_commit_info_to_precheck_revision.py`). Inspect the generated file — it must contain exactly one `AddField` for `project.chip_on_board`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestProjectChipOnBoard -v`
Expected: 3 PASSED.

- [ ] **Step 6: Pre-commit gate + commit**

```bash
make lint-fix && make lint && make type-check && make test
git add wafer_space/projects/models.py wafer_space/projects/migrations/ wafer_space/projects/tests/test_models.py
git commit -m "feat: add Project.chip_on_board field (#259)"
```

---

### Task 2: `TriggerReason.COB_CHANGE` + migration

**Files:**
- Modify: `wafer_space/projects/models.py:1549-1553` (`TriggerReason`)
- Create: `wafer_space/projects/migrations/0057_*.py` (generated `AlterField` for choices)
- Test: `wafer_space/projects/tests/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db
class TestCobChangeTriggerReason:
    """Tests for the COB_CHANGE trigger reason."""

    def test_cob_change_choice_exists(self):
        """COB_CHANGE is a valid TriggerReason."""
        reason = ManufacturabilityCheck.TriggerReason.COB_CHANGE
        assert reason.value == "cob_change"
        assert reason.label == "Chip-on-Board Option Changed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestCobChangeTriggerReason -v`
Expected: FAIL with `AttributeError: COB_CHANGE`.

- [ ] **Step 3: Add the choice**

In `models.py`, extend `ManufacturabilityCheck.TriggerReason` (after `RETRY`):

```python
        COB_CHANGE = "cob_change", "Chip-on-Board Option Changed"
```

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations projects`
Expected: one migration with an `AlterField` on `manufacturabilitycheck.trigger_reason` (choices-only change; the project's migration history does this for status choices in `0053`).

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestCobChangeTriggerReason -v`
Expected: PASS.

- [ ] **Step 6: Pre-commit gate + commit**

```bash
make lint-fix && make lint && make type-check && make test
git add wafer_space/projects/models.py wafer_space/projects/migrations/ wafer_space/projects/tests/test_models.py
git commit -m "feat: add COB_CHANGE manufacturability trigger reason (#259)"
```

---

### Task 3: `ManufacturabilityCheck.create_check_cob_change()`

**Files:**
- Modify: `wafer_space/projects/models.py` (add method directly after `create_check_drc_update`, which ends ~line 2341)
- Test: `wafer_space/projects/tests/test_models.py` (add after `TestCreateCheckDrcUpdate`, ~line 3091, and reuse its imports: `ManufacturabilityCheckFactory`, `ProjectFileFactory`, `pytest`)

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.django_db
class TestCreateCheckCobChange:
    """Tests for ManufacturabilityCheck.create_check_cob_change()."""

    def test_creates_pending_cob_change_check(self):
        """Creates a PENDING check with COB_CHANGE reason chained to the source."""
        old_check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.FINISHED,
        )

        new_check = old_check.create_check_cob_change()

        assert new_check.project == old_check.project
        assert new_check.project_file == old_check.project_file
        assert (
            new_check.trigger_reason == ManufacturabilityCheck.TriggerReason.COB_CHANGE
        )
        assert new_check.parent_check == old_check
        assert new_check.status == ManufacturabilityCheck.Status.PENDING

    def test_finished_source_check_is_not_cancelled(self):
        """A FINISHED source check keeps its status (nothing to cancel)."""
        old_check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.FINISHED,
        )

        old_check.create_check_cob_change()

        old_check.refresh_from_db()
        assert old_check.status == ManufacturabilityCheck.Status.FINISHED

    def test_in_progress_source_check_is_marked_cancelling(self):
        """A RUNNING source check is explicitly marked CANCELLING."""
        running_check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING,
        )

        new_check = running_check.create_check_cob_change()

        running_check.refresh_from_db()
        assert running_check.status == ManufacturabilityCheck.Status.CANCELLING
        assert "Chip-on-Board option changed" in running_check.processing_logs
        assert new_check.status == ManufacturabilityCheck.Status.PENDING

    def test_raises_when_not_latest_check(self):
        """Refuses to run on a check that is not the file's latest."""
        project_file = ProjectFileFactory()
        old_check = ManufacturabilityCheckFactory(
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
        )
        ManufacturabilityCheckFactory(
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
        )

        with pytest.raises(ValueError, match="latest check"):
            old_check.create_check_cob_change()
```

Note: `ManufacturabilityCheckFactory(project_file=...)` does not link `project` to the file's project automatically — that's fine here; the not-latest guard only compares checks on the same `project_file` (the existing `TestCreateCheckDrcUpdate` tests do exactly this).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestCreateCheckCobChange -v`
Expected: 4 FAILED with `AttributeError: ... has no attribute 'create_check_cob_change'`.

- [ ] **Step 3: Implement the method**

Add to `ManufacturabilityCheck` directly after `create_check_drc_update`:

```python
    def create_check_cob_change(self) -> "ManufacturabilityCheck":
        """Create a new pending check after the project's CoB option changed.

        Unlike ``create_check_drc_update`` — which leaves an in-progress check
        to the scheduled superseded-check cleanup — this cancels an in-progress
        check itself, so the superseded check can never FINISH with a result
        computed from the old CoB setting.

        Returns:
            The newly created ManufacturabilityCheck.

        Raises:
            ValueError: If this check is not the latest check for its file.
        """
        latest = self.project_file.latest_manufacturability_check
        if latest != self:
            msg = "Can only create CoB change check from the latest check for a file"
            raise ValueError(msg)

        if self.is_cancellable:
            self.mark_cancelling(reason="Chip-on-Board option changed")

        return ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            trigger_reason=self.TriggerReason.COB_CHANGE,
            parent_check=self,
        )
```

Pure ORM — no task imports (models must never import tasks). No digest/version guards (the trigger is the user toggling, not a version change).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestCreateCheckCobChange -v`
Expected: 4 PASSED.

- [ ] **Step 5: Pre-commit gate + commit**

```bash
make lint-fix && make lint && make type-check && make test
git add wafer_space/projects/models.py wafer_space/projects/tests/test_models.py
git commit -m "feat: add create_check_cob_change model method (#259)"
```

---

### Task 4: `--cob` in the precheck command (`do_starting`)

**Files:**
- Modify: `wafer_space/projects/tasks_checks.py` (~line 1070, the `command = [...]` list in `do_starting`)
- Test: `wafer_space/projects/tests/test_tasks.py` (class `TestDoStarting`; copy the mocking pattern of `test_creates_and_starts_container`, ~line 1256)

- [ ] **Step 1: Write the failing test**

Add to `TestDoStarting`, mirroring `test_creates_and_starts_container`'s setup/mocks exactly (same `shuttle`, `project__project_id="ABCD"`, `tmp_path` file, `get_docker_client` / `create_tar_archive` / `Path` patches) but with `project__chip_on_board=True`, and assert only on the command:

```python
    @pytest.mark.django_db
    def test_command_includes_cob_flag_when_requested(self, tmp_path, settings) -> None:
        """--cob is appended after --id when project.chip_on_board is True."""
        # ... same setup/mocks as test_creates_and_starts_container, plus:
        #     project__chip_on_board=True on the factory call
        ...
        create_call = mock_client.containers.create.call_args
        command = create_call.kwargs["command"]
        assert command[-1] == "--cob"
        assert command[:-1] == [
            "python3",
            "precheck.py",
            "--input",
            "/input/design.gds",
            "--output",
            "/output/design.gds",
            "--top",
            "chip_top",
            "--slot",
            "1x1",
            "--id",
            "G850ABCD",
        ]
```

The existing `test_creates_and_starts_container` already asserts the exact command list for the default project (`chip_on_board=False`), so it doubles as the "no `--cob` by default" regression test — do not modify it.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/projects/tests/test_tasks.py::TestDoStarting::test_command_includes_cob_flag_when_requested -v`
Expected: FAIL — `command[-1]` is `"G850ABCD"`, not `"--cob"`.

- [ ] **Step 3: Implement**

In `do_starting`, right after the `command = [...]` list is built (before `command_str = " ".join(command)`):

```python
    if check.project.chip_on_board:
        command.append("--cob")
```

(`--cob` is an argparse `store_true` flag in the precheck image — no value. Read live from `check.project`, exactly like `slot_size`/`full_id` above it.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest wafer_space/projects/tests/test_tasks.py::TestDoStarting -v`
Expected: all PASS (including the unmodified default-command test).

- [ ] **Step 5: Pre-commit gate + commit**

```bash
make lint-fix && make lint && make type-check && make test
git add wafer_space/projects/tasks_checks.py wafer_space/projects/tests/test_tasks.py
git commit -m "feat: pass --cob to precheck when chip_on_board is set (#259)"
```

---

### Task 5: Form field + template rendering

**Files:**
- Modify: `wafer_space/projects/forms.py` (`ProjectForm.Meta`, ~lines 199-260)
- Modify: `wafer_space/templates/projects/project_form.html` (~line 65)
- Test: `wafer_space/projects/tests/test_forms.py` (class `TestProjectForm`, line 21)

**IMPORTANT:** this codebase renders form fields explicitly in the template. Adding the field to `Meta.fields` alone will silently NOT display it — both edits are required.

- [ ] **Step 1: Write the failing tests**

Add to `TestProjectForm` in `test_forms.py` (match the class's existing style for constructing the form):

```python
    def test_chip_on_board_field_present_and_optional(self):
        """chip_on_board is on the form, optional, and defaults to False."""
        form = ProjectForm(user=self.user)
        assert "chip_on_board" in form.fields
        assert form.fields["chip_on_board"].required is False

    def test_chip_on_board_editable_for_non_staff_on_existing_project(self):
        """chip_on_board is a user field — never disabled on edit."""
        form = ProjectForm(user=self.user, instance=self.project)
        assert form.fields["chip_on_board"].disabled is False
```

(If `TestProjectForm.setUp` lacks a `self.project`, create one the same way neighbouring tests do.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest wafer_space/projects/tests/test_forms.py::TestProjectForm -v -k chip_on_board`
Expected: 2 FAILED — `KeyError: 'chip_on_board'`.

- [ ] **Step 3: Implement the form changes**

In `ProjectForm.Meta`:
- `fields`: add `"chip_on_board"` right after `"is_public"`.
- `widgets`: add `"chip_on_board": forms.CheckboxInput(attrs={"class": "form-check-input"}),`
- `help_texts`: add `"chip_on_board": ("Run extra Chip-on-Board (CoB) compatibility checks during the manufacturability precheck"),`

(The label comes from the model field's `verbose_name` set in Task 1.)

- [ ] **Step 4: Render in the template**

In `project_form.html`, after `{{ form.is_public|as_crispy_field }}` (line 65):

```html
              {{ form.chip_on_board|as_crispy_field }}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest wafer_space/projects/tests/test_forms.py::TestProjectForm -v`
Expected: PASS (all, including pre-existing tests).

- [ ] **Step 6: Pre-commit gate + commit**

```bash
make lint-fix && make lint && make type-check && make test
git add wafer_space/projects/forms.py wafer_space/templates/projects/project_form.html wafer_space/projects/tests/test_forms.py
git commit -m "feat: add CoB checkbox to project form (#259)"
```

---

### Task 6: Re-check on toggle (`ProjectUpdateView.form_valid`)

**Files:**
- Modify: `wafer_space/projects/views.py` (`ProjectUpdateView.form_valid`, ~line 252)
- Test: `wafer_space/projects/tests/test_views.py` (class `TestProjectUpdateView`, line 251 — reuse its `setUp`; import `ManufacturabilityCheck`, `ManufacturabilityCheckFactory`, `ProjectFileFactory` following the file's import style)

- [ ] **Step 1: Write the failing tests**

Add to `TestProjectUpdateView`. Base form data matches `test_owner_can_update_project_details` (line 284):

```python
    def _cob_form_data(self, *, chip_on_board: bool) -> dict:
        """Valid update-form payload toggling only chip_on_board."""
        data = {
            "name": "Test Project",
            "description": "Test project",
            "repository_url": "",
            "license_type": "proprietary",
            "other_license_spdx_id": "",
            "proprietary_terms_url": "",
        }
        if chip_on_board:
            data["chip_on_board"] = "on"
        return data

    def _make_submitted_check(self, status):
        """Attach a submitted file with a check to self.project."""
        project_file = ProjectFileFactory(project=self.project)
        self.project.submitted_file = project_file
        self.project.save()
        return ManufacturabilityCheckFactory(
            project=self.project,
            project_file=project_file,
            status=status,
        )

    def test_toggling_cob_creates_cob_change_check(self):
        """Enabling CoB on a project with a check creates one COB_CHANGE check."""
        check = self._make_submitted_check(ManufacturabilityCheck.Status.FINISHED)
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:update", kwargs={"pk": self.project.pk})

        response = self.client.post(url, self._cob_form_data(chip_on_board=True))

        assert response.status_code == HTTP_FOUND
        self.project.refresh_from_db()
        assert self.project.chip_on_board is True
        checks = ManufacturabilityCheck.objects.filter(
            project_file=check.project_file
        ).order_by("created_at")
        assert checks.count() == len([check, "new"])  # exactly one new check
        new_check = checks.last()
        assert (
            new_check.trigger_reason
            == ManufacturabilityCheck.TriggerReason.COB_CHANGE
        )
        assert new_check.parent_check == check

    def test_toggling_cob_cancels_in_progress_check(self):
        """Enabling CoB while a check is RUNNING marks it CANCELLING."""
        check = self._make_submitted_check(ManufacturabilityCheck.Status.RUNNING)
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:update", kwargs={"pk": self.project.pk})

        self.client.post(url, self._cob_form_data(chip_on_board=True))

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLING

    def test_toggling_cob_on_draft_only_persists(self):
        """No submitted file/check: the flag is saved, no check is created."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:update", kwargs={"pk": self.project.pk})

        self.client.post(url, self._cob_form_data(chip_on_board=True))

        self.project.refresh_from_db()
        assert self.project.chip_on_board is True
        assert ManufacturabilityCheck.objects.filter(project=self.project).count() == 0

    def test_unchanged_cob_creates_no_check(self):
        """Submitting the form with CoB unchanged creates no new check."""
        check = self._make_submitted_check(ManufacturabilityCheck.Status.FINISHED)
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:update", kwargs={"pk": self.project.pk})

        self.client.post(url, self._cob_form_data(chip_on_board=False))

        assert (
            ManufacturabilityCheck.objects.filter(
                project_file=check.project_file
            ).count()
            == 1
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest wafer_space/projects/tests/test_views.py::TestProjectUpdateView -v -k cob`
Expected: `test_toggling_cob_creates_cob_change_check` and `test_toggling_cob_cancels_in_progress_check` FAIL (no new check / status unchanged); the draft and unchanged tests may already pass — that is fine, they are regression guards.

- [ ] **Step 3: Implement in the view**

Replace `ProjectUpdateView.form_valid` (views can import models; `create_check_cob_change` is pure ORM):

```python
    def form_valid(self, form):
        """Save, then re-run the manufacturability check if CoB changed."""
        cob_changed = "chip_on_board" in form.changed_data
        response = super().form_valid(form)

        if cob_changed:
            latest_check = self.object.latest_manufacturability_check
            if latest_check is not None:
                latest_check.create_check_cob_change()

        messages.success(
            self.request,
            f"Project '{form.instance.name}' updated successfully!",
        )
        return response
```

Notes:
- `form.changed_data` is computed from bound data vs. `initial`, so it stays valid after save; capturing it before `super().form_valid(form)` just keeps the intent obvious.
- `self.object.latest_manufacturability_check` (the `Project` property, `models.py:406`) returns the latest check on `submitted_file`, or `None` for drafts — which satisfies `create_check_cob_change`'s latest-check guard by construction.
- This replaces the old `form_valid` body; the success message moves after the re-check logic but is otherwise unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest wafer_space/projects/tests/test_views.py::TestProjectUpdateView -v`
Expected: all PASS (including the pre-existing update tests — the success message must still appear exactly once).

- [ ] **Step 5: Pre-commit gate + commit**

```bash
make lint-fix && make lint && make type-check && make test
git add wafer_space/projects/views.py wafer_space/projects/tests/test_views.py
git commit -m "feat: re-run manufacturability check when CoB toggled (#259)"
```

---

### Task 7: CoB badge on the project detail page

**Files:**
- Modify: `wafer_space/templates/projects/project_detail.html` (after the Visibility block, ~line 128)
- Test: `wafer_space/projects/tests/test_views.py` (detail-view test class)

- [ ] **Step 1: Write the failing tests**

Add to the existing project detail view test class in `test_views.py` (find it via `grep -n "class TestProjectDetail" wafer_space/projects/tests/test_views.py`; reuse its setUp/login pattern):

```python
    def test_detail_shows_cob_badge_when_requested(self):
        """Detail page shows the CoB badge when chip_on_board is set."""
        self.project.chip_on_board = True
        self.project.save()
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})

        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert "Chip-on-Board" in response.content.decode()

    def test_detail_shows_standard_packaging_when_not_requested(self):
        """Detail page shows standard packaging when chip_on_board is unset."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})

        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert "Chip-on-Board" not in response.content.decode()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest wafer_space/projects/tests/test_views.py -v -k "cob_badge or standard_packaging"`
Expected: `test_detail_shows_cob_badge_when_requested` FAILS ("Chip-on-Board" not in page); the negative test passes already (regression guard).

- [ ] **Step 3: Add the badge**

In `project_detail.html`, after the Visibility `</p>` (line ~128), matching the surrounding badge markup:

```html
            <p class="mb-2">
              <strong>Packaging:</strong>
              {% if project.chip_on_board %}
                <span class="badge bg-info"><i class="bi bi-cpu"></i> Chip-on-Board (CoB)</span>
              {% else %}
                <span class="badge bg-secondary">Standard</span>
              {% endif %}
            </p>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest wafer_space/projects/tests/test_views.py -v -k "cob_badge or standard_packaging"`
Expected: 2 PASSED. (`make lint` runs djlint over templates — fix any template lint it reports.)

- [ ] **Step 5: Pre-commit gate + commit**

```bash
make lint-fix && make lint && make type-check && make test
git add wafer_space/templates/projects/project_detail.html wafer_space/projects/tests/test_views.py
git commit -m "feat: show CoB packaging badge on project detail (#259)"
```

---

### Task 8: Final verification + follow-ups

- [ ] **Step 1: Full quality gate**

Run: `make check-all`
Expected: everything green. Then `make test` once more: expect baseline + ~17 new tests, 0 failures.

- [ ] **Step 2: Verify migrations are consistent**

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.

- [ ] **Step 3: Update issue #259**

The issue mentions a `--chip-on-board` flag; the real precheck flag is `--cob`. Post a comment on #259 noting the implemented flag name (use `gh issue comment 259 ...`).

- [ ] **Step 4: Finish the branch**

Use @superpowers:finishing-a-development-branch — push and open a PR referencing #259. PR body should call out: new migration(s), the explicit-cancel design (link the spec), and that no new Celery tasks/schedules were added.
