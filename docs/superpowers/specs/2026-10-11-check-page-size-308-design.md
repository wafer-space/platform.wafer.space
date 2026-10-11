# Check logs: never render or poll the whole log

**Date:** 2026-10-11
**Issue:** [#308](https://github.com/wafer-space/platform.wafer.space/issues/308) (check-status and project pages render 16-25 MB of HTML, ballooning gunicorn workers to ~5 GB and OOM-killing prod)
**Priority:** P2 (Run #3 traffic risk, coordinator, 11 Oct)
**Status:** Approved by the coordinator 2026-10-11, with the amendment in section 4 (stream the saved log, never redirect to /media/)

## What makes the responses that large (main b3f868f)

All three oversized responses in the issue come from one field, `ManufacturabilityCheck.processing_logs` (`TextField`, `models.py:1957`). It holds a check's full precheck log and grows to megabytes. It is shipped whole, often many times per response:

| Response in #308 | Cause | Where |
|---|---|---|
| `GET /projects/<pk>/check-status/`, 16 MB, every 5 s | The polling **JSON** endpoint returns the whole log on every poll | `ManufacturabilityCheckStatusView`, `views.py:531-534`; polled by `project_detail.html:600-630` |
| `GET /projects/<pk>/`, 25 MB | The detail page renders `_manufacturability_check.html` for the latest check **and for every previous check** of each revision. Each inlines its full log in a `<pre>` (`_manufacturability_check.html:516-521`), and the history is inside closed `<details>`, which are still sent | `_file_display.html:167`, `:170-205` (`file.manufacturability_checks.all`) |
| `GET /projects/admin/summary/`, 5.4 GB worker | The queryset prefetches **every check of every active file** with all columns, logs included, unpaginated. The page then reads only `latest_manufacturability_check`, which issues its own query per project (`order_by`), so the prefetch is unused **and** each latest check's full row, log included, is loaded again | `ProjectAdminSummaryView.get_queryset`, `views.py:897-916`; `admin_summary.html:459-460`; `models.py:1311-1317` |

Python holds several copies of each log while rendering: the model attribute, the escaped template string, and the response buffer. That explains a worker of about 5 GB for a page of about 25 MB.

## Goals

- No response contains more than a bounded tail of any check's log: `LOG_TAIL_BYTES = 64 KiB` per displayed log, as a setting.
- The full log stays one click away for whoever may see the check: the owner and staff, as now.
- Pages that do not show logs never load them from the database.
- Behaviour is otherwise unchanged: the same status badges, the same history list, polling only while a check runs.

## Design

### 1. Database-side tail, never the whole field

The tail is computed in SQL, so Python never receives the full text:

```python
log_annotations = {
    "processing_logs_tail": Right("processing_logs", LOG_TAIL_BYTES),
    "processing_logs_length": Length("processing_logs"),
}
```

`Right` and `Length` work on PostgreSQL and SQLite and count characters, which is close enough to bytes for a display bound.

A queryset helper `ManufacturabilityCheck.objects.with_log_tail()` applies `.defer("processing_logs")` plus these annotations. A model property `log_tail_truncated` is true when `processing_logs_length > LOG_TAIL_BYTES`.

### 2. Polling endpoint returns only the tail

`ManufacturabilityCheckStatusView` loads the check via `with_log_tail()` and returns:
- `processing_logs_tail`, the last 64 KiB;
- `processing_logs_length`;
- `processing_logs_truncated`;
- the existing status fields.

The `processing_logs` key is removed. Its only consumer is the detail page JS, changed in the same PR. The JS writes the tail into `#processing-logs` and shows "Showing the last 64 KiB of N KiB. Full log." when truncated.

A 5-second poll then costs at most about 64 KiB, instead of up to 16 MB.

### 3. The check partial renders the tail, history renders no log

- `_manufacturability_check.html` renders `check.processing_logs_tail` with the same truncation note and a **Full log** link, instead of `check.processing_logs`.
- Checks in the "Previous Checks" history (`_file_display.html:180-205`) render **without** the log body; they show only the Full log link. History logs are rarely read, and a project with 20 re-runs would otherwise still carry 20 tails (1.3 MB).
- Both call sites pass checks from `with_log_tail()`: the detail view's file context and `file.manufacturability_checks` via a `Prefetch(..., queryset=ManufacturabilityCheck.objects.with_log_tail())`.

### 4. Full log download view

New `projects:check_log` (`/projects/<pk>/checks/<check_id>/log/`):
- the same permission as the detail page (`ProjectOwnerOrStaffMixin`);
- it streams `processing_logs` as `text/plain; charset=utf-8` with `Content-Disposition: attachment; filename="check_<id>.log"`.

When the check has a saved `log_file` (written at analysis by the `dock:rw:checks-save` worker), the view streams that file itself (`FileResponse` on the opened stored file, read-only).

It must **not** redirect to `log_file.url`. On production `/media/` is a public nginx alias with no access control (coordinator, 11 Oct; private item coord-10), so a redirect would bypass the permission check the view just made. A later X-Accel-Redirect change can replace the Python streaming with an internal nginx location.

The view only reads, so it fits the read-only web process (CLAUDE.md).

### 5. Admin summary loads no logs

`ProjectAdminSummaryView`:
- The prefetch of `manufacturability_checks` gets `.defer("processing_logs")` (`Prefetch(..., queryset=ManufacturabilityCheck.objects.defer("processing_logs"))`).
- The template reads the latest check from the prefetched list instead of the per-project query. A template-tag or model helper `latest_check_from(prefetched)` picks max `created_at`. This removes N queries as well as the logs.
- Pagination is out of scope: the page is staff-only, and once logs are gone its rows are small. It can be noted for later if the project count grows.

## Error handling

- A check with an empty log shows nothing, as now; length 0 means no truncation note.
- `check_log` for a check of another project returns 404. Anonymous users go to login. A user who can't see the project gets 403, as on the detail page.

## Tests (TDD, each watched failing first)

- **Size bound:** a check with a 5 MB log. The polling JSON is under 70 KiB, contains the last line, and does not contain the first.
- **Detail page:** a revision with 10 previous checks of 2 MB each renders under 200 KiB. The latest check's tail is present; no history log body is present; every history check has its Full log link.
- **Never loaded:** on the detail and admin-summary pages, a `CaptureQueriesContext` assertion that no SQL selects the `processing_logs` column, other than inside the `RIGHT`/`LENGTH` expressions.
- **Admin summary:** the query count does not grow with the number of checks per project (1 versus 10 checks).
- **check_log:**
  - the owner gets the full text, streamed and identical to the field;
  - a check with `log_file` streams that file's bytes through the view and never redirects (no `Location` header, no `/media/` URL in the response);
  - a non-owner gets 403;
  - another project's check gets 404;
  - the response is a `StreamingHttpResponse`.
- **Browser** (`tests/browser/`): a running check's detail page shows the tail and the "Full log" link, and polling updates the tail. A real headless browser test, plus a Playwright walk-through against a local server, with screenshots for the PR.

## Deploy notes

- No migration, no settings secrets, no hetzner-ansible change.
- Issue #308's defence-in-depth suggestion (`--max-requests` / `--max-requests-jitter` on gunicorn) lives in hetzner-ansible. It goes to the coordinator as a separate request and is not part of this PR.

## Out of scope

- Celery worker RSS growth (#308 mentions it as a separate issue).
- Pagination of the admin summary.
- Replacing polling with server-sent events.
