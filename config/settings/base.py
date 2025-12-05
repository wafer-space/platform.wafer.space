# ruff: noqa: ERA001, E501
"""Base settings to build other settings files upon."""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve(strict=True).parent.parent.parent
# wafer_space/
APPS_DIR = BASE_DIR / "wafer_space"
env = environ.Env()

READ_DOT_ENV_FILE = env.bool("DJANGO_READ_DOT_ENV_FILE", default=True)
if READ_DOT_ENV_FILE and (BASE_DIR / ".env").exists():
    # OS environment variables take precedence over variables from .env
    env.read_env(str(BASE_DIR / ".env"))

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#debug
DEBUG = None

# Local time zone. Choices are
# http://en.wikipedia.org/wiki/List_of_tz_zones_by_name
# though not all of them may be available with every OS.
# In Windows, this must be set to your system time zone.
TIME_ZONE = "UTC"

# https://docs.djangoproject.com/en/dev/ref/settings/#language-code
LANGUAGE_CODE = "en-us"
# https://docs.djangoproject.com/en/dev/ref/settings/#languages
# from django.utils.translation import gettext_lazy as _
# LANGUAGES = [
#     ('en', _('English')),
#     ('fr-fr', _('French')),
#     ('pt-br', _('Portuguese')),
# ]

# https://docs.djangoproject.com/en/dev/ref/settings/#site-id
SITE_ID = 1

# Site URL for email templates and absolute URLs
# Must be set in each environment (dev, pytest, stage, prod)
SITE_URL: str | None = None

# Deploy target identifier displayed in page footer (alongside hostname and git commit)
# Set via DEPLOY_TARGET in .env file (optional, e.g., "staging", "prod-us-east-1")
DEPLOY_TARGET: str | None = env("DEPLOY_TARGET", default=None)

# https://docs.djangoproject.com/en/dev/ref/settings/#use-i18n
USE_I18N = True

# https://docs.djangoproject.com/en/dev/ref/settings/#use-tz
USE_TZ = True

# https://docs.djangoproject.com/en/dev/ref/settings/#locale-paths
LOCALE_PATHS = [str(BASE_DIR / "locale")]

# DATABASES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#databases

DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres:///wafer_space",
    ),
}
DATABASES["default"]["ATOMIC_REQUESTS"] = True
# https://docs.djangoproject.com/en/stable/ref/settings/#std:setting-DEFAULT_AUTO_FIELD
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# CACHES
# ------------------------------------------------------------------------------
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "wafer-space-cache",
    },
}

# URLS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#root-urlconf
ROOT_URLCONF = "config.urls"
# https://docs.djangoproject.com/en/dev/ref/settings/#wsgi-application
WSGI_APPLICATION = "config.wsgi.application"

# APPS
# ------------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.sites",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # "django.contrib.humanize", # Handy template tags
    "django.contrib.admin",
    "django.forms",
]
THIRD_PARTY_APPS = [
    "crispy_forms",
    "crispy_bootstrap5",
    "allauth",
    "allauth.account",
    "allauth.mfa",
    "allauth.socialaccount",
    # Social providers
    "allauth.socialaccount.providers.github",
    "allauth.socialaccount.providers.gitlab",
    "allauth.socialaccount.providers.openid_connect",  # LinkedIn uses OpenID Connect
    "allauth.socialaccount.providers.google",
    "allauth.socialaccount.providers.discord",
    # Background job processing
    "django_celery_results",
    # History tracking
    "simple_history",
]

LOCAL_APPS = [
    "wafer_space.users",
    "wafer_space.legal",
    "wafer_space.notifications",
    "wafer_space.referrals",
    "wafer_space.projects",
    "wafer_space.shuttles",
    "wafer_space.coupons",
]
# https://docs.djangoproject.com/en/dev/ref/settings/#installed-apps
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# MIGRATIONS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#migration-modules
MIGRATION_MODULES = {"sites": "wafer_space.contrib.sites.migrations"}

# AUTHENTICATION
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#authentication-backends
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
# https://docs.djangoproject.com/en/dev/ref/settings/#auth-user-model
AUTH_USER_MODEL = "users.User"
# https://docs.djangoproject.com/en/dev/ref/settings/#login-redirect-url
LOGIN_REDIRECT_URL = "users:redirect"
# https://docs.djangoproject.com/en/dev/ref/settings/#login-url
LOGIN_URL = "account_login"

