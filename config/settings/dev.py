"""Development settings for local platform.wafer.space."""

from .base import *  # noqa: F403
from .base import BASE_DIR
from .base import INSTALLED_APPS
from .base import MIDDLEWARE
from .base import SOCIALACCOUNT_PROVIDERS
from .base import env

# CORE DJANGO SETTINGS
# ------------------------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = [
    "localhost",
    "0.0.0.0",  # noqa: S104
    "127.0.0.1",
    "platform.wafer.space",
    "test-platform.wafer.space",
]
SITE_URL = "http://localhost:8081"

# DATABASES
# ------------------------------------------------------------------------------
# Local sqlite database
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "timeout": 30,
        "OPTIONS": {"init_command": "PRAGMA journal_mode=WAL;"},
    },
}

# SECURITY
# ------------------------------------------------------------------------------
# Uses base.py defaults (no HTTPS in local development)

# STATIC FILES / STORAGE
# ------------------------------------------------------------------------------
# Uses base.py defaults

# EMAIL
# ------------------------------------------------------------------------------
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
# DEFAULT_FROM_EMAIL: uses base.py defaults
# SERVER_EMAIL: uses base.py defaults
# EMAIL_SUBJECT_PREFIX: uses base.py defaults

# INSTALLED APPS / MIDDLEWARE
# ------------------------------------------------------------------------------
INSTALLED_APPS = [
    "whitenoise.runserver_nostatic",
    *INSTALLED_APPS,
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
CELERY_BROKER_URL = f"sqla+sqlite:///{BASE_DIR / 'db.sqlite3'}"
# Fast retries
DOWNLOAD_RETRY_BASE_DELAY_MINUTES = 30 / 60  # 30 seconds for development
DOWNLOAD_RETRY_CHECK_INTERVAL_SECONDS = 30.0
DOWNLOAD_STATE_CHECK_INTERVAL_SECONDS = 30.0

CELERY_BEAT_SCHEDULE = {
    "retry-failed-downloads": {
        "task": "wafer_space.projects.tasks.retry_failed_downloads",
        "schedule": DOWNLOAD_RETRY_CHECK_INTERVAL_SECONDS,
    },
    "check-download-states": {
        "task": "wafer_space.projects.tasks.check_download_states",
        "schedule": DOWNLOAD_STATE_CHECK_INTERVAL_SECONDS,
    },
}

# LOGGING
# ------------------------------------------------------------------------------
# Uses base.py defaults

# OAUTH PROVIDERS
# ------------------------------------------------------------------------------
SOCIALACCOUNT_PROVIDERS = SOCIALACCOUNT_PROVIDERS.copy()

# GitHub
SOCIALACCOUNT_PROVIDERS["github"]["APP"]["client_id"] = "Ov23liLB7RRJUzku13dU"
SOCIALACCOUNT_PROVIDERS["github"]["APP"]["secret"] = env("GITHUB_CLIENT_SECRET")

# GitLab
SOCIALACCOUNT_PROVIDERS["gitlab"]["APP"]["client_id"] = (
    "2a29dee626b3c8b544f6f2c3a8042f912130bd040f4d3c60ef0e5864a4962aaa"
)
SOCIALACCOUNT_PROVIDERS["gitlab"]["APP"]["secret"] = env("GITLAB_CLIENT_SECRET")

# Google
SOCIALACCOUNT_PROVIDERS["google"]["APP"]["client_id"] = (
    "62545893239-jiesk1vfk22j87cth4ukq4alluc3nqhc.apps.googleusercontent.com"
)
SOCIALACCOUNT_PROVIDERS["google"]["APP"]["secret"] = env("GOOGLE_CLIENT_SECRET")

# Discord
SOCIALACCOUNT_PROVIDERS["discord"]["APP"]["client_id"] = "1426055950221054052"
SOCIALACCOUNT_PROVIDERS["discord"]["APP"]["secret"] = env("DISCORD_CLIENT_SECRET")

# LinkedIn
for app in SOCIALACCOUNT_PROVIDERS["openid_connect"]["APPS"]:
    if app["provider_id"] == "linkedin":
        app["client_id"] = "86j973nx41hlk7"
        app["secret"] = env("LINKEDIN_CLIENT_SECRET")

# DEVELOPMENT TOOLS
# ------------------------------------------------------------------------------
DEBUG = True
INSTALLED_APPS += [
    "debug_toolbar",
    "django_extensions",
]
MIDDLEWARE += [
    "debug_toolbar.middleware.DebugToolbarMiddleware",
]
DEBUG_TOOLBAR_CONFIG = {
    "DISABLE_PANELS": [
        "debug_toolbar.panels.redirects.RedirectsPanel",
        "debug_toolbar.panels.profiling.ProfilingPanel",
    ],
    "SHOW_TEMPLATE_CONTEXT": True,
}
INTERNAL_IPS = [
    "127.0.0.1",
]
