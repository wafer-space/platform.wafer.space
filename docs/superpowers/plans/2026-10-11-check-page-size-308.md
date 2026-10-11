# Check Log Size (#308) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** No response carries more than a 64 KiB tail of any check's log; pages that show no logs never load them.

**Architecture:**
- A queryset helper annotates a SQL-side tail and length and defers the full field.
- The polling JSON, the check partial and the admin summary use it.
- A read-only `check_log` view streams the full log (saved file or DB slices) behind the detail page's permission check.

**Tech Stack:** Django 5.2 ORM functions (`Right`, `Length`, `Substr`), `FileResponse` / `StreamingHttpResponse`, pytest, the Selenium browser tests.

**Spec:** `docs/superpowers/specs/2026-10-11-check-page-size-308-design.md` (approved 2026-10-11, with the section 4 amendment).

## Global Constraints

- `LOG_TAIL_CHARS = 64 * 1024`, in `config/settings/base.py`; a setting, not `.env`.
- Never redirect to `log_file.url` or any `/media/` URL for logs. Stream through the view.
- Views only read; no file writes (CLAUDE.md, read-only web process).
- Execution: native, no sub-agents until the final review (coordinator, quota). One gate at a time; commit only after `EXIT=0`.

## Review Focus

1. A log shorter than the tail: no truncation note, and the full text is shown (Task 1).
2. A log with multi-byte UTF-8 near the cut: no broken characters, because `Right` counts characters (Task 1).
3. A running check (no `log_file` yet): the full-log view streams from the DB in slices (Task 4).
4. Another project's check id on the URL: 404, not someone else's log (Task 4).
5. A history check: no log body in the HTML, only the link (Task 3).

---

### Task 1: `with_log_tail()` and the tail properties
- Files: `wafer_space/projects/models.py` (a `ManufacturabilityCheckQuerySet.with_log_tail()`, the manager, properties `log_tail` / `log_tail_truncated`), `config/settings/base.py`, tests in `wafer_space/projects/tests/test_models.py`.
- Tests:
  - a 200 KiB log gives a 64 KiB tail ending with the last line, with `truncated` True;
  - a short log gives the whole text, with `truncated` False;
  - a multi-byte character survives the cut;
  - the SQL of `with_log_tail()` never selects the bare `processing_logs` column (`str(qs.query)`).

### Task 2: Polling JSON returns the tail
- Files: `ManufacturabilityCheckStatusView` in `views.py`; the polling JS in `project_detail.html`; tests in `test_views.py`.
- Tests:
  - a 5 MB log gives JSON under 70 KiB, with the last line present and the first absent;
  - the keys are `processing_logs_tail`, `processing_logs_length` and `processing_logs_truncated`;
  - `processing_logs` is absent.

### Task 3: Partial and history render bounded logs
- Files: `_manufacturability_check.html` (the tail, the note, and the Full log link to `check_log`, replacing `log_file.url`); `_file_display.html` (history with a `show_log=False` flag); the detail view / `_file_display` context, prefetching `manufacturability_checks` via `with_log_tail()`. Run pre-commit on the templates.
- Tests:
  - a revision with 10 previous 2 MB checks renders the detail page under 200 KiB;
  - the latest tail is present, and no history log body is;
  - no `/media/` log URL appears in the page.

### Task 4: `check_log` view
- Files: `views.py` (`CheckLogView`), `urls.py` (`<uuid:pk>/checks/<int:check_id>/log/`, name `check_log`), tests.
- Behaviour:
  - permission as in `ProjectOwnerOrStaffMixin`;
  - the check must belong to the project, else 404;
  - with a saved `log_file`, a `FileResponse(check.log_file.open("rb"), as_attachment=True, filename=f"check_{id}.log")`;
  - otherwise a `StreamingHttpResponse` of 1 MiB `Substr` slices;
  - `text/plain; charset=utf-8` in both cases.
- Tests:
  - the owner gets the full text, streamed;
  - a saved file is streamed with no `Location` header;
  - a non-owner gets 403;
  - another project's check gets 404;
  - an anonymous user goes to login;
  - a DB-streamed body equals the field across several slices.

### Task 5: Admin summary loads no logs
- Files: `ProjectAdminSummaryView.get_queryset` (the prefetch deferring `processing_logs`), plus a template tag or helper reading the latest check from the prefetched list; `admin_summary.html`.
- Tests:
  - the query count with 1 versus 10 checks per project is equal;
  - no query selects `processing_logs`.

### Task 6: Browser test, review, PR
- `tests/browser/`: a running check with a long log shows the truncation note and the Full log link, and polling replaces the tail.
- A Playwright walk-through against a local server, with screenshots.
- An independent Sonnet review, then the PR body and the slot.
