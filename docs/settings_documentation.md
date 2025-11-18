# Django Settings Catalog and Environment Configuration

## Executive Summary

This document catalogs all Django settings across the four environments in the wafer.space test platform project.

**Environments:**
- `dev.py` - Local development (renamed from `local.py`)
- `pytest.py` - Test execution (renamed from `test.py`)
- `stage.py` - Staging deployment at test-platform.wafer.space (NEW)
- `prod.py` - Production deployment at platform.wafer.space (renamed from `production.py`)

**Key Principles:**
- **Settings-based OAuth configuration** (not database-based)
- **PostgreSQL as Celery broker** (Redis/RabbitMQ are banned)
- **Separate OAuth apps** for each deployed environment (dev, stage, prod)
- **Separate secrets** for each deployed environment
- **Explicit configuration** over DRY (cookiecutter-django philosophy)

## File Structure

```
config/settings/
├── __init__.py
├── base.py           # Universal settings, shared across all environments
├── dev.py            # Local development
├── pytest.py         # Test execution
├── stage.py          # Staging deployment at test-platform.wafer.space
└── prod.py           # Production deployment at platform.wafer.space
```

## Unified Settings Structure

All environment files (`dev.py`, `pytest.py`, `stage.py`, `prod.py`) follow the same section order for easy comparison and diffing:

1. Core Django (DEBUG, SECRET_KEY, ALLOWED_HOSTS, SITE_URL)
2. Databases
3. Caches
4. Security (SECURE_*, cookies)
5. Static files/Storage
6. Email
7. Admin
8. Installed Apps / Middleware
9. Templates
10. Authentication
11. Media
12. Celery
13. Logging
14. OAuth Providers
15. Development tools (dev only)

**Benefits:**
- Identical section headers make differences obvious when diffing
- Comments indicate when settings use base.py defaults
- Easy to spot missing configurations across environments

## Environment Selection

```bash
# Development
export DJANGO_SETTINGS_MODULE=config.settings.dev
make runserver

# Testing (pytest)
# Automatically uses config.settings.pytest via pyproject.toml

# Staging
export DJANGO_SETTINGS_MODULE=config.settings.stage
# Configured in systemd service on test-platform.wafer.space

# Production
export DJANGO_SETTINGS_MODULE=config.settings.prod
# Configured in systemd service on platform.wafer.space
```

## Settings Catalog by Category

### 1. CORE DJANGO SETTINGS

| Setting | dev | pytest | stage | prod | Notes |
|---------|-----|--------|-------|------|-------|
| `DEBUG` | `True` | Inherits base (`None`) | `False` | Inherits base (`None`) | Set to None in base, must be set in each environment |
| `SECRET_KEY` | **Required from env** | **Required from env** | **Required from env** | **Required from env** | Different keys per environment |
| `ALLOWED_HOSTS` | `["localhost", "0.0.0.0", "127.0.0.1", "platform.wafer.space", "test-platform.wafer.space"]` | `["testserver"]` | `["test-platform.wafer.space", "buddy.test-platform.wafer.space", "doc.test-platform.wafer.space"]` | `["platform.wafer.space"]` | Dev includes prod domains for local testing |
| `SITE_URL` | Inherits base (`http://localhost:8081`) | Inherits base (`http://localhost:8081`) | `https://test-platform.wafer.space` | `https://platform.wafer.space` | Dev uses HTTP for simplicity, deployed envs use HTTPS |
| `TIME_ZONE` | `UTC` | `UTC` | `UTC` | `UTC` | Universal |
| `USE_I18N` | `True` | `True` | `True` | `True` | Universal |
| `USE_TZ` | `True` | `True` | `True` | `True` | Universal |
| `DEFAULT_AUTO_FIELD` | `BigAutoField` | `BigAutoField` | `BigAutoField` | `BigAutoField` | Universal |

**Installed Apps:**
- **dev**: base + `debug_toolbar` + `django_extensions` + `whitenoise.runserver_nostatic`
- **pytest**: base only
- **stage**: base + `anymail`
- **prod**: base + `anymail`

