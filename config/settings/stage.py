"""Staging settings for test-platform.wafer.space."""

from .base import *  # noqa: F403
from .base import DATABASES
from .base import INSTALLED_APPS
from .base import SOCIALACCOUNT_PROVIDERS
from .base import env
from .base import required_host_list

# CORE DJANGO SETTINGS
# ------------------------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY")
# Comma-separated list provided by the deployment (see .env / ansible).
# required_host_list fails fast if the value is missing or empty, so we never
# silently boot with an unusable allowlist and serve HTTP 400s (issue #267).
ALLOWED_HOSTS = required_host_list("DJANGO_ALLOWED_HOSTS")
SITE_URL = "https://test-platform.wafer.space"

# DATABASES
# ------------------------------------------------------------------------------
# Production postgres database
DATABASES["default"]["CONN_MAX_AGE"] = 60  # Keep connections alive for 60 seconds

# CACHES
# ------------------------------------------------------------------------------
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "wafer-space-cache",
    },
}

# SECURITY
# ------------------------------------------------------------------------------
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# nginx is the sole ingress and sets X-Real-IP from its own (Cloudflare-scoped
# real_ip) resolution; gunicorn is reachable only via a local unix socket.
TRUST_X_REAL_IP = True
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_NAME = "__Secure-sessionid"
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_NAME = "__Secure-csrftoken"
SECURE_HSTS_SECONDS = 3600  # 1 hour for staging
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False
SECURE_CONTENT_TYPE_NOSNIFF = True

# STATIC FILES / STORAGE
# ------------------------------------------------------------------------------
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# EMAIL
# ------------------------------------------------------------------------------
EMAIL_BACKEND = "anymail.backends.mailgun.EmailBackend"

ANYMAIL = {
    "MAILGUN_API_KEY": env("MAILGUN_API_KEY"),
    "MAILGUN_SENDER_DOMAIN": "mg.wafer.space",
    "MAILGUN_API_URL": "https://api.mailgun.net/v3",
}

DEFAULT_FROM_EMAIL = "wafer.space Platform <noreply@test-platform.wafer.space>"
SERVER_EMAIL = DEFAULT_FROM_EMAIL
# EMAIL_SUBJECT_PREFIX: uses base.py defaults

# INSTALLED APPS / MIDDLEWARE
# ------------------------------------------------------------------------------
INSTALLED_APPS += [
    "anymail",
]

# TEMPLATES
# ------------------------------------------------------------------------------
# Uses base.py defaults

# AUTHENTICATION
# ------------------------------------------------------------------------------
# PASSWORD_HASHERS: uses base.py defaults (Argon2, PBKDF2, etc.)

# MEDIA
# ------------------------------------------------------------------------------
# MEDIA_URL: uses base.py default (/media/)

# CELERY
# ------------------------------------------------------------------------------
# CELERY_BROKER_URL: uses base.py default (PostgreSQL via SQLAlchemy)
# CELERY_TASK_ALWAYS_EAGER: uses base.py default (False)
# DOWNLOAD_TASK_*: uses base.py defaults (Celery retry configuration)
# CELERY_BEAT_SCHEDULE: uses base.py defaults (all check lifecycle tasks)

# Docker servers for manufacturability checks
# Staging uses one remote Docker server with 2 concurrent checks
# Total capacity: 2 concurrent checks, each reserving 32GB memory
# (soft limit; hard cap 2x = 64GB, no swap - see PRECHECK_MEM_SOFT_LIMIT_GB)
# Must match checker_concurrent_checks in hetzner-ansible host_vars
# E2E testing showed --workers 6 --threads 1 gives the best performance vs
# memory trade-off per check: 6 workers share the 32GB soft limit (~5.3GB
# each), and concurrent checks share idle CPU via the scheduler.
DOCKER_SERVERS = [
    {
        "id": "checker.wafer.space@buddy",
        "url": "tcp://10.2.27.44:2375",
        "max_concurrent": 2,
        "priority": 1,
        "check_workers": 6,
        "check_threads": 1,
    },
]

# LOGGING
# ------------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"require_debug_false": {"()": "django.utils.log.RequireDebugFalse"}},
    "formatters": {
        "verbose": {
            "format": "%(levelname)s %(asctime)s %(module)s %(process)d %(thread)d %(message)s",  # noqa: E501
        },
    },
    "handlers": {
        # Rate-limited: at most one email per error signature per hour,
        # so a repeating failure (e.g. a periodic task erroring every few
        # minutes) cannot flood ADMINS. See issue #293.
        "mail_admins": {
            "level": "ERROR",
            "filters": ["require_debug_false"],
            "class": "wafer_space.core.log.RateLimitedAdminEmailHandler",
        },
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {"level": "INFO", "handlers": ["console"]},
    "loggers": {
        "django.request": {
            "handlers": ["mail_admins"],
            "level": "ERROR",
            "propagate": True,
        },
        "django.security.DisallowedHost": {
            "level": "ERROR",
            "handlers": ["console", "mail_admins"],
            "propagate": True,
        },
        # Application errors (logger.error/logger.exception anywhere under
        # wafer_space.*, including Celery tasks and the task_failure bridge
        # in config/celery.py) email ADMINS. Celery's root-logger hijack in
        # workers does not touch explicitly-configured loggers, so this
        # works in web and worker processes alike. See issue #293: metadata
        # fetches failed every 5 minutes for a month with no email.
        "wafer_space": {
            "handlers": ["mail_admins"],
            "level": "ERROR",
            "propagate": True,
        },
    },
}

# OAUTH PROVIDERS
# ------------------------------------------------------------------------------
SOCIALACCOUNT_PROVIDERS = SOCIALACCOUNT_PROVIDERS.copy()

# GitHub
SOCIALACCOUNT_PROVIDERS["github"]["APP"]["client_id"] = "Ov23lisQ91kx0M3Dhqwd"
SOCIALACCOUNT_PROVIDERS["github"]["APP"]["secret"] = env("GITHUB_CLIENT_SECRET")

# GitLab
SOCIALACCOUNT_PROVIDERS["gitlab"]["APP"]["client_id"] = (
    "6b111b2573f18fbe2f4cdb2f9dcdbc9ee0318b7e546bf9a029b9b361b06cf708"
)
SOCIALACCOUNT_PROVIDERS["gitlab"]["APP"]["secret"] = env("GITLAB_CLIENT_SECRET")

# Google
SOCIALACCOUNT_PROVIDERS["google"]["APP"]["client_id"] = (
    "62545893239-00nmudn3he0nb8bipsbuhdk2ou3jo0ca.apps.googleusercontent.com"
)
SOCIALACCOUNT_PROVIDERS["google"]["APP"]["secret"] = env("GOOGLE_CLIENT_SECRET")

# Discord
SOCIALACCOUNT_PROVIDERS["discord"]["APP"]["client_id"] = "1440161777756405851"
SOCIALACCOUNT_PROVIDERS["discord"]["APP"]["secret"] = env("DISCORD_CLIENT_SECRET")

# LinkedIn
for app in SOCIALACCOUNT_PROVIDERS["openid_connect"]["APPS"]:
    if app["provider_id"] == "linkedin":
        app["client_id"] = "86r16sb9k5fkwt"
        app["secret"] = env("LINKEDIN_CLIENT_SECRET")

# DEVELOPMENT TOOLS
# ------------------------------------------------------------------------------
DEBUG = False
