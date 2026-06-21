"""Staging settings for test-platform.wafer.space."""

from .base import *  # noqa: F403
from .base import DATABASES
from .base import INSTALLED_APPS
from .base import SOCIALACCOUNT_PROVIDERS
from .base import env

# CORE DJANGO SETTINGS
# ------------------------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY")
# Comma-separated list provided by the deployment (see .env / ansible). No
# default: a missing value raises ImproperlyConfigured so we fail fast rather
# than silently serving HTTP 400 for unlisted hosts (issue #267).
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")
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
# Staging uses one remote Docker server with 3 concurrent checks
# Total capacity: 3 concurrent checks, each using 24GB memory
DOCKER_SERVERS = [
    {
        "id": "checker.wafer.space@buddy",
        "url": "tcp://10.2.27.44:2375",
        "max_concurrent": 3,
        "priority": 1,
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
        "mail_admins": {
            "level": "ERROR",
            "filters": ["require_debug_false"],
            "class": "django.utils.log.AdminEmailHandler",
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