### 2. DATABASE CONFIGURATION

| Setting | dev | pytest | stage | prod | Notes |
|---------|-----|--------|-------|------|-------|
| `ENGINE` | SQLite3 | SQLite3 | PostgreSQL | PostgreSQL | SQLite for dev/test speed |
| `NAME` | `db.sqlite3` | `:memory:` | From env | From env | In-memory for test speed |
| `ATOMIC_REQUESTS` | `True` | `True` | `True` | `True` | Universal data integrity |
| `CONN_MAX_AGE` | Not set (0) | Not set (0) | `60` (env) | `60` (env) | Connection pooling for deployed |
| `timeout` | `30` | `30` | N/A | N/A | SQLite lock timeout |
| `OPTIONS.init_command` | `PRAGMA journal_mode=WAL;` | Not set | Not set | Not set | WAL mode for SQLite concurrent access |

### 3. CACHING

| Setting | dev | pytest | stage | prod | Notes |
|---------|-----|--------|-------|------|-------|
| `BACKEND` | `LocMemCache` | `LocMemCache` | `LocMemCache` | `LocMemCache` | Universal: In-memory sufficient for current scale |
| `LOCATION` | `"wafer-space-cache"` | `"wafer-space-cache"` | `"wafer-space-cache"` | `"wafer-space-cache"` | Universal: Defined in base.py |

### 4. SECURITY SETTINGS

| Setting | dev | pytest | stage | prod | Notes |
|---------|-----|--------|-------|------|-------|
| `SESSION_COOKIE_HTTPONLY` | `True` | `True` | `True` | `True` | Universal security |
| `SESSION_COOKIE_SECURE` | `False` | `False` | `True` | `True` | HTTPS enforcement for deployed |
| `SESSION_COOKIE_NAME` | Default | Default | `__Secure-sessionid` | `__Secure-sessionid` | Secure prefix for deployed |
| `CSRF_COOKIE_HTTPONLY` | `True` | `True` | `True` | `True` | Universal security |
| `CSRF_COOKIE_SECURE` | `False` | `False` | `True` | `True` | HTTPS enforcement for deployed |
| `CSRF_COOKIE_NAME` | Default | Default | `__Secure-csrftoken` | `__Secure-csrftoken` | Secure prefix for deployed |
| `X_FRAME_OPTIONS` | `DENY` | `DENY` | `DENY` | `DENY` | Universal security |
| `SECURE_PROXY_SSL_HEADER` | Not set | Not set | `("HTTP_X_FORWARDED_PROTO", "https")` | Same | For nginx reverse proxy |
| `SECURE_SSL_REDIRECT` | Not set | Not set | `True` | `True` | HTTPS enforcement |
| `SECURE_HSTS_SECONDS` | Not set | Not set | `3600` (1 hour) | `31536000` (1 year) | Production: 1 year required for preload list |
| `SECURE_HSTS_INCLUDE_SUBDOMAINS` | Not set | Not set | `True` | `True` | Comprehensive HTTPS |
| `SECURE_HSTS_PRELOAD` | Not set | Not set | `False` | `True` | Staging: preload disabled (testing), Production: enabled |
| `SECURE_CONTENT_TYPE_NOSNIFF` | Not set | Not set | `True` | `True` | Prevent security vulnerabilities |

### 5. PASSWORD HASHING

| Setting | dev | pytest | stage | prod | Notes |
|---------|-----|--------|-------|------|-------|
| `PASSWORD_HASHERS` | Argon2, PBKDF2, etc. | `MD5PasswordHasher` only | Argon2, PBKDF2, etc. | Argon2, PBKDF2, etc. | Fast MD5 for tests only |

### 6. EMAIL CONFIGURATION

