# Crowd Supply Order Number Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a project owner associate an optional Crowd Supply order number (e.g. `327373`) with their project, shown on the edit form, detail page, and Django admin.

**Architecture:** Add a digits-only `CharField` (`crowd_supply_order_id`) to the `Project` model in the always-editable `USER_FIELDS` group, plus a computed `crowd_supply_order_url` property. Surface it through the existing `ProjectForm`, `ProjectAdmin`, and `project_detail.html` patterns already used by `repository_url`. No uniqueness, no external verification.

**Tech Stack:** Django 5.2, django-simple-history, pytest-django, factory-boy, ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-06-09-crowd-supply-order-id-design.md`

**Working directory:** this worktree (`.worktrees/crowd-supply-order-id`, branch `feature/crowd-supply-order-id`, based on PR #260 `fix/zip-mime-detection`).

**Pre-commit policy (every commit):** `make lint-fix && make lint && make type-check && make test` must pass. Per project CLAUDE.md, NEVER add `# noqa` / `# type: ignore` without explicit user permission — fix the root cause.

---

## File Structure

| File | Responsibility | Change |
| --- | --- | --- |
| `wafer_space/projects/models.py` | `validate_crowd_supply_order_id`, `crowd_supply_order_id` field, `USER_FIELDS` membership, `crowd_supply_order_url` property | Modify |
| `wafer_space/projects/migrations/00NN_*.py` | Schema migration for `Project` + `HistoricalProject` | Create (generated) |
| `wafer_space/projects/forms.py` | Field in `ProjectForm.Meta`, widget, help text, `clean_crowd_supply_order_id` | Modify |
| `wafer_space/projects/admin.py` | `list_display` + `search_fields` entries | Modify |
| `wafer_space/templates/projects/project_detail.html` | Conditional linked detail row | Modify |
| `wafer_space/projects/tests/test_models.py` | Validator + property + round-trip tests | Modify |
| `wafer_space/projects/tests/test_forms.py` | Form normalisation / validation tests | Modify |

---

## Task 1: Model validator + field + property

**Files:**
- Modify: `wafer_space/projects/models.py` (validator near `validate_project_id` at line 49; field in `Project` near `repository_url` ~line 247; `USER_FIELDS` frozenset ~line 158; property near other `@property` methods)
- Test: `wafer_space/projects/tests/test_models.py`

- [ ] **Step 1: Write the failing tests**

Add to `test_models.py` (validator is imported from models):

```python
from wafer_space.projects.models import validate_crowd_supply_order_id


class TestCrowdSupplyOrderId:
    """Crowd Supply order number validation and URL property."""

    @pytest.mark.parametrize("value", ["327373", "0", "00123"])
    def test_validator_accepts_digit_strings(self, value):
        # Should not raise.
        validate_crowd_supply_order_id(value)

    @pytest.mark.parametrize("value", ["abc", "3273 73", "#327373", "32.73", "-1"])
    def test_validator_rejects_non_digits(self, value):
        with pytest.raises(ValidationError):
            validate_crowd_supply_order_id(value)

    @pytest.mark.django_db
    def test_blank_order_id_is_valid(self):
        # Field is optional: blank must pass full_clean (validators skipped on blank).
        project = ProjectFactory()
        project.crowd_supply_order_id = ""
        project.full_clean()  # must not raise

    @pytest.mark.django_db
    def test_url_property_returns_account_order_url(self):
        project = ProjectFactory(crowd_supply_order_id="327373")
        assert (
            project.crowd_supply_order_url
            == "https://www.crowdsupply.com/account/order/327373"
        )

    @pytest.mark.django_db
    def test_url_property_empty_when_unset(self):
        project = ProjectFactory(crowd_supply_order_id="")
        assert project.crowd_supply_order_url == ""

    @pytest.mark.django_db
    def test_order_id_round_trips(self):
        project = ProjectFactory(crowd_supply_order_id="314421")
        project.refresh_from_db()
        assert project.crowd_supply_order_id == "314421"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestCrowdSupplyOrderId -v`
