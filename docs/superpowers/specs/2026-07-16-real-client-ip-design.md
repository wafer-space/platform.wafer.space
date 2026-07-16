# Real client IP from trusted proxy header — Design

**Date:** 2026-07-16
**Branch:** `issue/274-real-client-ip` (base `main`)
**Status:** Approved by user (design discussion in session)
**Issue:** [#274](https://github.com/wafer-space/platform.wafer.space/issues/274)
**Depends on:** [hetzner-ansible#132](https://github.com/mithro/hetzner-ansible/pull/132),
[hetzner-ansible#133](https://github.com/mithro/hetzner-ansible/pull/133)

## Problem

Django does not surface the **real client IP**. It reads `REMOTE_ADDR`,
which — behind gunicorn on a unix socket — is empty or local. The only
proxy setting configured today is `SECURE_PROXY_SSL_HEADER` (stage/prod),
which fixes the request *scheme* only, not the IP. Any feature relying on
client IP (audit logs, rate limiting, abuse handling, geolocation) sees the
wrong value.

Verified on prod + test-platform: the platform nginx access log records
IPv4 requests as the hypervisor bridge `192.168.27.1`; the real visitor IP
never reaches the application.

### Secondary problem: spoofable, duplicated extraction

Client-IP extraction is duplicated across **four** sites, each reading
`X-Forwarded-For` and taking `split(",")[0]` — the *first* entry:

- `wafer_space/projects/views_compliance.py` — `get_client_ip()` helper
- `wafer_space/projects/mixins.py` — two inline blocks (access logging)
- `wafer_space/legal/views.py` — one inline block (TOS acceptance)

The first `X-Forwarded-For` entry is **client-controlled**. nginx appends
the IP it saw, so a request carrying `X-Forwarded-For: 1.2.3.4` arrives as
`1.2.3.4, <real-ip>` and the first-entry logic records the **spoofed**
value. Because these sites prefer `X-Forwarded-For` *over* `REMOTE_ADDR`,
fixing `REMOTE_ADDR` alone would be bypassed. Both problems must be fixed
together.

## Infra context (already being handled)

The proxy layer is fixed separately, outside this repo:

- **hetzner-ansible#132** — hypervisor SNI proxy uses transparent source
  bind, so the VM sees the real connecting IP (the Cloudflare edge for
  proxied traffic, the real client for direct traffic).
- **hetzner-ansible#133** — platform nginx `real_ip` scoped to Cloudflare's
  published ranges:

  ```nginx
  set_real_ip_from <Cloudflare published ranges>;
  real_ip_header   CF-Connecting-IP;
  ```

  nginx then forwards the resolved visitor to gunicorn in `X-Real-IP` and
  `X-Forwarded-For`.

This repo's remaining job: **consume `X-Real-IP`**.

## Requirements

1. The app's notion of client IP shows the real visitor for both
   Cloudflare-proxied and direct-origin requests.
2. IPv6 (which reaches the VM directly) continues to show the real visitor.
3. The client-supplied `X-Forwarded-For` spoofing path is removed.
4. Client-IP extraction has a single source of truth.
5. Dev and test behaviour is unchanged (no nginx there).
6. Use an existing, maintained library rather than hand-rolled IP parsing.

## Design

### 1. Dependency — `django-ipware`

Add `django-ipware==7.0.1` to `pyproject.toml` dependencies (`uv lock`).
Used **only** inside the middleware, for IP parsing/validation.

`get_client_ip()` returns `(ip, is_routable)`, validating address **format**
and **routability**. It has no Cloudflare awareness — by design; see
"Trust model" below.

### 2. Middleware — `wafer_space/core/middleware.py`

New `RealClientIPMiddleware`, following the existing
`TOSAcceptanceMiddleware` shape:

```python
class RealClientIPMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.TRUST_X_REAL_IP:
            client_ip, _is_routable = ipware_get_client_ip(
                request,
                request_header_order=("HTTP_X_REAL_IP",),
            )
            if client_ip:
                request.META["REMOTE_ADDR"] = client_ip
        return self.get_response(request)
```

Restricting `request_header_order` to `HTTP_X_REAL_IP` means ipware **never**
consults the spoofable `X-Forwarded-For`. If the header is absent or
malformed, ipware returns `None` and `REMOTE_ADDR` is left untouched — we do
not fall back to a spoofable source.

Registered **first** in `MIDDLEWARE` (`config/settings/base.py`) so the
corrected `REMOTE_ADDR` is visible to every later middleware and view.

### 3. Shared helper — `wafer_space/core/utils.py`

```python
def get_client_ip(request: HttpRequest) -> str | None:
    """Return the client IP, as resolved by RealClientIPMiddleware."""
    return request.META.get("REMOTE_ADDR")
```

Single source of truth for all call sites. The old
`views_compliance.get_client_ip` (with its `X-Forwarded-For` logic) is
**deleted** and replaced by this import.

`wafer_space/core/` is a plain module namespace (not an installed app),
which is sufficient: middleware is referenced by dotted path and the helper
is a plain function.

### 4. Settings — `TRUST_X_REAL_IP`

| File | Value | Rationale |
|------|-------|-----------|
| `config/settings/base.py` | `False` | Fail-safe default, matching the repo's "off/None in base, override per env" convention |
| `config/settings/stage.py` | `True` | nginx is sole ingress and sets `X-Real-IP` |
| `config/settings/prod.py` | `True` | as above |
| `config/settings/dev.py` | inherits `False` | no nginx locally |
| `config/settings/pytest.py` | inherits `False` | tests opt in via `override_settings` |

When `False`, the middleware is a pass-through: a spoofed `X-Real-IP` is
ignored entirely.

### 5. Call-site refactor

All four sites drop their inline `X-Forwarded-For` logic and call the shared
helper:

- `wafer_space/projects/views_compliance.py` — import helper; delete local one
- `wafer_space/projects/mixins.py` — replace both inline blocks
- `wafer_space/legal/views.py` — replace inline block

### 6. Trust model (lean — validation stays at nginx)

Layered, with each control at the layer that owns it:

| Layer | Control |
|-------|---------|
| nginx | `set_real_ip_from <CF ranges>` validates the **connecting peer** is Cloudflare before trusting `CF-Connecting-IP`; then **overwrites** `X-Real-IP` with the resolved visitor |
| gunicorn | listens on a **local unix socket** — only nginx can reach it |
| Django | trusts `X-Real-IP` *because of* the layers above, gated by `TRUST_X_REAL_IP`; ipware validates format/routability only |

A client sending its own `X-Real-IP` through the front door has it
overwritten by nginx, so the forged value never survives. Injecting a fake
value requires bypassing nginx and hitting the socket directly — i.e.
already having host access. That socket isolation is the trust boundary.

**Cloudflare range validation is deliberately *not* done in Django:**

1. It would duplicate nginx's `set_real_ip_from`.
2. Cloudflare's ranges drift; a second in-app copy would need maintaining.
3. It would be **semantically wrong**. The value in `X-Real-IP` is the
   *resolved end visitor*, not a Cloudflare edge IP. Checking it against CF
   ranges would reject every legitimate request and break direct-origin
   traffic (requirement 1). The CF-range check belongs against the
   **connecting peer**, which only nginx can see.

### 7. Rejected alternatives

- **django-xff** (v1.5.0, Feb 2025) — is an off-the-shelf middleware that
  rewrites `REMOTE_ADDR`, but reads **only** `X-Forwarded-For` via
  proxy-depth counting; it cannot read `X-Real-IP`. Depth counting is
  fragile if the proxy chain length changes, whereas `X-Real-IP` is a single
  authoritative value. Django 5.2 is also absent from its classifiers.
- **django-ipware as a plain helper (no middleware)** — would fix only the
  call sites we route through it, leaving `REMOTE_ADDR` wrong for any future
  consumer (rate limiting, abuse handling, geolocation — all named in #274).
- **Hand-rolled header parsing** — rejected per requirement 6.

## Testing (TDD)

### New — `wafer_space/core/tests/test_middleware.py`

| Case | Expectation |
|------|-------------|
| `TRUST_X_REAL_IP=True`, `X-Real-IP` present | `REMOTE_ADDR` rewritten to that value |
| `TRUST_X_REAL_IP=True`, IPv6 `X-Real-IP` | `REMOTE_ADDR` rewritten correctly |
| `TRUST_X_REAL_IP=True`, header absent | `REMOTE_ADDR` unchanged |
| `TRUST_X_REAL_IP=True`, malformed `X-Real-IP` | `REMOTE_ADDR` unchanged |
| `TRUST_X_REAL_IP=True`, spoofed `X-Forwarded-For` only | `REMOTE_ADDR` unchanged (XFF never consulted) |
| **`TRUST_X_REAL_IP=False`, `X-Real-IP` present** | **`REMOTE_ADDR` unchanged (no trust)** |

### New — `wafer_space/core/tests/test_utils.py` (extend)

`get_client_ip()` returns `REMOTE_ADDR`; returns `None` when absent.

### Updated — existing tests asserting `X-Forwarded-For` precedence

These encode the **old, spoofable** behaviour and must be rewritten to the
new model (resolution happens in middleware from `X-Real-IP`; the helper
returns `REMOTE_ADDR`):

- `wafer_space/projects/tests/test_views_compliance.py`
- `wafer_space/projects/tests/test_mixins.py`
- `wafer_space/legal/tests/test_views.py`
- `wafer_space/legal/tests/test_oauth_tos_flow.py`

Baseline before changes: 79 passed.

## Files touched

| File | Change |
|------|--------|
| `pyproject.toml` | add `django-ipware==7.0.1` |
| `uv.lock` | regenerated |
| `wafer_space/core/middleware.py` | **new** — `RealClientIPMiddleware` |
| `wafer_space/core/utils.py` | add `get_client_ip()` |
| `wafer_space/core/tests/test_middleware.py` | **new** |
| `wafer_space/core/tests/test_utils.py` | extend |
| `config/settings/base.py` | register middleware (first); `TRUST_X_REAL_IP = False` |
| `config/settings/stage.py` | `TRUST_X_REAL_IP = True` |
| `config/settings/prod.py` | `TRUST_X_REAL_IP = True` |
| `wafer_space/projects/views_compliance.py` | delete local helper; import shared |
| `wafer_space/projects/mixins.py` | replace 2 inline blocks |
| `wafer_space/legal/views.py` | replace inline block |
| `wafer_space/projects/tests/test_views_compliance.py` | update |
| `wafer_space/projects/tests/test_mixins.py` | update |
| `wafer_space/legal/tests/test_views.py` | update |
| `wafer_space/legal/tests/test_oauth_tos_flow.py` | update |

## Edge cases

- **No `X-Real-IP`** (misconfig, or direct-to-origin without nginx) →
  `REMOTE_ADDR` left as-is. Never fall back to spoofable `X-Forwarded-For`.
- **IPv6 direct to VM** → nginx sets `X-Real-IP` to the real client; flows
  through unchanged.
- **Malformed `X-Real-IP`** → ipware returns `None`; `REMOTE_ADDR` untouched.
- **Private/non-routable `X-Real-IP`** → still recorded. `is_routable` is
  ignored deliberately: on stage/test the real visitor may legitimately be
  an internal address, and dropping it would lose audit data.

## Assumptions to verify before trusting in prod

1. **nginx overwrites `X-Real-IP`** (`proxy_set_header X-Real-IP
   $remote_addr`) rather than passing a client-supplied value through. The
   whole trust model depends on this; confirm against the #133 config.
2. hetzner-ansible #132 + #133 are deployed to `doc` before
   `TRUST_X_REAL_IP=True` is relied upon (until then the middleware is
   harmless: no `X-Real-IP` means no rewrite).
3. `django-ipware` 7.0.1 accepts `request_header_order` as specified —
   verify against the installed version during implementation.

## Out of scope

- Consuming the IP for new features (rate limiting, geolocation) — #274 only
  requires the IP be *correct and available*.
- The nginx/hypervisor changes themselves (hetzner-ansible #132/#133).