| Setting | dev | pytest | stage | prod | Notes |
|---------|-----|--------|-------|------|-------|
| `EMAIL_BACKEND` | `console.EmailBackend` | `locmem.EmailBackend` | `anymail.backends.mailgun.EmailBackend` | `anymail.backends.mailgun.EmailBackend` | Set to None in base, must be set in each environment |
| `EMAIL_TIMEOUT` | `5` | `5` | `5` | `5` | Universal |
| `DEFAULT_FROM_EMAIL` | Inherits base | Inherits base | Inherits base | Inherits base | Universal: `wafer.space Platform <noreply@platform.wafer.space>` |
| `SERVER_EMAIL` | Inherits base | Inherits base | Inherits base | Inherits base | Universal: Same as DEFAULT_FROM_EMAIL |
| `EMAIL_SUBJECT_PREFIX` | Inherits base | Inherits base | Inherits base | Inherits base | Universal: `[wafer.space] ` |
| `ANYMAIL` | Not set | Not set | Mailgun config: domain `mg.wafer.space`, API key from env | Same as stage | Mailgun credentials per environment |

### 7. STATIC & MEDIA FILES

| Setting | dev | pytest | stage | prod | Notes |
|---------|-----|--------|-------|------|-------|
| `STATIC_ROOT` | `BASE_DIR/staticfiles` | Same | Same | Same | Universal |
| `STATIC_URL` | `/static/` | `/static/` | `/static/` | `/static/` | Universal |
| `MEDIA_ROOT` | `APPS_DIR/media` | Same | Same | Same | Universal |
| `MEDIA_URL` | `/media/` | `http://media.testserver/` | `/media/` | `/media/` | Testserver URL for pytest |
| `STORAGES['staticfiles']` | Default | Default | `CompressedManifestStaticFilesStorage` | `CompressedManifestStaticFilesStorage` | WhiteNoise compression for deployed |

### 8. ADMIN CONFIGURATION

| Setting | dev | pytest | stage | prod | Notes |
|---------|-----|--------|-------|------|-------|
| `ADMIN_URL` | `admin/` | `admin/` | Inherits base (`admin/`) | Inherits base (`admin/`) | Universal: Default admin URL |
| `ADMINS` | Tim Ansell | Same | Same | Same | Universal |
| `MANAGERS` | Same as ADMINS | Same | Same | Same | Universal |
| `DJANGO_ADMIN_FORCE_ALLAUTH` | `False` (env) | `False` (env) | `False` (env) | `False` (env) | Configurable |

### 9. LOGGING

| Setting | dev | pytest | stage | prod | Notes |
|---------|-----|--------|-------|------|-------|
| `LOGGING` | Base config (console, INFO) | Same | Enhanced: console + mail_admins on ERROR | Same as stage | Email admins on errors in deployed |

### 10. OAUTH PROVIDERS (django-allauth)

**Critical Note:** This project uses **settings-based OAuth configuration** (not database-based). All provider settings are in `SOCIALACCOUNT_PROVIDERS` dictionary.

**OAuth Apps:** Separate OAuth applications exist for each deployed environment:
- **Dev apps**: localhost:8081 callback URLs
- **Stage apps**: test-platform.wafer.space callback URLs
- **Prod apps**: platform.wafer.space callback URLs

**Important:** All OAuth client IDs and secrets are set to `None` in `base.py`. Each environment MUST override these values.

| Provider | dev Client ID | pytest Client ID | stage Client ID | prod Client ID | Notes |
|----------|---------------|------------------|-----------------|----------------|-------|
| **GitHub** | `Ov23liLB7RRJUzku13dU` (dev.py) | `test_github_client_id` | `Ov23lisQ91kx0M3Dhqwd` (stage.py) | `Ov23linEhI33aev2uGSU` (prod.py) | Separate apps per environment |
| **GitLab** | `2a29dee626...a4962aaa` (dev.py) | `test_gitlab_client_id` | `6b111b2573...b06cf708` (stage.py) | `f0fde384db...fbea6c16` (prod.py) | Separate apps per environment |
| **Google** | `62545893239-jiesk...nqhc` (dev.py) | `test_google_client_id` | `62545893239-00nmu...jo0ca` (stage.py) | `62545893239-pgg1l...qua2` (prod.py) | Separate apps per environment |
| **LinkedIn** | `86j973nx41hlk7` (dev.py) | `test_linkedin_client_id` | `86r16sb9k5fkwt` (stage.py) | `86q1gs3uqhpqt1` (prod.py) | OpenID Connect, separate apps |
| **Discord** | `1426055950221054052` (dev.py) | `test_discord_client_id` | `1440161777756405851` (stage.py) | `1426065281138167841` (prod.py) | Separate apps per environment |

