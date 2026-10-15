# Request analytics

The platform records who fetched what, from where, and whether they were logged in, so questions such as "who downloaded this file?" can be answered later. It was added for issue #379.

## What is recorded

`RequestLogMiddleware` (`wafer_space/analytics/middleware.py`) writes one `RequestLog` row to PostgreSQL after the response for:

- every request by a logged-in user;
- every request to a file-serving view, whoever makes it and whatever the status: `projects:check_artifact`, `projects:check_log` and `projects:file_download`. A redirected or refused fetch is still an attempt. A fetch that the ToS check redirects before it reaches the view is still recorded under that view's name.

Each row holds:

| Field | What it is |
|-------|------------|
| `created_at` | When the request reached the application |
| `request_id` | nginx's `$request_id` from the `X-Request-ID` header, or one generated here. Joins the row to its nginx access-log line |
| `user`, `username` | The logged-in user and their username at that time; empty for anonymous requests. Never the email address |
| `client_ip` | The visitor's address, from the trusted `X-Real-IP` header (see `RealClientIPMiddleware`) |
| `method`, `path` | The request line. The query string is never stored, because OAuth callbacks carry codes there |
| `view_name`, `route_kwargs` | The URL name and its arguments, for example `projects:file_download` with the project and file ids |
| `status`, `bytes`, `duration_ms` | The response status, its size when the application knows it, and time spent in the application |
| `user_agent`, `referrer` | Those two headers, truncated. The referrer loses its query string |

## What is not recorded

- Request bodies (form fields, passwords, uploads).
- Any header other than `User-Agent` and `Referer`, including cookies and `Authorization`.
- Anonymous page views, `/static/` and `/health/`. The nginx access log has these.
- The request log's own admin pages, so reading the log does not add to it.
- One-time secrets in a URL path: allauth's email-confirmation key and password-reset key. For those pages the stored path is the URL pattern, and the key arguments are stored as `<redacted>`. The same applies to a referrer pointing at one of those pages.
- Credentials in a referrer URL (`user:password@`), and NUL characters anywhere.

## Bytes behind nginx

A file served through `X-Accel-Redirect` has no body in Django, so its row has no byte count. The bytes actually sent, including partial (Range) and aborted downloads, are in nginx's access log, which is joined by `request_id`. The nginx log format is set in the hetzner-ansible repository.

## Request id

Every response that reaches the middleware carries an `X-Request-ID` header. Responses from middleware earlier in the stack do not: WhiteNoise's static files and CommonMiddleware's `APPEND_SLASH` redirects. Where nginx is the sole ingress (`TRUST_X_REAL_IP`, the same switch that trusts `X-Real-IP`), the application keeps nginx's `$request_id` if it is 32 hexadecimal characters. Otherwise it generates a new one, so a client cannot choose the id.

## Who can read it

Staff, through the Django admin (Analytics → Request logs). It is read-only for everyone, superusers included. The admin has:

- a date hierarchy;
- filters for logged in or anonymous, URL name, status and method;
- search: an exact request id, client IP or username, or a path by its beginning, for example `/projects/<uuid>/`.

Every filter offers a fixed set of choices, so the page never scans the table for distinct values. A path search still scans the rows in the date range, so narrow the date first.

## Retention

Rows are kept indefinitely, as the nginx access logs are. Client IP addresses and user agents are personal data. If a limit is set, run:

```bash
uv run python manage.py prune_request_logs --older-than DAYS
```

Nothing schedules this command yet.

## Cost

Each row is written in its own transaction with `SET LOCAL synchronous_commit TO OFF`, so the request does not wait for PostgreSQL's WAL flush. Measured on 15 Oct 2026 against PostgreSQL 17, over 1,000 requests: the plain INSERT added about 17 ms a request, almost all of it the flush; this way it adds about 1.4 ms. The trade-off: a database server crash can lose the last fraction of a second of request log rows. It cannot corrupt them, and no other table is affected.

## Failure

If a row cannot be written, the `DatabaseError` is logged at ERROR, which emails ADMINS through the rate-limited handler. The visitor still gets their page. Until migration `analytics 0001` has run, every logged request produces that error and no row.
