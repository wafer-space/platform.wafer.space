# Manufacturable vs Submitted for Manufacturing

This document is the authoritative definition of two distinct concepts that
are easy to conflate. All code, UI, and documentation must use these
definitions. If other code or documentation disagrees with this document,
this document wins (and the other place should be fixed).

## The Two Concepts

### (a) Manufacturable — a property of a *file revision*

A **file revision** (a `ProjectFile` row) is **manufacturable** when the most
recent *finished* manufacturability check (`ManufacturabilityCheck`) for that
specific revision passed.

Manufacturability is always evaluated per file revision, never per project:

- Each file revision has its own independent check history (retries, DRC
  updates, re-runs).
- A revision's manufacturability can be in one of three states:
  - **Unknown** (`None`) — the revision has no finished check at all.
  - **Manufacturable** (`True`) — latest finished check passed.
  - **Not manufacturable** (`False`) — latest finished check failed.
- The verdict comes from the latest **finished** check: a newer check that
  is still pending/running does not reset an existing verdict; when it
  finishes, its result becomes the verdict.

### (b) Submitted to be manufactured — a designation held by the *project*

A project may designate **at most one** file revision as the one to be
manufactured. This is the `Project.submitted_file` foreign key, set when the
user clicks "Submit for Manufacturing" (`Project.submit()`).

- `submitted_file` is `NULL` → nothing has been submitted for manufacturing.
- `submitted_file` is set → that exact revision is what will be manufactured.

## The Rules

1. **A file revision must be manufacturable (a) before it can be submitted
   (b).** `Project.submit()` enforces this.
2. **Submission does not freeze the project.** After a revision has been
   submitted, new file revisions can still be uploaded. The newest upload
   becomes the *latest* revision; `submitted_file` keeps pointing at the
   previously submitted revision.
3. **A newer manufacturable revision can be re-submitted.** Doing so replaces
   the previously submitted revision as the one to be manufactured.
4. Because of rules 2 and 3, *"the latest revision"* and *"the submitted
   revision"* are routinely **different revisions**. This is a normal,
   expected state — not an error.

## Mapping to Code

| Concept | Code |
|---|---|
| File revision | `ProjectFile` |
| Latest file revision | `ProjectFile.is_active=True` (unique per project via `one_active_file_per_project`); `Project.latest_file` (falls back to the most recently uploaded revision if none is marked active) |
| Manufacturability of a revision (a) | `ProjectFile.latest_manufacturability_check.is_manufacturable` (only when that check is `FINISHED`) |
| Latest revision's check | `Project.latest_file_check` |
| Latest revision manufacturable? | `Project.latest_file_manufacturable` (`True`/`False`/`None`) |
| Submitted for manufacturing (b) | `Project.submitted_file` (+ `Project.submitted_at`) |
| Submitted revision's check | `Project.submitted_file_check` |
| Revision that manufacturing consumes | `Project.output_file` (submitted revision, falling back to latest) |

## Pitfalls

### Do not use `Project.status` to answer either question

`Project.status` is a coarse lifecycle field with a known quirk: when any
check finishes, `ManufacturabilityCheck.mark_finished()` overwrites the
status with `MANUFACTURABLE` / `NOT_MANUFACTURABLE` — including overwriting
`SUBMITTED`. Therefore:

- **"Has a file been submitted for manufacturing?"** → check
  `Project.submitted_file is not None`. Never `status == SUBMITTED`.
- **"Is the design manufacturable?"** → ask a specific file revision
  (usually `Project.latest_file_manufacturable`). Never infer it from
  `status` alone.

### Always say *which* revision a precheck status belongs to

Any UI that displays a precheck status is displaying the status of one
specific file revision. When the submitted revision differs from the latest
revision, showing a single unlabeled status is ambiguous and has caused real
confusion (e.g. a project with a passing check on its latest revision showing
"No check" because the page was reading the — nonexistent — submitted
revision).

## Display Rules: Slot Assignment Page

The shuttle Slot Assignment page (`/shuttles/<name>/assign/`) follows these
rules:

- **Submitted to Manufacturing column** (send icon): shows a green check when
  `Project.submitted_file` is set, a red cross otherwise. It reflects concept
  (b) only.
- **Status column**: always shows one line with the precheck status of the
  **latest** file revision. If a submitted revision exists and it is *not*
  the latest revision, a second line shows the precheck status of the
  **submitted** revision. Each line is labelled when both are shown.
- **Grid tiles and the assign-autocomplete indicator** (✓/?/✗) are keyed on
  the **latest** revision's manufacturability, consistent with the rest of
  the page. The grid tooltip carries the same information as the Status
  column: one `Status:` line for the latest revision, or `Latest:` plus
  `Submitted:` lines when the submitted revision differs. Note this is a display convention only: the revision that
  manufacturing actually consumes is `Project.output_file` (submitted,
  falling back to latest), and the reticle packaging service independently
  validates that revision's check before placing a project.
