# Project List: Shuttle and State Columns

**Date:** 2026-07-16
**Status:** Approved

## Goal

Add two columns to the left of each project row on `/projects/`
(`ProjectListView`): the assigned shuttle number (e.g. G801) and the
project state (Draft, Submitted, etc.).

## Background

The projects page renders a Bootstrap **list-group**, not a `<table>`
(`wafer_space/templates/projects/project_list.html`). Each row shows the
project name, ownership badge, packaging badge, a Draft/Submitted badge
derived from `submitted_at`, the creation date, an optional CrowdSupply
link, and a truncated description.

The `Project` model already has:

- `shuttle` — nullable FK to `shuttles.Shuttle`; `shuttle.name` is the
  shuttle number ("G801").
- `status` — `Project.Status` with nine states: Draft, Submitted,
  Checking Manufacturability, Manufacturable, Not Manufacturable,
  Assigned to Shuttle, In Production, Completed, Cancelled.

The detail page (`project_detail.html`) renders `status` as a
colour-coded badge via an inline `{% if %}` chain; the list page does
not use `status` at all.

## Decisions

| Question | Decision |
|----------|----------|
| Layout | Keep the list-group; add two fixed-width flex cells on the left of each row (no `<table>` conversion). |
| State source | Full `status` field via `get_status_display`, not the `submitted_at`-derived badge. |
| Old inline Draft/Submitted badge | Removed (replaced by the state column). |
| Unassigned shuttle | Empty cell (fixed width keeps alignment). |
| Badge implementation | Shared partial template, following the existing `_packaging_badge.html` pattern. |

## Design

### 1. Shared status badge partial

New file `wafer_space/templates/projects/_status_badge.html` containing
the badge markup and colour mapping, used with
`{% include "projects/_status_badge.html" with project=project %}`.

Colour mapping preserves the detail page's current rendering exactly:

| Status | Class |
|--------|-------|
| draft | `bg-secondary` |
| submitted | `bg-primary` |
| manufacturable | `bg-success` |
| not_manufacturable | `bg-danger` |
| all others | `bg-info` |

`project_detail.html` replaces its inline `{% if %}` chain with this
include — zero visual change there.

### 2. List template layout

In `project_list.html`, each `list-group-item` becomes a horizontal
flex row:

- **Shuttle cell** (~4.5rem, `flex-shrink-0`):
  `{{ project.shuttle.name }}`; empty when `shuttle` is null.
- **State cell** (~9rem, `flex-shrink-0`): the status badge partial.
- **Content cell** (`flex-grow-1`): the existing title / badges / date /
  description block, unchanged except the inline `submitted_at`-based
  Draft/Submitted badge is removed.

The `stretched-link` on the project name keeps the whole row clickable;
the new cells live inside the same `position-relative` container. The
CS# link keeps its existing `z-index: 2` escape.

### 3. View

`ProjectListView.get_queryset`
(`wafer_space/projects/views.py`) adds `select_related("shuttle")` to
both the staff and regular-user branches to avoid an N+1 query on
`shuttle.name` (page size is 20).

### 4. Error handling

Nothing new. `shuttle` is nullable (renders as empty cell); `status`
has a default and `get_status_display` always resolves.

## Testing

- Update `wafer_space/projects/tests/test_views.py` (the tests around
  lines 139–160 assert the old badge markup, e.g.
  `title="Submitted for manufacturing"`): rewrite to assert the new
  status badge output for draft and submitted projects.
- Add assertions that a shuttle-assigned project renders the shuttle
  name in the list. Per repo convention, pass an explicit `name=` to
  `ShuttleFactory` to avoid the migration-seeded G801 collision.
- Verify the detail page still renders the status badge after switching
  to the shared partial.
- Run `uv run pre-commit run --files <templates>` before committing
  (djlint is not part of `make lint`).

## Out of scope

- Sorting/filtering by shuttle or status.
- Converting the page to a real `<table>`.
- Changing the admin summary page.
