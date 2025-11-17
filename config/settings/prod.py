"""Production settings for platform.wafer.space."""

from .base import *  # noqa: F403
from .base import DATABASES
from .base import INSTALLED_APPS
from .base import SOCIALACCOUNT_PROVIDERS
from .base import env

# CORE DJANGO SETTINGS
# ------------------------------------------------------------------------------
# DEBUG: uses base.py default (False)
SECRET_KEY = env("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = ["platform.wafer.space"]
SITE_URL = "https://platform.wafer.space"

# DATABASES
# ------------------------------------------------------------------------------
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
SECURE_HSTS_SECONDS = 60
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
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
DEFAULT_FROM_EMAIL = "wafer.space Online Platform <noreply@platform.wafer.space>"
SERVER_EMAIL = DEFAULT_FROM_EMAIL
EMAIL_SUBJECT_PREFIX = "[wafer.space Online Platform] "
ACCOUNT_EMAIL_SUBJECT_PREFIX = EMAIL_SUBJECT_PREFIX

ANYMAIL = {
    "MAILGUN_API_KEY": env("MAILGUN_API_KEY"),
    "MAILGUN_SENDER_DOMAIN": env("MAILGUN_DOMAIN"),
    "MAILGUN_API_URL": "https://api.mailgun.net/v3",
}

# ADMIN
# ------------------------------------------------------------------------------
ADMIN_URL = env("DJANGO_ADMIN_URL")

# INSTALLED APPS / MIDDLEWARE
# ------------------------------------------------------------------------------
INSTALLED_APPS += ["anymail"]
# MIDDLEWARE: uses base.py defaults

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
# DOWNLOAD_RETRY_*: uses base.py defaults

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
SOCIALACCOUNT_PROVIDERS["github"]["APP"]["client_id"] = "Ov23linEhI33aev2uGSU"
SOCIALACCOUNT_PROVIDERS["github"]["APP"]["secret"] = env("GITHUB_CLIENT_SECRET")
SOCIALACCOUNT_PROVIDERS["gitlab"]["APP"]["client_id"] = (
    "f0fde384db4cd0fe11041488a6b87e9d3d20223385b78d1ba1ed4045fbea6c16"
)
SOCIALACCOUNT_PROVIDERS["gitlab"]["APP"]["secret"] = env("GITLAB_CLIENT_SECRET")
SOCIALACCOUNT_PROVIDERS["google"]["APP"]["client_id"] = (
    "62545893239-pgg1lcg28u9suivjh4nso9t8mev5qua2.apps.googleusercontent.com"
)
SOCIALACCOUNT_PROVIDERS["google"]["APP"]["secret"] = env("GOOGLE_CLIENT_SECRET")
SOCIALACCOUNT_PROVIDERS["discord"]["APP"]["client_id"] = "1426065281138167841"
SOCIALACCOUNT_PROVIDERS["discord"]["APP"]["secret"] = env("DISCORD_CLIENT_SECRET")
for app in SOCIALACCOUNT_PROVIDERS["openid_connect"]["APPS"]:
    if app["provider_id"] == "linkedin":
        app["client_id"] = "86q1gs3uqhpqt1"
        app["secret"] = env("LINKEDIN_CLIENT_SECRET")