# PASSWORDS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#password-hashers
PASSWORD_HASHERS = [
    # https://docs.djangoproject.com/en/dev/topics/auth/passwords/#using-argon2-with-django
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
]
# https://docs.djangoproject.com/en/dev/ref/settings/#auth-password-validators
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# MIDDLEWARE
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#middleware
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "wafer_space.legal.middleware.TOSAcceptanceMiddleware",
    # History tracking - captures user for each change
    "simple_history.middleware.HistoryRequestMiddleware",
]

# STATIC
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#static-root
STATIC_ROOT = str(BASE_DIR / "staticfiles")
# https://docs.djangoproject.com/en/dev/ref/settings/#static-url
STATIC_URL = "/static/"
# https://docs.djangoproject.com/en/dev/ref/contrib/staticfiles/#std:setting-STATICFILES_DIRS
STATICFILES_DIRS = [str(APPS_DIR / "static")]
# https://docs.djangoproject.com/en/dev/ref/contrib/staticfiles/#staticfiles-finders
STATICFILES_FINDERS = [
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
]

# MEDIA
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#media-root
MEDIA_ROOT = str(APPS_DIR / "media")
# https://docs.djangoproject.com/en/dev/ref/settings/#media-url
MEDIA_URL = "/media/"

# TEMPLATES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#templates
TEMPLATES = [
    {
        # https://docs.djangoproject.com/en/dev/ref/settings/#std:setting-TEMPLATES-BACKEND
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # https://docs.djangoproject.com/en/dev/ref/settings/#dirs
        "DIRS": [str(APPS_DIR / "templates")],
        # https://docs.djangoproject.com/en/dev/ref/settings/#app-dirs
        "APP_DIRS": True,
        "OPTIONS": {
            # https://docs.djangoproject.com/en/dev/ref/settings/#template-context-processors
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.template.context_processors.i18n",
                "django.template.context_processors.media",
                "django.template.context_processors.static",
                "django.template.context_processors.tz",
                "django.contrib.messages.context_processors.messages",
                "wafer_space.users.context_processors.allauth_settings",
                "wafer_space.contrib.git_info.git_info",
                "wafer_space.contrib.hostname_info.hostname_info",
            ],
        },
    },
]

# https://docs.djangoproject.com/en/dev/ref/settings/#form-renderer
FORM_RENDERER = "django.forms.renderers.TemplatesSetting"

# http://django-crispy-forms.readthedocs.io/en/latest/install.html#template-packs
CRISPY_TEMPLATE_PACK = "bootstrap5"
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"

# FIXTURES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#fixture-dirs
FIXTURE_DIRS = (str(APPS_DIR / "fixtures"),)

# SECURITY
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#session-cookie-httponly
SESSION_COOKIE_HTTPONLY = True
# https://docs.djangoproject.com/en/dev/ref/settings/#csrf-cookie-httponly
CSRF_COOKIE_HTTPONLY = True
# https://docs.djangoproject.com/en/dev/ref/settings/#x-frame-options
X_FRAME_OPTIONS = "DENY"

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
EMAIL_BACKEND: str | None = None
# https://docs.djangoproject.com/en/dev/ref/settings/#email-timeout
EMAIL_TIMEOUT = 5

DEFAULT_FROM_EMAIL = "wafer.space Platform <noreply@platform.wafer.space>"
SERVER_EMAIL = DEFAULT_FROM_EMAIL
EMAIL_SUBJECT_PREFIX = "[wafer.space] "
ACCOUNT_EMAIL_SUBJECT_PREFIX = EMAIL_SUBJECT_PREFIX

# ADMIN
# ------------------------------------------------------------------------------
# Django Admin URL.
ADMIN_URL = "admin/"
# https://docs.djangoproject.com/en/dev/ref/settings/#admins
ADMINS = [("""Tim 'mithro' Ansell""", "tim@wafer.space")]
# https://docs.djangoproject.com/en/dev/ref/settings/#managers
MANAGERS = ADMINS
# https://cookiecutter-django.readthedocs.io/en/latest/settings.html#other-environment-settings
# Force the `admin` sign in process to go through the `django-allauth` workflow
DJANGO_ADMIN_FORCE_ALLAUTH = env.bool("DJANGO_ADMIN_FORCE_ALLAUTH", default=False)

