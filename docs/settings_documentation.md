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
| `DEBUG` | `True` | `False` | `False` | `False` | Debug only in local dev |
| `SECRET_KEY` | Hardcoded dev key | Hardcoded test key | **Required from env** | **Required from env** | Different keys per environment |
| `ALLOWED_HOSTS` | `["localhost", "0.0.0.0", "127.0.0.1"]` | `["testserver"]` | `["test-platform.wafer.space"]` | `["platform.wafer.space", "5.9.182.54"]` | Environment-specific |
| `SITE_URL` | `http://localhost:8081` | Inherits base | `https://test-platform.wafer.space` | Inherits base | Used in emails and absolute URLs |
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
| `BACKEND` | `LocMemCache` | Inherits base | `LocMemCache` | `LocMemCache` | In-memory sufficient for current scale |
| `LOCATION` | `""` | Inherits base | `"wafer-space-cache"` | `"wafer-space-cache"` | Named cache for deployed environments |

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
| `SECURE_SSL_REDIRECT` | Not set | Not set | `True` (env) | `True` (env) | HTTPS enforcement |
| `SECURE_HSTS_SECONDS` | Not set | Not set | `60` (env) | `60` (env) | HSTS header (increase after verification) |
| `SECURE_HSTS_INCLUDE_SUBDOMAINS` | Not set | Not set | `True` (env) | `True` (env) | Comprehensive HTTPS |
| `SECURE_HSTS_PRELOAD` | Not set | Not set | `True` (env) | `True` (env) | Maximum HTTPS enforcement |
| `SECURE_CONTENT_TYPE_NOSNIFF` | Not set | Not set | `True` (env) | `True` (env) | Prevent security vulnerabilities |

### 5. PASSWORD HASHING

| Setting | dev | pytest | stage | prod | Notes |
|---------|-----|--------|-------|------|-------|
| `PASSWORD_HASHERS` | Argon2, PBKDF2, etc. | `MD5PasswordHasher` only | Argon2, PBKDF2, etc. | Argon2, PBKDF2, etc. | Fast MD5 for tests only |

### 6. EMAIL CONFIGURATION

| Setting | dev | pytest | stage | prod | Notes |
|---------|-----|--------|-------|------|-------|
| `EMAIL_BACKEND` | `console.EmailBackend` | `locmem.EmailBackend` | `anymail.backends.mailgun.EmailBackend` | `anymail.backends.mailgun.EmailBackend` | Console/memory for dev/test, Mailgun for deployed |
| `EMAIL_TIMEOUT` | `5` | `5` | `5` | `5` | Universal |
| `DEFAULT_FROM_EMAIL` | Base default | Base default | `wafer.space Online Platform <noreply@test-platform.wafer.space>` | `wafer.space Online Platform <noreply@platform.wafer.space>` | Environment-specific sender |
| `SERVER_EMAIL` | Base default | Base default | Matches DEFAULT_FROM_EMAIL | Matches DEFAULT_FROM_EMAIL | For error reports |
| `EMAIL_SUBJECT_PREFIX` | Base default | Base default | `[wafer.space Online Platform] ` | `[wafer.space Online Platform] ` | Consistent branding |
| `ANYMAIL` | Not set | Not set | Mailgun config from env | Mailgun config from env | Mailgun credentials |

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
| `ADMIN_URL` | `admin/` | `admin/` | **Required from env** | **Required from env** | Security through obscurity for deployed |
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

