"""Development settings for local environment."""

from .base import *  # noqa: F403
from .base import BASE_DIR
from .base import INSTALLED_APPS
from .base import MIDDLEWARE
from .base import env

DEBUG = True
SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="x6qF1ip5OCnSpNimKy5euQyAVL8VargqvQnqxknuOyy5aMJePgKviTT7iYXQaxjO",
)
ALLOWED_HOSTS = ["localhost", "0.0.0.0", "127.0.0.1"]  # noqa: S104

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "timeout": 30,
        "OPTIONS": {"init_command": "PRAGMA journal_mode=WAL;"},
    },
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "",
    },
}

EMAIL_BACKEND = env(
    "DJANGO_EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend",
)

INSTALLED_APPS = ["whitenoise.runserver_nostatic", *INSTALLED_APPS]
INSTALLED_APPS += ["debug_toolbar", "django_extensions"]
MIDDLEWARE += ["debug_toolbar.middleware.DebugToolbarMiddleware"]

DEBUG_TOOLBAR_CONFIG = {
    "DISABLE_PANELS": [
        "debug_toolbar.panels.redirects.RedirectsPanel",
        "debug_toolbar.panels.profiling.ProfilingPanel",
    ],
    "SHOW_TEMPLATE_CONTEXT": True,
}
INTERNAL_IPS = ["127.0.0.1", "10.0.2.2"]

CELERY_BROKER_URL = f"sqla+sqlite:///{BASE_DIR / 'db.sqlite3'}"
DOWNLOAD_RETRY_BASE_DELAY_MINUTES = 30 / 60
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
