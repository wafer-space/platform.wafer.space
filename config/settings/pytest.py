"""Test settings for pytest execution."""

from .base import *  # noqa: F403
from .base import TEMPLATES
from .base import env

SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="8dIz5XazziQI0eksKFugR13QIZhCbVOy4YXoBjWsA0JH9fEqJnheGk3swaHmMDYI",
)
ALLOWED_HOSTS = ["testserver"]

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

TEMPLATES[0]["OPTIONS"]["debug"] = True  # type: ignore[index]

MEDIA_URL = "http://media.testserver/"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
        "timeout": 30,
    },
}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

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