**OAuth Secrets:** All environments load secrets from environment variables:
- **base.py**: All client IDs and secrets set to `None` (must be overridden)
- **dev**: Client IDs hardcoded in dev.py, secrets **required from env**
- **pytest**: Client IDs and secrets hardcoded in pytest.py
- **stage**: Client IDs hardcoded in stage.py, secrets **required from env** (loaded from `/home/django/.secrets/`)
- **prod**: Client IDs hardcoded in prod.py, secrets **required from env** (loaded from `/home/django/.secrets/`)

**OAuth Scopes:** Consistent across all environments per provider:
- GitHub: `["user:email"]`
- GitLab: `["read_user", "email"]`
- Google: `["profile", "email"]`
- Discord: `["identify", "email"]`
- LinkedIn: OpenID Connect scopes (automatic)

### 11. CELERY CONFIGURATION

| Setting | dev | pytest | stage | prod | Notes |
|---------|-----|--------|-------|------|-------|
| `CELERY_BROKER_URL` | `sqla+sqlite:///db.sqlite3` | Inherits base (PostgreSQL format) | `sqla+postgresql://...` | `sqla+postgresql://...` | SQLite for dev, PostgreSQL for deployed |
| `CELERY_RESULT_BACKEND` | `django-db` | Same | Same | Same | Universal: Django database |
| `CELERY_CACHE_BACKEND` | `django-cache` | Same | Same | Same | Universal: Django cache |
| `CELERY_TASK_ALWAYS_EAGER` | `False` | `True` | `False` | `False` | Synchronous for tests only |
| `CELERY_TASK_EAGER_PROPAGATES` | `True` | `True` | `True` | `True` | Universal |
| `CELERY_TASK_ROUTES` | projects→manufacturability, referrals→referrals | Same | Same | Same | Universal queue routing |
| `CELERY_RESULT_EXPIRES` | `3600` (1 hour) | Same | Same | Same | Universal |
| `CELERY_TASK_TIME_LIMIT` | `1800` (30 min) | Same | Same | Same | Universal hard limit |
| `CELERY_TASK_SOFT_TIME_LIMIT` | `1500` (25 min) | Same | Same | Same | Universal soft limit |

### 12. APPLICATION-SPECIFIC SETTINGS

| Setting | dev | pytest | stage | prod | Notes |
|---------|-----|--------|-------|------|-------|
| `DOWNLOAD_RETRY_BASE_DELAY_MINUTES` | `0.5` (30 sec) | `5` (5 min) | `0.5` (30 sec) | `5` (5 min) | Faster retries for dev and stage |
| `DOWNLOAD_RETRY_BACKOFF_MULTIPLIER` | `3` | Same | Same | Same | Universal |
| `DOWNLOAD_RETRY_CHECK_INTERVAL_SECONDS` | `30` | `300` | `30` | `300` | Faster checks for dev and stage |
| `DOWNLOAD_STATE_CHECK_INTERVAL_SECONDS` | `30` | `60` | `30` | `60` | Faster checks for dev and stage |
| `CELERY_BEAT_SCHEDULE` | Dev intervals (30s) | Base intervals | Stage intervals (30s) | Base intervals | Faster schedule for dev and stage |

### 13. MIDDLEWARE

| Setting | dev | pytest | stage | prod | Notes |
|---------|-----|--------|-------|------|-------|
| `MIDDLEWARE` | Base + `DebugToolbarMiddleware` | Base only | Base only | Base only | Debug toolbar only in dev |

### 14. DEBUG TOOLS

