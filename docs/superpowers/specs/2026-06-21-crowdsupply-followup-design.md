# CrowdSupply follow-up changes — Design

**Date:** 2026-06-21
**Branch:** `feature/crowd-supply-order-id` (PR #263, base `main`)
**Status:** Approved by user (design discussion in session)
**Builds on:** `docs/superpowers/specs/2026-06-09-crowd-supply-order-id-design.md`

## Problem

Three follow-up changes to the shipped CrowdSupply order-number feature:

1. The brand name must always be written **CrowdSupply** — never "Crowd
   Supply" or "Crowd supply". Today the detail page says "Crowd Supply
   order:", the edit form auto-generates the label "Crowd supply order id"
   from the field name, and help texts / docs / the PR title all use
   "Crowd Supply".
2. The displayed order ID should link to the **CrowdSupply campaign page of
   the project's shuttle**, not the account-scoped order URL
   (`https://www.crowdsupply.com/account/order/<id>`), which only the buyer
   can open. Shuttles need a CrowdSupply URL:
   - G801 → `https://www.crowdsupply.com/wafer-space/gf180mcu-run-1/`
   - G802 → `https://www.crowdsupply.com/wafer-space/gf180mcu-run-2/`
   - G803 → `https://www.crowdsupply.com/wafer-space/gf180mcu-run-3/`
3. The CrowdSupply Order ID must be shown in the **Project Details** section
   of the project detail page. (The row already lives in that card; this
   change keeps it there with the corrected label and new link target.)

## Requirements

| Decision | Choice |
| --- | --- |
| Where the shuttle URL lives | **`Shuttle` model field** (user-selected over code-config dict and YAML layout files) |
| Link target for the order ID | `project.shuttle.crowd_supply_url` |
| Shuttle without a URL | Order ID renders as **plain text, no link** |
| Project without a shuttle | Same plain-text rendering (`Project.shuttle` is nullable; `{% if project.shuttle.crowd_supply_url %}` resolves falsy) |
| Row visibility | Unchanged — only shown when an order ID is set |
| Python identifiers | Unchanged (`crowd_supply_order_id` stays snake_case; the naming rule governs prose, not symbols) |

Out of scope: renaming DB columns, showing the shuttle URL anywhere else,
backfilling order IDs.

## Design

### 1. Naming — "CrowdSupply" everywhere

- `Project.crowd_supply_order_id` gains
  `verbose_name="CrowdSupply Order ID"`. This single change fixes the
  auto-generated edit-form label and the admin column header.
- Prose updates: model help_text and validator message + docstrings, form
  help_text, detail-page label, both existing `docs/superpowers/` documents,
  and the PR title/body (via `gh api -X PATCH`; `gh pr edit` silently fails
  on this repo).
- The existing unmerged migration `projects/0058` is regenerated/edited in
  place to absorb the help_text/verbose_name change — no extra migration.

### 2. Shuttle model field (`wafer_space/shuttles/models.py`)

```python
crowd_supply_url = models.URLField(
    blank=True,
    default="",
    verbose_name="CrowdSupply URL",
    help_text="CrowdSupply campaign page for this shuttle run (optional).",
)
```

- One new migration `shuttles/0008` containing both the `AddField` and a
  `RunPython` data step:
  - forward: `Shuttle.objects.filter(name="G801").update(crowd_supply_url=...)`
    for each of G801/G802/G803 — a safe no-op for names not present in a
    given database (G803 may not exist everywhere yet);
  - reverse: blank the URL on those three names;
  - dependencies include `projects/0041_populate_shuttle_and_project_ids`
    (which seeds G801) so the data step runs after G801 exists on fresh
    databases, making seeding deterministic.
- `ShuttleAdmin`: add `crowd_supply_url` to the existing fieldsets so staff
  can set URLs for future shuttles without code changes.
- `populate_dev_data`: set the G801 URL so dev environments exercise the
  linked rendering; G899 stays blank to exercise the plain-text path.

### 3. Detail page (`wafer_space/templates/projects/project_detail.html`)

Within the existing conditional row in the Project Details card:

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

### 4. Removal

`Project.crowd_supply_order_url` (the account-scoped URL property) and its
tests are deleted — fully superseded by the shuttle link, dead code
otherwise.

## Testing (TDD)

- **Shuttle model** (create `shuttles/tests/test_models.py`, mirroring the
  source layout): new field defaults to blank; migration test asserting the
  data step sets all three URLs (create G801–G803 rows, run forward
  function, assert values). Shuttle factories/tests pass explicit `name=` to
  avoid the known G801 auto-sequence collision.
- **Views** (`projects/tests/test_views.py`):
  - detail page renders the order ID as a link to the shuttle URL when set;
  - detail page renders the order ID as plain text when the shuttle URL is
    blank;
  - detail page renders the order ID as plain text when the project has no
    shuttle at all (`shuttle` is nullable);
  - edit form contains the label "CrowdSupply Order ID".
- **Removal**: delete the `crowd_supply_order_url` property tests.
- **Sweep**: `grep -ri "crowd supply" wafer_space/` returns nothing, and the
  two 2026-06-09 docs are checked individually (identifiers like
  `crowd_supply_order_id` don't match the spaced form). This spec is
  excluded from the sweep — its Problem section intentionally quotes the
  banned spellings.
- Full gate per project policy: `make lint-fix && make lint &&
  make type-check && make test`, djlint on touched templates.

## Files touched

| File | Change |
| --- | --- |
| `wafer_space/projects/models.py` | verbose_name, help_text, validator message, docstrings; delete URL property |
| `wafer_space/projects/migrations/0058_*.py` | absorb field kwarg changes |
| `wafer_space/projects/forms.py` | help_text wording |
| `wafer_space/shuttles/models.py` | new `crowd_supply_url` field |
| `wafer_space/shuttles/migrations/0008_*.py` | AddField + data step (new) |
| `wafer_space/shuttles/admin.py` | expose field |
| `wafer_space/users/management/commands/populate_dev_data.py` | G801 dev URL |
| `wafer_space/templates/projects/project_detail.html` | label + link target |
| `wafer_space/projects/tests/test_models.py` | drop property tests |
| `wafer_space/projects/tests/test_views.py` | link/plain/label tests |
| `wafer_space/shuttles/tests/*` | field + data-migration tests |
| `docs/superpowers/*.md` | naming sweep |

---

## Revision (2026-07-03): detail-row rendering superseded by user feedback

After the original design shipped to PR #263, Tim revised the detail-page
rendering:

1. The "CrowdSupply Order ID:" row is **always shown**, even when the order
   ID is blank (a muted "Not set" placeholder renders in that case). The
   original "only shown when set" visibility rule above is superseded.
2. The **label** ("CrowdSupply Order ID:") is what links to the shuttle's
   CrowdSupply campaign page (plain text when the shuttle has no URL or the
   project has no shuttle).
3. The **order ID value** links to the buyer's order page
   `https://www.crowdsupply.com/account/order/<id>` — the
   `crowd_supply_order_url` property removed by this design was restored,
   along with its tests.

Implemented in commit `5fd750d` with a five-case view-test matrix
(label-linked + ID-linked / ID-linked only with blank shuttle URL / ID-linked
only with no shuttle / "Not set" with no shuttle / "Not set" with linked
label).

Additional revision (same date): the "CrowdSupply Order ID" label on the
project **edit form** also links to the shuttle's campaign page (new window,
`rel="noopener"`, no underline), via `format_html` in
`ProjectForm._link_crowd_supply_label()` — plain label on the create form or
when the shuttle has no URL. All CrowdSupply links open in a new window.