| Provider | dev Client ID | pytest Client ID | stage Client ID | prod Client ID | Notes |
|----------|---------------|------------------|-----------------|----------------|-------|
| **GitHub** | `Ov23liLB7RRJUzku13dU` (base.py) | `test_github_client_id` | **Required from env** | `Ov23linEhI33aev2uGSU` (prod.py) | Separate apps per environment |
| **GitLab** | `2a29dee626...a4962aaa` (base.py) | `test_gitlab_client_id` | **Required from env** | `f0fde384db...fbea6c16` (prod.py) | Separate apps per environment |
| **Google** | `62545893239-jiesk...nqhc` (base.py) | `test_google_client_id` | **Required from env** | `62545893239-pgg1l...qua2` (prod.py) | Separate apps per environment |
| **LinkedIn** | `86j973nx41hlk7` (base.py) | `test_linkedin_client_id` | **Required from env** | `86q1gs3uqhpqt1` (prod.py) | OpenID Connect, separate apps |
| **Discord** | `1426055950221054052` (base.py) | `test_discord_client_id` | **Required from env** | `1426065281138167841` (prod.py) | Separate apps per environment |

**OAuth Secrets:** All environments load secrets from environment variables:
- **dev**: Empty defaults (optional secrets in .env)
- **pytest**: Hardcoded test secrets
- **stage**: **Required from env** (loaded from `/home/django/.secrets-stage/`)
- **prod**: **Required from env** (loaded from `/home/django/.secrets/`)

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
| `DOWNLOAD_RETRY_BASE_DELAY_MINUTES` | `0.5` (30 sec) | `5` (5 min) | `5` (5 min) | `5` (5 min) | Faster retries for dev |
| `DOWNLOAD_RETRY_BACKOFF_MULTIPLIER` | `3` | Same | Same | Same | Universal |
| `DOWNLOAD_RETRY_CHECK_INTERVAL_SECONDS` | `30` | `300` | `300` | `300` | Faster checks for dev |
| `DOWNLOAD_STATE_CHECK_INTERVAL_SECONDS` | `30` | `60` | `60` | `60` | Faster checks for dev |
| `CELERY_BEAT_SCHEDULE` | Dev intervals (30s) | Base intervals | Base intervals | Base intervals | Faster schedule for dev |

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
| `DJANGO_DEBUG` | Optional (default True) | Not needed | `False` | `False` | Explicit for deployed |
| `DJANGO_SECRET_KEY` | Optional (has default) | Optional (has default) | **Required** | **Required** | Generated keys for deployed |
| `DJANGO_SETTINGS_MODULE` | `config.settings.dev` | `config.settings.pytest` | `config.settings.stage` | `config.settings.prod` | Environment selection |
| `DJANGO_ALLOWED_HOSTS` | Optional | Not needed | Optional | Optional | Can override default |
| `DATABASE_URL` | Optional (uses SQLite) | Not needed | **Required** | **Required** | PostgreSQL connection string |
| `SITE_URL` | Optional | Not needed | `https://test-platform.wafer.space` | Optional | Staging-specific |
| `DJANGO_ADMIN_URL` | Not needed | Not needed | **Required** | **Required** | Security through obscurity |
| `MAILGUN_API_KEY` | Not needed | Not needed | **Required** | **Required** | From secrets repo |
| `MAILGUN_DOMAIN` | Not needed | Not needed | **Required** | **Required** | Email sending domain |
| `GITHUB_CLIENT_ID` | Optional | Not needed | **Required** | Optional (has default) | Stage override needed |
| `GITHUB_CLIENT_SECRET` | Optional | Not needed | **Required** | **Required** | From secrets repo |
| `GITLAB_CLIENT_ID` | Optional | Not needed | **Required** | Optional (has default) | Stage override needed |
| `GITLAB_CLIENT_SECRET` | Optional | Not needed | **Required** | **Required** | From secrets repo |
| `GOOGLE_CLIENT_ID` | Optional | Not needed | **Required** | Optional (has default) | Stage override needed |
| `GOOGLE_CLIENT_SECRET` | Optional | Not needed | **Required** | **Required** | From secrets repo |
| `LINKEDIN_CLIENT_ID` | Optional | Not needed | **Required** | Optional (has default) | Stage override needed |
| `LINKEDIN_CLIENT_SECRET` | Optional | Not needed | **Required** | **Required** | From secrets repo |
| `DISCORD_CLIENT_ID` | Optional | Not needed | **Required** | Optional (has default) | Stage override needed |
| `DISCORD_CLIENT_SECRET` | Optional | Not needed | **Required** | **Required** | From secrets repo |