| Setting | dev | pytest | stage | prod | Notes |
|---------|-----|--------|-------|------|-------|
| `DEBUG_TOOLBAR_CONFIG` | Configured | Not set | Not set | Not set | Dev only |
| `INTERNAL_IPS` | `["127.0.0.1", "10.0.2.2"]` | Not set | Not set | Not set | Dev only |

## Environment Variables Matrix

### Required Environment Variables by Environment

| Variable | dev (.env) | pytest | stage (.env) | prod (.env) | Notes |
|----------|-----------|---------|--------------|-------------|-------|
| `DJANGO_SECRET_KEY` | **Required** | **Required** | **Required** | **Required** | Different keys per environment |
| `DJANGO_SETTINGS_MODULE` | `config.settings.dev` | `config.settings.pytest` | `config.settings.stage` | `config.settings.prod` | Environment selection |
| `DATABASE_URL` | Optional (uses SQLite) | Not needed | **Required** | **Required** | PostgreSQL connection string |
| `MAILGUN_API_KEY` | Not needed | Not needed | **Required** | **Required** | From secrets repo |
| `GITHUB_CLIENT_SECRET` | **Required** | Not needed | **Required** | **Required** | From secrets repo |
| `GITLAB_CLIENT_SECRET` | **Required** | Not needed | **Required** | **Required** | From secrets repo |
| `GOOGLE_CLIENT_SECRET` | **Required** | Not needed | **Required** | **Required** | From secrets repo |
| `LINKEDIN_CLIENT_SECRET` | **Required** | Not needed | **Required** | **Required** | From secrets repo |
| `DISCORD_CLIENT_SECRET` | **Required** | Not needed | **Required** | **Required** | From secrets repo |

## Secrets Management

### Secrets Repository Structure

**Both staging and production use the same directory path:** `/home/django/.secrets/`

However, they clone from **different git repositories**:

**Production secrets repository:**
- Git URL: `git+ssh://github.com/mithro/platform.wafer.space-secrets.git`
- Cloned to: `/home/django/.secrets/`
- Contains production OAuth secrets and API keys

**Staging secrets repository:**
- Git URL: `git+ssh://github.com/mithro/test-platform.wafer.space-secrets.git`
- Cloned to: `/home/django/.secrets/` (same path as production)
- Contains staging OAuth secrets and API keys

**Directory structure (same for both environments):**
```
/home/django/.secrets/
├── github-oauth          # GitHub Client Secret
├── gitlab-oauth          # GitLab Client Secret
├── google-auth.json      # Google OAuth credentials (JSON)
├── discord-oauth         # Discord Client Secret
├── linkedin-oauth        # LinkedIn Client Secret
└── mailgun               # Mailgun API key
```

**How it works:**
1. Deployment script `02a-setup-secrets.sh` clones the appropriate repository
2. Production server clones from `platform.wafer.space-secrets.git`
3. Staging server clones from `test-platform.wafer.space-secrets.git`
4. Both clone to the same path: `/home/django/.secrets/`
5. Script `03a-update-env-secrets.sh` reads secrets and injects into `.env`

### Deployment Script Behavior

**Script:** `deployment/scripts/02a-setup-secrets.sh`
- Detects environment (staging vs production)
- Clones appropriate secrets repository to `/home/django/.secrets/`
- Updates secrets from git repository on subsequent runs

**Script:** `deployment/scripts/03a-update-env-secrets.sh`
- Reads secrets from `/home/django/.secrets/`
- Injects into `.env` file
- Same behavior for both staging and production

## Key Differences Between Environments

### dev vs stage vs prod

**Database:**
- dev: SQLite (fast, simple, local file)
- pytest: SQLite in-memory (fastest, ephemeral)
- stage/prod: PostgreSQL (production-grade, network database)

**Security:**
- dev: DEBUG=True, HTTP, weak passwords OK, insecure secret key
- pytest: DEBUG=False, MD5 passwords (fast), no HTTPS
- stage/prod: DEBUG=False, HTTPS enforced, Argon2 passwords, HSTS, secure cookies, unique secrets

