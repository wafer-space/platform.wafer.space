from .base import *  # noqa: F403
from .base import INSTALLED_APPS
from .base import MIDDLEWARE
from .base import env

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#debug
DEBUG = True
# https://docs.djangoproject.com/en/dev/ref/settings/#secret-key
SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="x6qF1ip5OCnSpNimKy5euQyAVL8VargqvQnqxknuOyy5aMJePgKviTT7iYXQaxjO",
)
# https://docs.djangoproject.com/en/dev/ref/settings/#allowed-hosts
ALLOWED_HOSTS = ["localhost", "0.0.0.0", "127.0.0.1"]  # noqa: S104

# DATABASES
# ------------------------------------------------------------------------------
# Use SQLite for local development with WAL mode and increased timeout
# to prevent "database is locked" errors with concurrent access
# (Django dev server + Celery workers)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",  # noqa: F405
        # Increase timeout to 30 seconds (default is 5)
        "timeout": 30,
        "OPTIONS": {
            # Enable WAL mode for better concurrent access
            # WAL allows multiple readers while one writer is active
            "init_command": "PRAGMA journal_mode=WAL;",
        },
    },
}

# CACHES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#caches
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "",
    },
}

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
EMAIL_BACKEND = env(
    "DJANGO_EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend",
)

# WhiteNoise
# ------------------------------------------------------------------------------
# http://whitenoise.evans.io/en/latest/django.html#using-whitenoise-in-development
INSTALLED_APPS = ["whitenoise.runserver_nostatic", *INSTALLED_APPS]


# django-debug-toolbar
# ------------------------------------------------------------------------------
# https://django-debug-toolbar.readthedocs.io/en/latest/installation.html#prerequisites
INSTALLED_APPS += ["debug_toolbar"]
# https://django-debug-toolbar.readthedocs.io/en/latest/installation.html#middleware
MIDDLEWARE += ["debug_toolbar.middleware.DebugToolbarMiddleware"]
# https://django-debug-toolbar.readthedocs.io/en/latest/configuration.html#debug-toolbar-config
DEBUG_TOOLBAR_CONFIG = {
    "DISABLE_PANELS": [
        "debug_toolbar.panels.redirects.RedirectsPanel",
        # Disable profiling panel due to an issue with Python 3.12+:
        # https://github.com/jazzband/django-debug-toolbar/issues/1875
        "debug_toolbar.panels.profiling.ProfilingPanel",
    ],
    "SHOW_TEMPLATE_CONTEXT": True,
}
# https://django-debug-toolbar.readthedocs.io/en/latest/installation.html#internal-ips
INTERNAL_IPS = ["127.0.0.1", "10.0.2.2"]


# django-extensions
# ------------------------------------------------------------------------------
# https://django-extensions.readthedocs.io/en/latest/installation_instructions.html#configuration
INSTALLED_APPS += ["django_extensions"]

# Celery
# ------------------------------------------------------------------------------
# Use real Celery worker in local development (started via Honcho/Procfile)
# Eager mode disabled - tasks run asynchronously via worker process
# Start worker with: make runserver (uses Honcho to run web + worker)

# Use SQLite as Celery broker in local development (matches DATABASES config)
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#broker-url
CELERY_BROKER_URL = f"sqla+sqlite:///{BASE_DIR / 'db.sqlite3'}"  # noqa: F405

# Download retry configuration - use seconds for faster testing in development
# ------------------------------------------------------------------------------
DOWNLOAD_RETRY_BASE_DELAY_MINUTES = 30 / 60  # 30 seconds (expressed in minutes)
DOWNLOAD_RETRY_CHECK_INTERVAL_SECONDS = 30.0  # Check every 30 seconds

# Download state verification - faster checks in development
DOWNLOAD_STATE_CHECK_INTERVAL_SECONDS = 30.0  # Check every 30 seconds

# Override Celery Beat schedule with development intervals
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

# Your stuff...
# ------------------------------------------------------------------------------
