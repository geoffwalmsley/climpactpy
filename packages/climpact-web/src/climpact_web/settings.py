"""Django settings for climpact-web, read from environment variables.

There is one settings module for both ways the app runs, chosen by ``CLIMPACT_WEB_MODE``:

``local`` (the default)
    The offline install started by the ``climpact-web`` command: SQLite and run files in the
    user's data folder, ``DEBUG`` off, static files served by WhiteNoise straight from the
    package, bound to localhost.
``hosted``
    The server deployment (#12): the database from ``DATABASE_URL`` (Postgres), and the
    secret key and allowed hosts must be set; secure cookies, HTTPS behind a proxy.

Reading this module has no side effects (no folders or files are created); the
``climpact-web`` command prepares the data folder before starting the server. Every
variable is listed in TECHNICAL.md ("Web front end").
"""

import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from django.core.management.utils import get_random_secret_key
from django.utils.translation import gettext_lazy as _
from platformdirs import user_data_dir

PACKAGE_DIR = Path(__file__).resolve().parent

LOCAL = "local"
HOSTED = "hosted"


def env(name: str, default: str | None = None) -> str | None:
    """A ``CLIMPACT_WEB_<name>`` environment variable; empty counts as unset."""
    value = os.environ.get(f"CLIMPACT_WEB_{name}", "").strip()
    return value or default


def env_bool(name: str, default: bool) -> bool:
    value = env(name)
    if value is None:
        return default
    if value.lower() in {"1", "true", "yes", "on"}:
        return True
    if value.lower() in {"0", "false", "no", "off"}:
        return False
    raise ImproperlyConfigured(f"CLIMPACT_WEB_{name} must be true or false, not {value!r}")


def env_list(name: str, default: list[str]) -> list[str]:
    value = env(name)
    if value is None:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


MODE = env("MODE", LOCAL).lower()
if MODE not in {LOCAL, HOSTED}:
    raise ImproperlyConfigured(f"CLIMPACT_WEB_MODE must be 'local' or 'hosted', not {MODE!r}")
IS_HOSTED = MODE == HOSTED

# Where the local install keeps its database, secret key and run files.
DATA_DIR = Path(env("DATA_DIR") or user_data_dir("climpact-web", appauthor=False))

DEBUG = env_bool("DEBUG", False)

# The pattern library at /patterns/ (every UI component, for design review and the
# accessibility audit): on with DEBUG, or on its own with CLIMPACT_WEB_PATTERN_LIBRARY.
PATTERN_LIBRARY = env_bool("PATTERN_LIBRARY", DEBUG)

# Secret key: the environment, else (local mode) the file `climpact-web` writes on first
# start, else (local mode, e.g. tests) a throwaway key for this process.
SECRET_KEY = env("SECRET_KEY")
if SECRET_KEY is None:
    if IS_HOSTED:
        raise ImproperlyConfigured("CLIMPACT_WEB_SECRET_KEY must be set in hosted mode")
    key_file = DATA_DIR / "secret_key"
    SECRET_KEY = key_file.read_text().strip() if key_file.is_file() else get_random_secret_key()

if IS_HOSTED:
    ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", [])
    if not ALLOWED_HOSTS:
        raise ImproperlyConfigured("CLIMPACT_WEB_ALLOWED_HOSTS must be set in hosted mode")
else:
    ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", ["localhost", "127.0.0.1", "[::1]"])
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", [])

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "climpact_web.core",
    "climpact_web.jobs",
    "climpact_web.stations",
    "climpact_web.batch",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "climpact_web.middleware.UploadSizeLimitMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "climpact_web.urls"
WSGI_APPLICATION = "climpact_web.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.i18n",
                "django.contrib.messages.context_processors.messages",
                "climpact_web.core.context_processors.site",
                "climpact_web.jobs.context_processors.jobs",
            ],
        },
    },
]

# Database: DATABASE_URL (Postgres in hosted mode, needs the `postgres` extra), else SQLite
# in the data folder. Tests always use an in-memory SQLite database.
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if DATABASE_URL:
    DATABASES = {"default": dj_database_url.parse(DATABASE_URL, conn_max_age=600)}