**OAuth:**
- dev: Dev OAuth apps, empty secret defaults
- pytest: Hardcoded test credentials (mock authentication)
- stage: Stage OAuth apps, secrets from `/home/django/.secrets/` (cloned from test-platform repo)
- prod: Prod OAuth apps, secrets from `/home/django/.secrets/` (cloned from platform repo)

**Email:**
- dev: Console backend (prints to terminal)
- pytest: In-memory backend (captured for testing)
- stage/prod: Mailgun backend (real emails sent)

**Celery:**
- dev: SQLite broker, asynchronous tasks, fast retry intervals
- pytest: Synchronous tasks (`CELERY_TASK_ALWAYS_EAGER=True`), base intervals
- stage/prod: PostgreSQL broker, asynchronous tasks, production intervals

**Static Files:**
- dev: Direct serving via Django, no compression
- pytest: Direct serving via Django
- stage/prod: WhiteNoise with compression and manifest

**Monitoring:**
- dev: Debug toolbar, django-extensions, verbose logging
- pytest: Minimal logging
- stage/prod: Error emails to admins, production logging

## Staging (test-platform.wafer.space) Purpose

The staging environment serves several critical functions:

1. **Deployment Testing**: Verify deployment procedures before production
2. **Migration Testing**: Test database migrations in PostgreSQL
3. **OAuth Testing**: Verify OAuth flows with real providers
4. **Security Testing**: Validate HTTPS/security configurations
5. **Email Testing**: Test email delivery with Mailgun
6. **Performance Testing**: Load test under production-like conditions
7. **Integration Testing**: Smoke test new features before prod deployment
8. **Training Environment**: Safe environment for team onboarding

### Why staging differs from dev

- Deployed server (not localhost) - tests deployment procedures
- PostgreSQL - tests migration compatibility with production database
- HTTPS - validates security configuration
- Real email sending - verifies email flows work correctly
- Asynchronous Celery - tests task queue behavior
- Separate OAuth apps - prevents dev/stage conflicts
- Separate secrets - isolation from production credentials

### Why staging differs from prod

- Lower HSTS max-age: 1 hour vs 1 year (safer for testing)
- HSTS preload disabled (not submitted to browser preload list)
- Fast retry intervals like dev (30 seconds vs 5 minutes)
- Subdomain support (buddy, doc subdomains for testing)
- Can have relaxed error reporting for debugging
- Isolated failures don't affect production
- Safe environment for experimentation

## Settings That Should Remain Universal

These settings should stay in `base.py` and NOT be overridden:

- `TIME_ZONE`, `LANGUAGE_CODE`, `USE_I18N`, `USE_TZ`
- `SITE_URL` (default: `http://localhost:8081`, can be overridden)
- `CACHES` (default: LocMemCache with location `wafer-space-cache`)
- `DEFAULT_FROM_EMAIL`, `SERVER_EMAIL`, `EMAIL_SUBJECT_PREFIX`
- `TEMPLATES` configuration (except `OPTIONS.debug`)
- `MIDDLEWARE` (except debug toolbar in dev)
- `INSTALLED_APPS` (except environment-specific apps)
- `AUTHENTICATION_BACKENDS`
- `PASSWORD_HASHERS` (except pytest fast hashing)
- All django-allauth configuration (except OAuth credentials)
- Celery task routing, time limits, serialization
- Application business logic settings

## Settings That Must Differ Per Environment

These MUST be environment-specific (set to None in base.py):

- `DEBUG` - Set to None in base, must be explicitly set in each environment
- `EMAIL_BACKEND` - Set to None in base, must be explicitly set in each environment
- OAuth client IDs and secrets - All set to None in base, must be set in each environment
- `SECRET_KEY` - Different per environment for security
- `ALLOWED_HOSTS` - Environment-specific domains
- `DATABASES` (SQLite vs PostgreSQL)
- Security settings (cookies, HSTS, SSL redirect)
- Email credentials (ANYMAIL configuration)
- Static files storage backend
- Logging configuration
- Celery broker URL and eager mode

## Callback URLs by Environment