# LOGGING
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#logging
# See https://docs.djangoproject.com/en/dev/topics/logging for
# more details on how to customize your logging configuration.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(levelname)s %(asctime)s %(module)s %(process)d %(thread)d %(message)s",
        },
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {"level": "INFO", "handlers": ["console"]},
}

# django-allauth
# ------------------------------------------------------------------------------
ACCOUNT_ALLOW_REGISTRATION = env.bool("DJANGO_ACCOUNT_ALLOW_REGISTRATION", True)
# https://docs.allauth.org/en/latest/account/configuration.html
ACCOUNT_LOGIN_METHODS = {"username"}
# https://docs.allauth.org/en/latest/account/configuration.html
ACCOUNT_SIGNUP_FIELDS = ["email*", "username*", "password1*", "password2*"]
# https://docs.allauth.org/en/latest/account/configuration.html
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
# https://docs.allauth.org/en/latest/account/configuration.html
ACCOUNT_ADAPTER = "wafer_space.users.adapters.AccountAdapter"
# https://docs.allauth.org/en/latest/account/forms.html
ACCOUNT_FORMS = {"signup": "wafer_space.users.forms.UserSignupForm"}
# https://docs.allauth.org/en/latest/socialaccount/configuration.html
SOCIALACCOUNT_ADAPTER = "wafer_space.users.adapters.SocialAccountAdapter"
# https://docs.allauth.org/en/latest/socialaccount/configuration.html
SOCIALACCOUNT_FORMS = {"signup": "wafer_space.users.forms.UserSocialSignupForm"}

# Social Account Providers Configuration
# ------------------------------------------------------------------------------
SOCIALACCOUNT_PROVIDERS = {
    "github": {
        "APP": {
            "client_id": None,
            "secret": None,
        },
        "SCOPE": [
            "user:email",
        ],
        "VERIFIED_EMAIL": True,
    },
    "gitlab": {
        "APP": {
            "client_id": None,
            "secret": None,
        },
        "SCOPE": [
            "read_user",
            "email",
        ],
        "VERIFIED_EMAIL": True,
    },
    "google": {
        "APP": {
            "client_id": None,
            "secret": None,
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
        "APPS": [
            {
                "provider_id": "linkedin",
                "name": "LinkedIn",
                "client_id": None,
                "secret": None,
                "settings": {
                    "server_url": "https://www.linkedin.com/oauth",
                },
            }
        ],
        # OpenID Connect scope is automatically handled by the provider
        # LinkedIn requires: openid, profile, email
    },
    "discord": {
        "APP": {
            "client_id": None,
            "secret": None,
        },
        "SCOPE": [
            "identify",
            "email",
        ],
        "VERIFIED_EMAIL": True,
    },
}

# Auto-link social accounts to existing email accounts
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_EMAIL_VERIFICATION = "none"  # Use email from social provider if verified
SOCIALACCOUNT_LOGIN_ON_GET = (
    True  # Skip intermediate confirmation page before OAuth redirect
)

# Enable email-based authentication and automatic account linking
# This allows users to login with any OAuth provider that has a matching verified email
# and automatically connects the social account to their existing account
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True

# Celery Configuration
# ------------------------------------------------------------------------------
# IMPORTANT: This project uses PostgreSQL as the Celery broker via SQLAlchemy.
# Redis and RabbitMQ are BANNED - they add unnecessary deployment complexity
# for a project that will never operate at scale requiring dedicated message brokers.
# Convert DATABASE_URL to sqla+postgresql:// format for Celery broker
_database_url = env("DATABASE_URL", default="postgres:///wafer_space")
if _database_url.startswith("postgres://"):
    _database_url = _database_url.replace("postgres://", "postgresql://", 1)
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=f"sqla+{_database_url}")
CELERY_RESULT_BACKEND = "django-db"
CELERY_CACHE_BACKEND = "django-cache"

# Celery task configuration
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_ENABLE_UTC = True

# Task routing and execution
CELERY_TASK_ALWAYS_EAGER = False  # Set to True for synchronous testing
CELERY_TASK_EAGER_PROPAGATES = True