## Secrets Management

### Secrets Repository Structure

**Production secrets:** `/home/django/.secrets/` (existing)
```
/home/django/.secrets/
├── github-oauth          # GitHub Client Secret (prod)
├── gitlab-oauth          # GitLab Client Secret (prod)
├── google-auth.json      # Google OAuth credentials (prod)
├── discord-oauth         # Discord Client Secret (prod)
├── linkedin-oauth        # LinkedIn Client Secret (prod)
└── mailgun               # Mailgun API key (prod)
```

**Staging secrets:** `/home/django/.secrets-stage/` (NEW)
```
/home/django/.secrets-stage/
├── github-oauth          # GitHub Client Secret (stage)
├── gitlab-oauth          # GitLab Client Secret (stage)
├── google-auth.json      # Google OAuth credentials (stage)
├── discord-oauth         # Discord Client Secret (stage)
├── linkedin-oauth        # LinkedIn Client Secret (stage)
└── mailgun               # Mailgun API key (stage)
```

### Deployment Script Updates

**Script:** `deployment/scripts/03a-update-env-secrets.sh`

Must support both environments:
- Accept environment parameter (stage/prod)
- Read from appropriate secrets directory
- Inject into appropriate .env file

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
- stage: Stage OAuth apps, secrets from `/home/django/.secrets-stage/`
- prod: Prod OAuth apps, secrets from `/home/django/.secrets/`

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

- Can have relaxed error reporting for debugging
- Can use lower HSTS max-age (safer rollback)
- Can have different rate limits (for load testing)
- Isolated failures don't affect production
- Safe environment for experimentation

## Settings That Should Remain Universal

These settings should stay in `base.py` and NOT be overridden:

- `TIME_ZONE`, `LANGUAGE_CODE`, `USE_I18N`, `USE_TZ`
- `TEMPLATES` configuration (except `OPTIONS.debug`)
- `MIDDLEWARE` (except debug toolbar in dev)
- `INSTALLED_APPS` (except environment-specific apps)
- `AUTHENTICATION_BACKENDS`
- `PASSWORD_HASHERS` (except pytest fast hashing)
- All django-allauth configuration (except env vars)
- Celery task routing, time limits, serialization
- Application business logic settings

## Settings That Must Differ Per Environment

These MUST be environment-specific:

- `DEBUG`, `SECRET_KEY`, `ALLOWED_HOSTS`
- `DATABASES` (SQLite vs PostgreSQL)
- Security settings (cookies, HSTS, SSL redirect)
- Email backend and credentials
- OAuth credentials (client IDs and secrets)
- `ADMIN_URL` (security through obscurity)
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

1. **❌ Hardcoding secrets** - Always use `env("SECRET", default="")` never `"actual_value"`
2. **❌ Committing secrets** - Use `.gitignore`, pre-commit hooks, empty defaults
3. **❌ Using database-based OAuth** - This project uses settings-based configuration
4. **❌ Forgetting deployment script updates** - Must update `03a-update-env-secrets.sh` for staging
5. **❌ Inconsistent naming** - Settings: `PROVIDER_CLIENT_SECRET`, File: `provider-oauth`
6. **❌ Sharing secrets between environments** - Each environment has separate secrets
7. **❌ Using same OAuth apps** - Each environment needs separate OAuth applications
8. **❌ Forgetting to update callback URLs** - OAuth apps must have correct callback URLs configured

## Migration Checklist

When deploying staging environment:

- [ ] Create separate OAuth apps for all 5 providers (GitHub, GitLab, Google, LinkedIn, Discord)
- [ ] Configure callback URLs for test-platform.wafer.space on all OAuth apps
- [ ] Create `/home/django/.secrets-stage/` directory on staging server
- [ ] Generate and store all staging secrets in secrets repository
- [ ] Update `deployment/scripts/03a-update-env-secrets.sh` to support staging
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