Expected: FAIL — `ImportError`/`AttributeError` (validator, field, and property don't exist yet).

- [ ] **Step 3: Add the validator**

In `models.py`, after `validate_project_id` (ends ~line 60):

```python
def validate_crowd_supply_order_id(value: str) -> None:
    """Validate a Crowd Supply order number is all digits (e.g. "327373")."""
    if not value.isdigit():
        msg = "Crowd Supply order number must contain only digits (e.g. 327373)."
        raise ValidationError(msg)
```

- [ ] **Step 4: Add the field and register it as a user field**

Add `"crowd_supply_order_id"` to the `USER_FIELDS` frozenset (`Project`, ~line 158).

Add the field near `repository_url` (~line 247):

```python
crowd_supply_order_id = models.CharField(
    max_length=20,
    blank=True,
    default="",
    validators=[validate_crowd_supply_order_id],
    help_text="Crowd Supply order number, e.g. 327373 (optional).",
)
```

- [ ] **Step 5: Add the URL property**

Near the other `@property` methods on `Project`:

```python
@property
def crowd_supply_order_url(self) -> str:
    """Crowd Supply order page URL, or '' when no order id is set."""
    if not self.crowd_supply_order_id:
        return ""
    return f"https://www.crowdsupply.com/account/order/{self.crowd_supply_order_id}"
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestCrowdSupplyOrderId -v`
Expected: PASS (all parametrized cases).

- [ ] **Step 7: Lint + type-check, then commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/models.py wafer_space/projects/tests/test_models.py
git commit -m "feat: add crowd_supply_order_id field, validator and URL property to Project"
```

---

## Task 2: Database migration

**Files:**
- Create: `wafer_space/projects/migrations/00NN_add_crowd_supply_order_id.py` (generated; take whatever number `makemigrations` produces)

- [ ] **Step 1: Generate the migration**

Run: `uv run python manage.py makemigrations projects`
Expected: one new migration adding `crowd_supply_order_id` to `project` and `historicalproject`.

- [ ] **Step 2: Verify no further migrations are needed**

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: "No changes detected".

- [ ] **Step 3: Apply and confirm it runs**

Run: `uv run python manage.py migrate projects`
Expected: the new migration applies cleanly (and is reversible).

- [ ] **Step 4: Commit**

```bash
git add wafer_space/projects/migrations/
git commit -m "feat: migration for Project.crowd_supply_order_id"
```

---

## Task 3: Project form field + normalisation

**Files:**
- Modify: `wafer_space/projects/forms.py` (`ProjectForm.Meta.fields` ~line 199; `widgets` ~line 213; `help_texts` ~line 253; add `clean_crowd_supply_order_id` method on `ProjectForm`)
- Test: `wafer_space/projects/tests/test_forms.py`

- [ ] **Step 1: Write the failing tests**

Add to `TestProjectForm` in `test_forms.py` (uses the existing `setUp` shuttle). Helper to build base data:

```python
    def _base_form_data(self, **overrides):
        data = {
            "name": "Test Project",
            "shuttle": self.shuttle.pk,
            "project_id": "TEST",
            "slot_size": "1x1",
        }
        data.update(overrides)
        return data

    def test_order_id_optional(self):
        form = ProjectForm(data=self._base_form_data())
        assert form.is_valid(), form.errors
        assert form.cleaned_data["crowd_supply_order_id"] == ""

    def test_order_id_accepts_digits(self):
        form = ProjectForm(data=self._base_form_data(crowd_supply_order_id="327373"))
        assert form.is_valid(), form.errors
        assert form.cleaned_data["crowd_supply_order_id"] == "327373"

    def test_order_id_strips_hash_and_whitespace(self):
        form = ProjectForm(
            data=self._base_form_data(crowd_supply_order_id="  #327373 ")
        )
        assert form.is_valid(), form.errors
        assert form.cleaned_data["crowd_supply_order_id"] == "327373"

    def test_order_id_rejects_non_numeric(self):
        form = ProjectForm(data=self._base_form_data(crowd_supply_order_id="abc123"))
        assert not form.is_valid()
        assert "crowd_supply_order_id" in form.errors
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest wafer_space/projects/tests/test_forms.py::TestProjectForm -v -k order_id`
Expected: FAIL — field not in form / no normalisation.

- [ ] **Step 3: Add the field to the form Meta**

- Add `"crowd_supply_order_id"` to `Meta.fields` in the User-fields section (after `"repository_url"`).
- Add to `Meta.widgets`:

```python
"crowd_supply_order_id": forms.TextInput(
    attrs={
        "class": "form-control",
        "placeholder": "327373",
        "inputmode": "numeric",
    },
),
```

- Add to `Meta.help_texts`:

```python
"crowd_supply_order_id": "Crowd Supply order number, e.g. 327373 (optional).",
```

- [ ] **Step 4: Add the normalising clean method**

On `ProjectForm` (a method, near `clean()` ~line 345):

```python
def clean_crowd_supply_order_id(self) -> str:
    """Strip whitespace and a leading '#' so a pasted '#327373' is accepted."""
    value = self.cleaned_data.get("crowd_supply_order_id", "")
    return value.strip().lstrip("#").strip()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest wafer_space/projects/tests/test_forms.py::TestProjectForm -v -k order_id`
Expected: PASS.

- [ ] **Step 6: Lint + type-check, then commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/forms.py wafer_space/projects/tests/test_forms.py
git commit -m "feat: add crowd_supply_order_id to ProjectForm with #/whitespace normalisation"
```

---

## Task 4: Django admin

**Files:**
- Modify: `wafer_space/projects/admin.py` (`ProjectAdmin.list_display` ~line 22; `search_fields` ~line 44)

- [ ] **Step 1: Add to `list_display` and `search_fields`**

Insert `"crowd_supply_order_id"` into `ProjectAdmin.list_display` (e.g. after `"status"`) and into `ProjectAdmin.search_fields` (e.g. after `"project_id"`). `ProjectAdmin` has no custom `fields`/`fieldsets`, so the field is automatically editable on the admin change form.

- [ ] **Step 2: Verify admin loads (smoke check)**

Run: `uv run python manage.py check`
Expected: "System check identified no issues".

- [ ] **Step 3: Commit**

```bash
git add wafer_space/projects/admin.py
git commit -m "feat: surface crowd_supply_order_id in Project admin list and search"
```

---

## Task 5: Detail page row

**Files:**
- Modify: `wafer_space/templates/projects/project_detail.html` (Project Details card; insert after the `repository_url` `{% if %}` block ~line 136, before the License `<p>`)

- [ ] **Step 1: Add the conditional linked row**

Insert immediately after the closing `{% endif %}` of the Repository block:

```html
{% if project.crowd_supply_order_id %}
  <p class="mb-2">
    <strong>Crowd Supply order:</strong>
    <a href="{{ project.crowd_supply_order_url }}" target="_blank" rel="noopener">
      <i class="bi bi-box-arrow-up-right"></i> {{ project.crowd_supply_order_id }}
    </a>
  </p>
{% endif %}
```

- [ ] **Step 2: Lint the template**

Run: `uv run djlint wafer_space/templates/projects/project_detail.html --lint`
Expected: no new errors. (If `make lint` includes djlint, prefer `make lint-fix && make lint`.)

- [ ] **Step 3: Commit**

```bash
git add wafer_space/templates/projects/project_detail.html
git commit -m "feat: show Crowd Supply order link on project detail page"
```

---

## Task 6: Full verification

- [ ] **Step 1: Run the whole pre-commit gate**

Run: `make lint-fix && make lint && make type-check && make test`
Expected: all clean; full unit suite passes (no regressions vs. the PR #260 baseline of 1185 passing).

- [ ] **Step 2: Confirm migrations are complete**

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: "No changes detected".

- [ ] **Step 3 (optional manual sanity): exercise the field end-to-end**

In `uv run python manage.py shell`, create a project with `crowd_supply_order_id="314421"`, assert `crowd_supply_order_url` is correct, and `full_clean()` rejects `"abc"`. (No commit — verification only.)

- [ ] **Step 4: Finish the branch**

Use superpowers:finishing-a-development-branch to decide how to integrate (PR onto `fix/zip-mime-detection` / `main`, or merge), and to clean up the worktree.

---

## Notes / decisions captured

- **CharField not integer:** order IDs are identifiers, not quantities (see spec "Approach").
- **No uniqueness, no API verification, no verified flag, no backfill** — explicitly out of scope (spec YAGNI).
- **`list_filter` intentionally not changed** — free-form numeric IDs make poor filters.
- **Validator skipped on blank** — relies on Django treating `""` as an empty value, so optional behaviour needs no special-casing.