# Task result configuration
CELERY_RESULT_EXPIRES = 3600  # Results expire after 1 hour
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 minutes hard time limit
CELERY_TASK_SOFT_TIME_LIMIT = 25 * 60  # 25 minutes soft time limit

# Download task configuration
# Celery retry settings for download tasks (built-in retry mechanism)
DOWNLOAD_TASK_MAX_RETRIES = 2  # Total of 3 attempts (initial + 2 retries)
DOWNLOAD_TASK_RETRY_BASE_DELAY_SECONDS = 60  # 1 minute base delay
DOWNLOAD_TASK_RETRY_BACKOFF_MULTIPLIER = 2  # Exponential backoff: 60s, 120s

# Download state verification configuration
# Fallback system to detect orphaned tasks and recover from queue loss
DOWNLOAD_STATE_CHECK_INTERVAL_SECONDS = 60.0  # Check every 1 minute

# Docker client configuration
# ------------------------------------------------------------------------------
# Timeout for Docker SDK HTTP client (default 60s is too short for some operations)
DOCKER_CLIENT_TIMEOUT = 300  # 5 minutes

# Precheck (Manufacturability Checking) configuration
# See: Design document for manufacturability checking implementation
PRECHECK_DOCKER_IMAGE = "ghcr.io/wafer-space/gf180mcu-precheck:latest"
PRECHECK_CONCURRENT_LIMIT = 4
PRECHECK_TIMEOUT_SECONDS = 20 * 60 * 60  # 20 hours hard limit
PRECHECK_SOFT_TIMEOUT_BUFFER = 60 * 60  # 1 hour buffer before hard limit
PRECHECK_SCAN_INTERVAL_SECONDS = 30.0  # Scan for files ready to check every 30s

# Docker server configuration
# Servers are selected in priority order (lowest number = highest priority)
# Override in environment-specific settings
DOCKER_SERVERS: list[dict[str, str | int]] = []

# Celery Beat periodic tasks
CELERY_BEAT_SCHEDULE = {
    # Download recovery
    "ensure-download-tasks-queued": {
        "task": "wafer_space.projects.tasks.ensure_download_tasks_queued",
        "schedule": DOWNLOAD_STATE_CHECK_INTERVAL_SECONDS,
    },
    # Manufacturability check lifecycle - polling architecture (15s intervals)
    # Each task polls for checks in a specific state and advances them to the next state
    "checks-pending": {
        "task": "wafer_space.projects.tasks.checks_pending",
        "schedule": 15.0,
    },
    "checks-dispatching": {
        "task": "wafer_space.projects.tasks.checks_dispatching",
        "schedule": 15.0,
    },
    "checks-starting": {
        "task": "wafer_space.projects.tasks.checks_starting",
        "schedule": 15.0,
    },
    "checks-running": {
        "task": "wafer_space.projects.tasks.checks_running",
        "schedule": 15.0,
    },
    "checks-analyzing": {
        "task": "wafer_space.projects.tasks.checks_analyzing",
        "schedule": 15.0,
    },
    "checks-cancelling": {
        "task": "wafer_space.projects.tasks.checks_cancelling",
        "schedule": 15.0,
    },
    # Cleanup and retry tasks (60s intervals)
    "checks-retry": {
        "task": "wafer_space.projects.tasks.checks_retry",
        "schedule": 60.0,
    },
    "checks-cleanup-orphaned-docker": {
        "task": "wafer_space.projects.tasks.checks_cleanup_orphaned_docker",
        "schedule": 60.0,
    },
    "checks-cleanup-stale-files": {
        "task": "wafer_space.projects.tasks.checks_cleanup_stale_files",
        "schedule": 60.0,
    },
}

# File Download and Processing Configuration
# ------------------------------------------------------------------------------
# Maximum file size limits for downloads and content extraction
MAX_DOWNLOAD_SIZE = 100 * 1024 * 1024 * 1024  # 100GB raw download
MAX_EXTRACTED_SIZE = 10 * 1024 * 1024 * 1024  # 10GB after extraction/decompression

# GitHub API Configuration
# ------------------------------------------------------------------------------
# GitHub Personal Access Token for Actions artifact downloads
# Requires 'actions:read' permission scope
# Must be set via environment variable when downloading GitHub artifacts
GITHUB_TOKEN = env("GITHUB_TOKEN", default=None)

# Your stuff...
# ------------------------------------------------------------------------------
