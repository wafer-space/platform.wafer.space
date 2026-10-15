# Request analytics

The platform records who fetched what, from where, and whether they were logged in, so questions such as "who downloaded this file?" can be answered later. It was added for issue #379.

## What is recorded

`RequestLogMiddleware` (`wafer_space/analytics/middleware.py`) writes one `RequestLog` row to PostgreSQL after the response for:

- every request by a logged-in user;
- every request to a file-serving view, whoever makes it and whatever the status: `projects:check_artifact`, `projects:check_log` and `projects:file_download`. A redirected or refused fetch is still an attempt.

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

## Bytes behind nginx

A file served through `X-Accel-Redirect` has no body in Django, so its row has no byte count. The bytes actually sent, including partial (Range) and aborted downloads, are in nginx's access log, which is joined by `request_id`. The nginx log format is set in the hetzner-ansible repository.

## Request id

Every response carries an `X-Request-ID` header. Where nginx is the sole ingress (`TRUST_X_REAL_IP`, the same switch that trusts `X-Real-IP`), the application keeps nginx's `$request_id` if it is 32 hexadecimal characters. Otherwise it generates a new one, so a client cannot choose the id.

## Who can read it

Staff, through the Django admin (Analytics → Request logs). It is read-only for everyone, superusers included. The admin has:

- a date hierarchy;
- filters for logged in or anonymous, URL name, status and method;
- search on path, username, client IP and request id.

## Retention

Rows are kept indefinitely, as the nginx access logs are. Client IP addresses and user agents are personal data. If a limit is set, run:

```bash
uv run python manage.py prune_request_logs --older-than DAYS
```

Nothing schedules this command yet.

## Failure

If a row cannot be written, the `DatabaseError` is logged at ERROR, which emails ADMINS through the rate-limited handler. The visitor still gets their page. Until migration `analytics 0001` has run, every logged request produces that error and no row.
