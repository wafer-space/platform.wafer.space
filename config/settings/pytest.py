"""Test settings for pytest execution."""

from .base import *  # noqa: F403
from .base import TEMPLATES
from .base import env

# CORE DJANGO SETTINGS
# ------------------------------------------------------------------------------
# DEBUG: uses base.py default (False)
SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="8dIz5XazziQI0eksKFugR13QIZhCbVOy4YXoBjWsA0JH9fEqJnheGk3swaHmMDYI",
)
ALLOWED_HOSTS = ["testserver"]
SITE_URL = "http://testserver"

# DATABASES
# ------------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
        "timeout": 30,
    },
}

# CACHES
# ------------------------------------------------------------------------------
# Uses base.py defaults

# SECURITY
# ------------------------------------------------------------------------------
# Uses base.py defaults (no HTTPS in testing)

# STATIC FILES / STORAGE
# ------------------------------------------------------------------------------
# Uses base.py defaults

# EMAIL
# ------------------------------------------------------------------------------
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
# DEFAULT_FROM_EMAIL: uses base.py defaults
# SERVER_EMAIL: uses base.py defaults
# EMAIL_SUBJECT_PREFIX: uses base.py defaults

# ADMIN
# ------------------------------------------------------------------------------
# ADMIN_URL: uses base.py default (admin/)

# INSTALLED APPS / MIDDLEWARE
# ------------------------------------------------------------------------------
# Uses base.py defaults

# TEMPLATES
# ------------------------------------------------------------------------------
TEMPLATES[0]["OPTIONS"]["debug"] = True  # type: ignore[index]

# AUTHENTICATION
# ------------------------------------------------------------------------------
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# MEDIA
# ------------------------------------------------------------------------------
MEDIA_URL = "http://media.testserver/"

# CELERY
# ------------------------------------------------------------------------------
CELERY_TASK_ALWAYS_EAGER = True  # Execute tasks synchronously for testing
CELERY_TASK_EAGER_PROPAGATES = True
# CELERY_BROKER_URL: uses base.py default (PostgreSQL via SQLAlchemy)
# DOWNLOAD_TASK_*: uses base.py defaults (Celery retry configuration)

# Test Docker server configuration
DOCKER_SERVERS = [
    {
        "id": "test-local",
        "url": "unix:///var/run/docker.sock",
        "max_concurrent": 2,
        "priority": 1,
    },
]

# LOGGING
# ------------------------------------------------------------------------------
# Uses base.py defaults

# OAUTH PROVIDERS
# ------------------------------------------------------------------------------
SOCIALACCOUNT_PROVIDERS = {
    "github": {
        "APP": {
            "client_id": "test_github_client_id",
            "secret": "test_github_secret",
        },
        "SCOPE": ["user:email"],
        "VERIFIED_EMAIL": True,
    },
    "gitlab": {
        "APP": {
            "client_id": "test_gitlab_client_id",
            "secret": "test_gitlab_secret",
        },
        "SCOPE": ["read_user", "email"],
        "VERIFIED_EMAIL": True,
    },
    "google": {
        "APP": {
            "client_id": "test_google_client_id.apps.googleusercontent.com",
            "secret": "test_google_secret",
        },
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
        "VERIFIED_EMAIL": True,
    },
    "openid_connect": {
        "APPS": [
            {
                "provider_id": "linkedin",
                "name": "LinkedIn",
                "client_id": "test_linkedin_client_id",
                "secret": "test_linkedin_secret",
                "settings": {"server_url": "https://www.linkedin.com/oauth"},
            }
        ],
    },
    "discord": {
        "APP": {
            "client_id": "test_discord_client_id",
            "secret": "test_discord_secret",
        },
        "SCOPE": ["identify", "email"],
        "VERIFIED_EMAIL": True,
    },
}