elif IS_HOSTED:
    raise ImproperlyConfigured("DATABASE_URL must be set in hosted mode")
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": DATA_DIR / "db.sqlite3",
            # The web server and the worker process write to the same file: WAL lets
            # readers carry on during a write, writers wait for each other (timeout, in
            # seconds) and take the write lock when a transaction starts (IMMEDIATE), which
            # avoids SQLite's "database is locked" on upgrading a read lock.
            "OPTIONS": {
                "timeout": 20,
                "transaction_mode": "IMMEDIATE",
                "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
            },
        }
    }
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SESSION_ENGINE = "django.contrib.sessions.backends.db"

# Internationalisation: English only for now; the language switcher appears once LANGUAGES
# has a second entry and its catalogue is in locale/.
LANGUAGE_CODE = "en"
LANGUAGES = [("en", _("English"))]
LOCALE_PATHS = [PACKAGE_DIR / "locale"]
USE_I18N = True
USE_TZ = True
TIME_ZONE = "UTC"

# Static files: shipped inside the package (core/static). Local mode serves them with
# WhiteNoise straight from the package (no collectstatic); hosted mode collects them into
# STATIC_ROOT with hashed, compressed copies.
STATIC_URL = "static/"
STATIC_ROOT = Path(env("STATIC_ROOT")) if env("STATIC_ROOT") else None
if IS_HOSTED:
    if STATIC_ROOT is None:
        raise ImproperlyConfigured("CLIMPACT_WEB_STATIC_ROOT must be set in hosted mode")
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
else:
    WHITENOISE_USE_FINDERS = True
    WHITENOISE_AUTOREFRESH = DEBUG

# Uploaded files and run outputs: each job has its own folder under RUNS_DIR.
MEDIA_URL = "media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT") or DATA_DIR / "media")
RUNS_DIR = MEDIA_ROOT / "runs"

# Background jobs (climpact_web.jobs; TECHNICAL.md, "Background jobs").
# Days a finished job and its files are kept; the upload page states it.
JOB_RETENTION_DAYS = int(env("RETENTION_DAYS", "7"))
# Seconds between worker heartbeats, and without one before a running job counts as dead.
JOB_HEARTBEAT_SECONDS = float(env("JOB_HEARTBEAT_SECONDS", "10"))
JOB_STALE_SECONDS = float(env("JOB_STALE_SECONDS", "60"))
# Seconds between a worker's checks for queued jobs, between progress writes, and between
# purges of expired jobs.
JOB_POLL_SECONDS = float(env("JOB_POLL_SECONDS", "1"))
JOB_PROGRESS_INTERVAL = 0.5
JOB_CLEANUP_INTERVAL = 3600
# Where job folders live (the hook for S3 in hosted mode, #12).
JOB_STORAGE = env("JOB_STORAGE", "climpact_web.jobs.storage.LocalJobStorage")

# Largest request body accepted, uploads included (UploadSizeLimitMiddleware answers 413).
# Station files are a few MB; gridded files are read from disk in local mode (#85).
MAX_UPLOAD_MB = int(env("MAX_UPLOAD_MB", "50"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2_621_440  # Django's default: larger uploads go to a temp file
DATA_UPLOAD_MAX_MEMORY_SIZE = 2_621_440  # non-file form data

# Security headers for both modes; HTTPS-only settings for hosted mode, which sits behind a
# TLS-terminating proxy that sets X-Forwarded-Proto.
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
if IS_HOSTED:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(env("HSTS_SECONDS", "0"))
    # The health check is fetched by the load balancer over plain HTTP.
    SECURE_REDIRECT_EXEMPT = [r"^healthz$"]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    # Warnings and errors from every library (django.request logs server errors); the
    # app's own messages from CLIMPACT_WEB_LOG_LEVEL up.
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "climpact_web": {"level": env("LOG_LEVEL", "INFO")},
        "climpact": {"level": env("LOG_LEVEL", "INFO")},
        # xclim redefines pint units on import, which pint reports as warnings
        "pint.util": {"level": "ERROR"},
    },
}