### Development (localhost:8081)
- `http://localhost:8081/accounts/github/login/callback/`
- `http://localhost:8081/accounts/gitlab/login/callback/`
- `http://localhost:8081/accounts/google/login/callback/`
- `http://localhost:8081/accounts/oidc/linkedin/login/callback/`
- `http://localhost:8081/accounts/discord/login/callback/`

### Staging (test-platform.wafer.space)
- `https://test-platform.wafer.space/accounts/github/login/callback/`
- `https://test-platform.wafer.space/accounts/gitlab/login/callback/`
- `https://test-platform.wafer.space/accounts/google/login/callback/`
- `https://test-platform.wafer.space/accounts/oidc/linkedin/login/callback/`
- `https://test-platform.wafer.space/accounts/discord/login/callback/`

### Production (platform.wafer.space)
- `https://platform.wafer.space/accounts/github/login/callback/`
- `https://platform.wafer.space/accounts/gitlab/login/callback/`
- `https://platform.wafer.space/accounts/google/login/callback/`
- `https://platform.wafer.space/accounts/oidc/linkedin/login/callback/`
- `https://platform.wafer.space/accounts/discord/login/callback/`

## Common Pitfalls to Avoid

1. **❌ Hardcoding secrets** - OAuth secrets must always use `env("SECRET")`, never hardcode values
2. **❌ Setting OAuth to empty defaults** - `env("SECRET", default="")` breaks tests; use required env vars
3. **❌ Committing secrets** - Use `.gitignore`, pre-commit hooks, secrets repository
4. **❌ Using database-based OAuth** - This project uses settings-based configuration only
5. **❌ Forgetting to set None-values** - DEBUG, EMAIL_BACKEND, OAuth credentials set to None in base.py must be overridden
6. **❌ Inconsistent section ordering** - Follow the 15-section structure in all environment files
7. **❌ Sharing secrets between environments** - Each environment has separate secrets
8. **❌ Using same OAuth apps** - Each environment needs separate OAuth applications with correct callback URLs
9. **❌ Forgetting HSTS differences** - Stage: 3600 (1 hour), Prod: 31536000 (1 year)
10. **❌ Not updating staging client IDs** - All staging OAuth apps have separate client IDs hardcoded in stage.py

## Migration Checklist

When deploying staging environment:

- [ ] Create separate OAuth apps for all 5 providers (GitHub, GitLab, Google, LinkedIn, Discord)
- [ ] Configure callback URLs for test-platform.wafer.space on all OAuth apps
- [ ] Create staging secrets repository at `git+ssh://github.com/mithro/test-platform.wafer.space-secrets.git`
- [ ] Generate and store all staging secrets in the staging secrets repository
- [ ] Clone staging secrets repository to `/home/django/.secrets/` on staging server
- [ ] Ensure `deployment/scripts/02a-setup-secrets.sh` clones correct repository for staging
- [ ] Create `.env` file on staging server with all required variables
- [ ] Configure systemd services to use `config.settings.stage`
- [ ] Test OAuth login flows for all 5 providers
- [ ] Test email sending via Mailgun
- [ ] Test Celery task execution
- [ ] Verify HTTPS enforcement and security headers
- [ ] Test database migrations in PostgreSQL
- [ ] Verify static files served correctly via WhiteNoise

## References

- Django Settings Documentation: https://docs.djangoproject.com/en/5.2/ref/settings/
- django-allauth Settings: https://docs.allauth.org/en/latest/account/configuration.html
- Celery Configuration: https://docs.celeryq.dev/en/stable/userguide/configuration.html
- WhiteNoise Documentation: http://whitenoise.evans.io/
- Mailgun (Anymail) Documentation: https://anymail.readthedocs.io/en/stable/esps/mailgun/

## Related Documentation

- `deployment/README.md` - Full deployment guide
- `docs/oauth_setup.md` - OAuth provider configuration
- `docs/oauth_secret_rotation.md` - Secret rotation procedures
- `docs/developer_onboarding.md` - Local development setup
- `docs/production_deployment.md` - Production deployment procedures
