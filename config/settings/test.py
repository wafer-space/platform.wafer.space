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
# Override SOCIALACCOUNT_PROVIDERS to avoid conflicts with test SocialApp objects
# Tests create their own SocialApp objects in the database, so we don't want
# settings-based apps that would cause MultipleObjectsReturned errors
SOCIALACCOUNT_PROVIDERS = {
    "github": {
        "SCOPE": [
            "user:email",
        ],
        "VERIFIED_EMAIL": True,
    },
    "gitlab": {
        "SCOPE": [
            "read_user",
            "email",
        ],
        "VERIFIED_EMAIL": True,
    },
    "google": {
        "SCOPE": [
            "profile",
            "email",
        ],
        "AUTH_PARAMS": {
            "access_type": "online",
        },
        "VERIFIED_EMAIL": True,
    },
    "linkedin_oauth2": {
        "SCOPE": [
            "r_liteprofile",
            "r_emailaddress",
        ],
        "PROFILE_FIELDS": [
            "id",
            "first-name",
            "last-name",
            "email-address",
        ],
        "VERIFIED_EMAIL": True,
    },
}

# Your stuff...
# ------------------------------------------------------------------------------
