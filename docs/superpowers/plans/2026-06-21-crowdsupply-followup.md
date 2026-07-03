# CrowdSupply Follow-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename all prose to "CrowdSupply", add a `crowd_supply_url` field to `Shuttle` (seeded for G801–G803), and make the project detail page link the order ID to the shuttle's CrowdSupply campaign page.

**Architecture:** New `URLField` on `Shuttle` with an `AddField` + `RunPython` migration (`shuttles/0008`, depending on `projects/0041` which seeds G801). The detail template links `crowd_supply_order_id` to `project.shuttle.crowd_supply_url` when present, plain text otherwise. `verbose_name="CrowdSupply Order ID"` on the project field fixes the form label and admin header in one place. The account-scoped `crowd_supply_order_url` property is deleted.

**Tech Stack:** Django 5.2, django-simple-history, pytest-django, factory-boy, ruff, mypy, djlint.

**Spec:** `docs/superpowers/specs/2026-06-21-crowdsupply-followup-design.md`

**Working directory:** this worktree (`.worktrees/crowd-supply-order-id`, branch `feature/crowd-supply-order-id`, PR #263).

**Pre-commit policy (every commit):** `make lint-fix && make lint && make type-check && make test` must pass. NEVER add `# noqa` / `# type: ignore` without explicit user permission.

**Facts the implementer must know:**

- The pytest database runs the full migration chain, so **G801 already exists in test databases** (seeded by `projects/0041_populate_shuttle_and_project_ids`). G802/G803 do not. `ShuttleFactory` auto-sequences names starting at `G800` and collides with the seeded G801 — always pass explicit `name=` when creating shuttles in tests (use G85x names to stay clear).
- `Shuttle.save()` calls `full_clean()`, so `Shuttle.objects.create(...)` validates; `queryset.update(...)` bypasses it (fine for the data migration).
- `Project.clean()` enforces core-field immutability on saved instances; `shuttle` is a core field. In tests, set `shuttle` at `Project.objects.create(...)` time, never by assigning to a saved project.
- `TestProjectDetailView.setUp` (`wafer_space/projects/tests/test_views.py:101`) creates `self.project` with **no shuttle** — it is the ready-made "project without shuttle" case.
- Python identifiers (`crowd_supply_order_id`, `validate_crowd_supply_order_id`, `crowd_supply_url`) keep their snake_case names. Only prose changes.

---

## File Structure

| File | Responsibility | Change |
| --- | --- | --- |
| `wafer_space/shuttles/models.py` | `crowd_supply_url` field | Modify |
| `wafer_space/shuttles/migrations/0008_shuttle_crowd_supply_url.py` | AddField + G801–G803 data step | Create |
| `wafer_space/shuttles/tests/test_models.py` | field default + data-step tests | Create |
| `wafer_space/shuttles/admin.py` | expose field in fieldsets | Modify |
| `wafer_space/users/management/commands/populate_dev_data.py` | G801 dev URL | Modify |
| `wafer_space/projects/models.py` | verbose_name/help_text/docstrings; delete `crowd_supply_order_url` | Modify |
| `wafer_space/projects/migrations/0058_*.py` | absorb field kwarg changes in place | Modify |
| `wafer_space/projects/forms.py` | help_text wording | Modify |
| `wafer_space/projects/tests/test_models.py` | drop property tests, fix docstring | Modify |
| `wafer_space/projects/tests/test_forms.py` | fix docstring | Modify |
| `wafer_space/templates/projects/project_detail.html` | label + link target | Modify |
| `wafer_space/projects/tests/test_views.py` | rewrite detail tests, label test | Modify |
| `docs/superpowers/specs/2026-06-09-*.md`, `docs/superpowers/plans/2026-06-09-*.md` | naming sweep | Modify |

---

## Task 1: `Shuttle.crowd_supply_url` field + migration with data step

**Files:**
- Create: `wafer_space/shuttles/tests/test_models.py`
- Modify: `wafer_space/shuttles/models.py` (after `grid_config_file`, ~line 93)
- Create: `wafer_space/shuttles/migrations/0008_shuttle_crowd_supply_url.py`

- [ ] **Step 1: Write the failing tests**

Create `wafer_space/shuttles/tests/test_models.py`:

```python
"""Tests for shuttle models."""

import importlib

import pytest
from django.apps import apps

from wafer_space.shuttles.models import Shuttle

G801_URL = "https://www.crowdsupply.com/wafer-space/gf180mcu-run-1/"
G802_URL = "https://www.crowdsupply.com/wafer-space/gf180mcu-run-2/"
G803_URL = "https://www.crowdsupply.com/wafer-space/gf180mcu-run-3/"


@pytest.mark.django_db
class TestShuttleCrowdSupplyUrl:
    """The CrowdSupply campaign URL on Shuttle."""

    def test_field_defaults_to_blank(self):
        shuttle = Shuttle.objects.create(name="G850", description="Test run")
        assert shuttle.crowd_supply_url == ""

    def test_migration_seeded_g801_url(self):
        # G801 is created by projects/0041 during test-DB setup; shuttles/0008
        # (which depends on it) must have stamped its CrowdSupply URL.
        g801 = Shuttle.objects.get(name="G801")
        assert g801.crowd_supply_url == G801_URL

    def test_data_step_sets_all_three_urls(self):
        # G802/G803 are not migration-seeded; create them, then re-run the
        # forward data function from the migration module.
        Shuttle.objects.create(name="G802", description="Run 2")
        Shuttle.objects.create(name="G803", description="Run 3")
        migration = importlib.import_module(
            "wafer_space.shuttles.migrations.0008_shuttle_crowd_supply_url"
        )

        migration.set_crowd_supply_urls(apps, None)

        urls = dict(
            Shuttle.objects.filter(name__in=["G801", "G802", "G803"]).values_list(
                "name", "crowd_supply_url"
            )
        )
        assert urls == {"G801": G801_URL, "G802": G802_URL, "G803": G803_URL}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest wafer_space/shuttles/tests/test_models.py -v`
Expected: FAIL — `crowd_supply_url` attribute/column does not exist.

- [ ] **Step 3: Add the field**

In `wafer_space/shuttles/models.py`, directly after the `grid_config_file` field:

```python
    crowd_supply_url = models.URLField(
        blank=True,
        default="",
        verbose_name="CrowdSupply URL",
        help_text="CrowdSupply campaign page for this shuttle run (optional).",
    )
```

- [ ] **Step 4: Generate the schema migration, then add the data step**

Run: `uv run python manage.py makemigrations shuttles`
Expected: creates `wafer_space/shuttles/migrations/0008_shuttle_crowd_supply_url.py` with one `AddField`.

Edit the generated file to add the data functions and dependency. Final content (keep the generated header comment):

```python
from django.db import migrations, models

CROWD_SUPPLY_URLS = {
    "G801": "https://www.crowdsupply.com/wafer-space/gf180mcu-run-1/",
    "G802": "https://www.crowdsupply.com/wafer-space/gf180mcu-run-2/",
    "G803": "https://www.crowdsupply.com/wafer-space/gf180mcu-run-3/",
}


def set_crowd_supply_urls(apps, schema_editor):
    """Stamp CrowdSupply campaign URLs onto known shuttle runs (if present)."""
    shuttle_model = apps.get_model("shuttles", "Shuttle")
    for name, url in CROWD_SUPPLY_URLS.items():
        shuttle_model.objects.filter(name=name).update(crowd_supply_url=url)


def unset_crowd_supply_urls(apps, schema_editor):
    """Blank the seeded URLs on reverse migration."""
    shuttle_model = apps.get_model("shuttles", "Shuttle")
    shuttle_model.objects.filter(name__in=CROWD_SUPPLY_URLS).update(
        crowd_supply_url=""
    )


class Migration(migrations.Migration):

    dependencies = [
        ("shuttles", "0007_alter_shuttleslot_fields"),
        # projects/0041 seeds the G801 shuttle; run after it so the data
        # step below finds G801 on freshly built databases.
        ("projects", "0041_populate_shuttle_and_project_ids"),
    ]

    operations = [
        migrations.AddField(
            model_name="shuttle",
            name="crowd_supply_url",
            field=models.URLField(
                blank=True,
                default="",
                help_text="CrowdSupply campaign page for this shuttle run (optional).",
                verbose_name="CrowdSupply URL",
            ),
        ),
        migrations.RunPython(set_crowd_supply_urls, unset_crowd_supply_urls),
    ]
```

Note: the generated `AddField` kwargs must match what `makemigrations` produced — only add the `RunPython` operation, the two functions, the `CROWD_SUPPLY_URLS` dict, and the `projects/0041` dependency.

- [ ] **Step 5: Verify migration state and run the tests**

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: "No changes detected".

Run: `uv run pytest wafer_space/shuttles/tests/test_models.py -v`
Expected: PASS (3 tests). The test DB rebuild applies 0008, so `test_migration_seeded_g801_url` proves the forward step ran in-chain.

- [ ] **Step 6: Full gate, then commit**

```bash
make lint-fix && make lint && make type-check && make test
git add wafer_space/shuttles/models.py wafer_space/shuttles/migrations/0008_shuttle_crowd_supply_url.py wafer_space/shuttles/tests/test_models.py
git commit -m "feat: add crowd_supply_url to Shuttle, seed G801-G803 campaign URLs"
```

---

## Task 2: Expose the field in admin and dev data

**Files:**
- Modify: `wafer_space/shuttles/admin.py` (fieldsets, ~line 28)
- Modify: `wafer_space/users/management/commands/populate_dev_data.py` (`_create_shuttle`, ~line 266, and the G801 call site, ~line 93)

- [ ] **Step 1: Add the field to `ShuttleAdmin`**

In the first (`None`) fieldset:

```python
        (None, {"fields": ("name", "description", "status", "crowd_supply_url")}),
```

- [ ] **Step 2: Set the G801 URL in dev data**

Change `_create_shuttle` to accept the URL (keyword-only, per FBT/API style):

```python
    def _create_shuttle(
        self, name: str, description: str, *, crowd_supply_url: str = ""
    ) -> Shuttle:
        """Create a shuttle with given name and description."""
        shuttle, created = Shuttle.objects.get_or_create(
            name=name,
            defaults={
                "description": description,
                "status": Shuttle.Status.OPEN,
                "crowd_supply_url": crowd_supply_url,
            },
        )
```

And the G801 call site (G899 stays URL-less to exercise the plain-text path):

```python
        g801 = self._create_shuttle(
            "G801",
            "Initial shuttle run for wafer.space",
            crowd_supply_url="https://www.crowdsupply.com/wafer-space/gf180mcu-run-1/",
        )
```

- [ ] **Step 3: Full gate, then commit**

```bash
make lint-fix && make lint && make type-check && make test
git add wafer_space/shuttles/admin.py wafer_space/users/management/commands/populate_dev_data.py
git commit -m "feat: expose Shuttle CrowdSupply URL in admin and dev data"
```

---

## Task 3: Project field naming + delete the account-URL property

**Files:**
- Modify: `wafer_space/projects/models.py` (validator ~line 64, field ~line 278, property ~line 497)
- Modify: `wafer_space/projects/migrations/0058_historicalproject_crowd_supply_order_id_and_more.py` (both `AddField` kwargs)
- Modify: `wafer_space/projects/forms.py` (help_texts, ~line 270)
- Modify: `wafer_space/projects/tests/test_models.py` (`TestCrowdSupplyOrderId`, ~line 3306)
- Modify: `wafer_space/projects/tests/test_forms.py` (docstring, ~line 116)

- [ ] **Step 1: Update the tests first**

In `wafer_space/projects/tests/test_models.py`, class `TestCrowdSupplyOrderId`:
- Docstring → `"""CrowdSupply order number validation."""`
- **Delete** `test_url_property_returns_account_order_url` and `test_url_property_empty_when_unset` (the property is being removed).

In `wafer_space/projects/tests/test_forms.py` line 116, docstring → `"""CrowdSupply order number is optional and cleans to empty string."""`

- [ ] **Step 2: Run tests — deletions can't fail, but confirm the module still passes**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestCrowdSupplyOrderId wafer_space/projects/tests/test_forms.py -v`
Expected: PASS (property still exists; its tests are simply gone).

- [ ] **Step 3: Update the model**

Validator (docstring + message; the URL-interpolation rationale is obsolete once the property goes):

```python
def validate_crowd_supply_order_id(value: str) -> None:
    """Validate a CrowdSupply order number is ASCII digits (e.g. "327373").

    Uses an explicit ASCII check rather than ``str.isdigit()`` alone, which
    also accepts non-ASCII digit characters (e.g. Arabic-Indic digits or
    superscripts) that are not valid in a CrowdSupply order number.
    """
    if not (value.isascii() and value.isdigit()):
        msg = "CrowdSupply order number must contain only digits (e.g. 327373)."
        raise ValidationError(msg)
```

Field (add `verbose_name`, reword help_text):

```python
    crowd_supply_order_id = models.CharField(
        max_length=20,
        blank=True,
        default="",
        validators=[validate_crowd_supply_order_id],
        verbose_name="CrowdSupply Order ID",
        help_text="CrowdSupply order number, e.g. 327373 (optional).",
    )
```

**Delete** the whole `crowd_supply_order_url` property (models.py ~lines 497–502).

- [ ] **Step 4: Update migration 0058 in place (branch is unmerged — no new migration)**

In both `AddField` entries of `0058_historicalproject_crowd_supply_order_id_and_more.py`, replace the `field=` value with:

```python
            field=models.CharField(blank=True, default='', help_text='CrowdSupply order number, e.g. 327373 (optional).', max_length=20, validators=[wafer_space.projects.models.validate_crowd_supply_order_id], verbose_name='CrowdSupply Order ID'),
```

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: "No changes detected". If Django reports pending changes, run `uv run python manage.py makemigrations projects --dry-run --verbosity 2` and align the 0058 kwargs until the check passes.

- [ ] **Step 5: Update the form help text**

In `wafer_space/projects/forms.py` help_texts:

```python
            "crowd_supply_order_id": (
                "CrowdSupply order number, e.g. 327373 (optional)."
            ),
```

- [ ] **Step 6: Run tests, full gate, commit**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestCrowdSupplyOrderId wafer_space/projects/tests/test_forms.py -v`
Expected: PASS.

Note: two view tests (`test_crowd_supply_order_shown_when_set` asserts `crowd_supply_order_url`; label assertions) will break at `make test` here — **that is expected**; Task 4 rewrites them. To keep commits green, Tasks 3 and 4 may be committed together if `make test` fails; prefer doing Task 4's template/test rewrite immediately and committing both as one commit:

```bash
make lint-fix && make lint && make type-check && make test
git add wafer_space/projects/ wafer_space/templates/projects/project_detail.html
git commit -m "feat: CrowdSupply naming and shuttle-page link for order ID"
```

(See Task 4 for the template/test contents that must be included for the suite to pass.)

---

## Task 4: Detail template link + view tests (commits together with Task 3)

**Files:**
- Modify: `wafer_space/templates/projects/project_detail.html` (~lines 145–154)
- Modify: `wafer_space/projects/tests/test_views.py` (`TestProjectDetailView` ~line 142, `TestProjectUpdateView` label test ~line 563)

- [ ] **Step 1: Rewrite the view tests (failing first)**

Replace `test_crowd_supply_order_shown_when_set` and update `test_crowd_supply_order_absent_when_blank` in `TestProjectDetailView`; add the shuttle import at the top of the file if missing (`from wafer_space.shuttles.models import Shuttle`):

```python
    def test_order_id_links_to_shuttle_crowdsupply_page(self):
        """Order ID renders as a link to the shuttle's CrowdSupply page."""
        shuttle = Shuttle.objects.create(
            name="G851",
            description="Linked run",
            crowd_supply_url="https://www.crowdsupply.com/wafer-space/gf180mcu-run-1/",
        )
        project = Project.objects.create(
            user=self.user,
            name="Linked Project",
            shuttle=shuttle,
            crowd_supply_order_id="327373",
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": project.pk})
        response = self.client.get(url)

        content = response.content.decode()
        assert "CrowdSupply Order ID:" in content
        assert "327373" in content
        assert shuttle.crowd_supply_url in content

    def test_order_id_plain_text_when_shuttle_has_no_url(self):
        """Order ID renders without a link when the shuttle URL is blank."""
        shuttle = Shuttle.objects.create(name="G852", description="Unlinked run")
        project = Project.objects.create(
            user=self.user,
            name="Unlinked Project",
            shuttle=shuttle,
            crowd_supply_order_id="327373",
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": project.pk})
        response = self.client.get(url)

        content = response.content.decode()
        assert "CrowdSupply Order ID:" in content
        assert "327373" in content
        assert "crowdsupply.com" not in content

    def test_order_id_plain_text_when_project_has_no_shuttle(self):
        """Order ID renders without a link when the project has no shuttle."""
        self.project.crowd_supply_order_id = "327373"
        self.project.save()

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        content = response.content.decode()
        assert "CrowdSupply Order ID:" in content
        assert "327373" in content
        assert "crowdsupply.com" not in content

    def test_crowd_supply_order_absent_when_blank(self):
        """No CrowdSupply row renders when the order ID is unset."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert "CrowdSupply Order ID:" not in response.content.decode()
```

In `TestProjectUpdateView.test_order_id_field_rendered_on_edit_form` (~line 563), add a label assertion, and update its docstring to
`"""The CrowdSupply order field is present and rendered on the form."""`
(the old docstring is the only "Crowd Supply" occurrence in `wafer_space/`
not otherwise covered — Task 5's sweep fails if it survives):

```python
        assert "CrowdSupply Order ID" in response.content.decode()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest wafer_space/projects/tests/test_views.py -v -k "order_id or crowd_supply"`
Expected: FAIL — template still renders the old label and account URL.

- [ ] **Step 3: Update the template**

Replace the block at `project_detail.html` ~lines 145–154:

```html
            {% if project.crowd_supply_order_id %}
              <p class="mb-2">
                <strong>CrowdSupply Order ID:</strong>
                {% if project.shuttle.crowd_supply_url %}
                  <a href="{{ project.shuttle.crowd_supply_url }}"
                     target="_blank"
                     rel="noopener">
                    <i class="bi bi-box-arrow-up-right"></i> {{ project.crowd_supply_order_id }}
                  </a>
                {% else %}
                  {{ project.crowd_supply_order_id }}
                {% endif %}
              </p>
            {% endif %}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest wafer_space/projects/tests/test_views.py -v -k "order_id or crowd_supply"`
Expected: PASS.

Run: `uv run djlint wafer_space/templates/projects/project_detail.html --check`
Expected: 0 files would be updated (fix formatting if not).

- [ ] **Step 5: Full gate, then commit (combined with Task 3 changes)**

```bash
make lint-fix && make lint && make type-check && make test
git add wafer_space/projects/ wafer_space/templates/projects/project_detail.html
git commit -m "feat: CrowdSupply naming and shuttle-page link for order ID"
```

---

## Task 5: Docs sweep, PR metadata, verification

**Files:**
- Modify: `docs/superpowers/specs/2026-06-09-crowd-supply-order-id-design.md`
- Modify: `docs/superpowers/plans/2026-06-09-crowd-supply-order-id.md`

- [ ] **Step 1: Naming sweep in the two 2026-06-09 docs**

Replace every `Crowd Supply` with `CrowdSupply` in both files (plain spelling fix; the historical code snippets in them stay otherwise untouched — they document what was designed then).

- [ ] **Step 2: Sweep check**

Run: `grep -rn "Crowd Supply\|Crowd supply\|crowd supply" wafer_space/`
Expected: no output.

Run: `grep -rn "Crowd Supply\|Crowd supply" docs/superpowers/ | grep -v 2026-06-21-crowdsupply-followup`
Expected: no output (the 2026-06-21 spec intentionally quotes the banned spellings and is excluded).

- [ ] **Step 3: Commit docs**

```bash
git add docs/superpowers/
git commit -m "docs: CrowdSupply naming sweep in 2026-06-09 spec and plan"
```

- [ ] **Step 4: Update PR #263 title/body**

Use `gh api` (NOT `gh pr edit` — it silently fails on this repo):

```bash
gh api -X PATCH repos/wafer-space/platform.wafer.space/pulls/263 -f title="feat: associate a CrowdSupply order number with a project"
```

Fetch the current body (`gh pr view 263 --json body`), rewrite "Crowd Supply" → "CrowdSupply", append a short section describing the follow-up (shuttle CrowdSupply URL + shuttle-page link), and PATCH the body.

- [ ] **Step 5: Final verification and push**

```bash
make lint-fix && make lint && make type-check && make test
uv run python manage.py makemigrations --check --dry-run
uv run pre-commit run --all-files
git push origin feature/crowd-supply-order-id
```

Watch CI (`gh run watch`) until green.

---

## Corrections (added during execution)

- **Task 1 test deviation (approved):** the planned `test_migration_seeded_g801_url`
  (assert the migration-seeded G801 row carries the URL) is ordering-fragile:
  `live_server` browser tests flush the database mid-suite, deleting
  migration-seeded rows, so the assertion fails under full `make test`
  ordering. It was replaced by `test_migration_runs_after_g801_seed`
  (asserts migration 0008 declares the `projects/0041` dependency) plus a
  `get_or_create`-based data-step test. An isolated `--create-db` run of the
  original test proved in-chain seeding works on fresh databases.
  **Lesson:** never rely on migration-seeded rows existing in ordinary tests.
- **Review-queued cosmetic fixes** (applied in the same commit as this note):
  `list(CROWD_SUPPLY_URLS)` + `elidable=True` in migration 0008, dev-data
  docstring/drift-guard comment, `HTTP_OK` guards + fifth matrix case in the
  detail-view tests (commit 87b7776).
