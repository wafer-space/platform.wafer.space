"""
With these settings, tests run faster.
"""

from .base import *  # noqa: F403
from .base import TEMPLATES
from .base import env

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#secret-key
SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="8dIz5XazziQI0eksKFugR13QIZhCbVOy4YXoBjWsA0JH9fEqJnheGk3swaHmMDYI",
)
# https://docs.djangoproject.com/en/dev/ref/settings/#test-runner
TEST_RUNNER = "django.test.runner.DiscoverRunner"
# https://docs.djangoproject.com/en/dev/ref/settings/#allowed-hosts
ALLOWED_HOSTS = ["testserver"]

# PASSWORDS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#password-hashers
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# DEBUGGING FOR TEMPLATES
# ------------------------------------------------------------------------------
TEMPLATES[0]["OPTIONS"]["debug"] = True  # type: ignore[index]

# MEDIA
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#media-url
MEDIA_URL = "http://media.testserver/"
# DATABASES
# ------------------------------------------------------------------------------
# Use SQLite for testing (faster and no setup required)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",  # Use in-memory database for speed
    },
}

# CELERY
# ------------------------------------------------------------------------------
# Run Celery tasks synchronously during testing
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# SOCIAL AUTHENTICATION
# ------------------------------------------------------------------------------
# Settings-based OAuth configuration for all tests (unit tests and browser tests)
# This eliminates the need for database SocialApp objects and avoids
# transaction isolation issues with file-based databases.
SOCIALACCOUNT_PROVIDERS = {
    "github": {
        "APP": {
            "client_id": "test_github_client_id",
            "secret": "test_github_secret",
        },
        "SCOPE": [
            "user:email",
        ],
        "VERIFIED_EMAIL": True,
    },
    "gitlab": {
        "APP": {
            "client_id": "test_gitlab_client_id",
            "secret": "test_gitlab_secret",
        },
        "SCOPE": [
            "read_user",
            "email",
        ],
        "VERIFIED_EMAIL": True,
    },
    "google": {
        "APP": {
            "client_id": "test_google_client_id.apps.googleusercontent.com",
            "secret": "test_google_secret",
        },
        "SCOPE": [
            "profile",
            "email",
        ],
        "AUTH_PARAMS": {
            "access_type": "online",
        },
        "VERIFIED_EMAIL": True,
    },
    "openid_connect": {
        # LinkedIn uses OpenID Connect
        "APPS": [
            {
                "provider_id": "linkedin",
                "name": "LinkedIn",
                "client_id": "test_linkedin_client_id",
                "secret": "test_linkedin_secret",
                "settings": {
                    "server_url": "https://www.linkedin.com/oauth",
                },
            }
        ],
    },
    "discord": {
        "APP": {
            "client_id": "test_discord_client_id",
            "secret": "test_discord_secret",
        },
        "SCOPE": [
            "identify",
            "email",
        ],
        "VERIFIED_EMAIL": True,
    },
}

# Your stuff...
# ------------------------------------------------------------------------------
