"""Django settings for climpact-web, read from environment variables.

There is one settings module for both ways the app runs, chosen by ``CLIMPACT_WEB_MODE``:

``local`` (the default)
    The offline install started by the ``climpact-web`` command: SQLite and run files in the
    user's data folder, ``DEBUG`` off, static files collected into the data folder when
    the command starts and served by WhiteNoise (with the package as a fallback), bound to
    localhost.
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
from django.utils.csp import CSP
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
    "climpact_web.gridded",
    "climpact_web.help",
    "climpact_web.charts",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "climpact_web.middleware.ContentSecurityPolicyMiddleware",  # SECURE_CSP below (#137)
    "climpact_web.middleware.StaticFilesMiddleware",  # WhiteNoise
    "climpact_web.middleware.PrivateCacheMiddleware",  # no shared caching of the rest
    "climpact_web.middleware.CompressionMiddleware",  # gzip for pages and fragments
    "climpact_web.middleware.UploadSizeLimitMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "climpact_web.middleware.RefusalMiddleware",  # the hosted limits' refusals (#125)
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

# Static files: shipped inside the package (core/static). `collectstatic` writes hashed,
# minified (CSS) and compressed (gzip, Brotli) copies that WhiteNoise serves with a
# one-year cache (core/storage.py; TECHNICAL.md, "Size budget"). Hosted mode collects into
# STATIC_ROOT at deployment. Local mode collects into the data folder when `climpact-web`
# starts, and WhiteNoise's finders serve any file not collected straight from the package
# (with DEBUG, nothing is collected, so edits show at once).
STATIC_URL = "static/"
STATIC_ROOT = Path(env("STATIC_ROOT")) if env("STATIC_ROOT") else None
if IS_HOSTED:
    if STATIC_ROOT is None:
        raise ImproperlyConfigured("CLIMPACT_WEB_STATIC_ROOT must be set in hosted mode")
    static_backend = "climpact_web.core.storage.StaticFilesStorage"
else:
    STATIC_ROOT = STATIC_ROOT or DATA_DIR / "static"
    WHITENOISE_USE_FINDERS = True
    WHITENOISE_AUTOREFRESH = DEBUG
    static_backend = (
        "django.contrib.staticfiles.storage.StaticFilesStorage"
        if DEBUG
        else "climpact_web.core.storage.LocalStaticFilesStorage"
    )
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": static_backend},
}

# Uploaded files and run outputs: each job has its own folder under RUNS_DIR.
MEDIA_URL = "media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT") or DATA_DIR / "media")
RUNS_DIR = MEDIA_ROOT / "runs"

# Background jobs (climpact_web.jobs; TECHNICAL.md, "Background jobs").
# Days a finished job and its files are kept; the upload page states it.
JOB_RETENTION_DAYS = int(env("RETENTION_DAYS", "7"))
# Whether workspaces (#231: their stations, batch and files, and the jobs they show) are
# deleted JOB_RETENTION_DAYS after their last change. On when hosted; off locally, where a
# workspace stays on the computer until the user deletes it.
WORKSPACE_EXPIRY = env_bool("WORKSPACE_EXPIRY", IS_HOSTED)
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

# Abuse limits for the hosted site (#125; TECHNICAL.md, "Security of the hosted site").
# None of them applies in local mode. Cloudflare Turnstile (a check that the visitor is a
# person) guards the forms that upload files or start a job, and is on only when both of
# its keys are set (Cloudflare dashboard > Turnstile > the widget). The quotas count jobs
# per client address, read from Cloudflare's CF-Connecting-IP header (the origin is
# reachable only through the tunnel); 0 turns a limit off.
TURNSTILE_SITE_KEY = env("TURNSTILE_SITE_KEY", "")
TURNSTILE_SECRET_KEY = env("TURNSTILE_SECRET_KEY", "")
if bool(TURNSTILE_SITE_KEY) != bool(TURNSTILE_SECRET_KEY):
    raise ImproperlyConfigured(
        "Set both CLIMPACT_WEB_TURNSTILE_SITE_KEY and CLIMPACT_WEB_TURNSTILE_SECRET_KEY, or neither"
    )
TURNSTILE_ORIGIN = "https://challenges.cloudflare.com"
TURNSTILE_VERIFY_URL = f"{TURNSTILE_ORIGIN}/turnstile/v0/siteverify"
TURNSTILE_TIMEOUT = 10  # seconds to wait for Cloudflare's answer
# Jobs waiting or running for one client address, and jobs started by it in 24 hours. The
# jobs of one change (a workspace recalculating all its stations, #254) count as one.
MAX_ACTIVE_JOBS_PER_IP = int(env("MAX_ACTIVE_JOBS_PER_IP", "2"))
MAX_DAILY_JOBS_PER_IP = int(env("MAX_DAILY_JOBS_PER_IP", "50"))
# No new jobs while more than this many wait in the queue, or while MEDIA_ROOT's disk has
# less than this much free space (uploads are refused too).
MAX_QUEUED_JOBS = int(env("MAX_QUEUED_JOBS", "20"))
# Hosted mode: a speculative station run (#178: the defaults calculated while the user looks
# at the quality checks) is queued only while fewer than this many jobs wait; 0 turns it
# off. Local mode always queues it.
SPECULATIVE_MAX_QUEUED = int(env("SPECULATIVE_MAX_QUEUED", "3"))
MIN_FREE_DISK_GB = float(env("MIN_FREE_DISK_GB", "2"))
# Wall-clock limit on one job: the worker stops it at its next progress step, and fails it
# outright (exiting, to be restarted) if it is still running a grace period later.
JOB_TIME_LIMIT_MINUTES = float(env("JOB_TIME_LIMIT_MINUTES", "60"))
JOB_TIME_LIMIT_GRACE_SECONDS = 60.0

# Largest request body accepted, uploads included (UploadSizeLimitMiddleware answers 413).
# Station files are a few MB; gridded files are read from disk in local mode (#85).
MAX_UPLOAD_MB = int(env("MAX_UPLOAD_MB", "50"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

# Gridded (netCDF) runs (#85): on in the local install, as in R; off in hosted mode unless
# CLIMPACT_WEB_GRIDDED_HOSTED is set (large uploads and long jobs; decided 2026-11-14).
# Local mode reads the files in place from paths on this computer; uploads (both modes)
# may be larger than other requests, up to GRIDDED_MAX_UPLOAD_MB in all.
GRIDDED_ENABLED = env_bool("GRIDDED_HOSTED", False) if IS_HOSTED else True
GRIDDED_MAX_UPLOAD_MB = int(env("GRIDDED_MAX_UPLOAD_MB", "200"))
GRIDDED_MAX_UPLOAD_BYTES = GRIDDED_MAX_UPLOAD_MB * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2_621_440  # Django's default: larger uploads go to a temp file
DATA_UPLOAD_MAX_MEMORY_SIZE = 2_621_440  # non-file form data
# More files in one request than any form takes (a gridded run up to 200, #291; a batch up
# to 500), so that the form says "Choose at most ..." instead of Django refusing the
# request (its default is 100). The size of a request stays capped as above.
DATA_UPLOAD_MAX_NUMBER_FILES = 1000

# Security headers for both modes; HTTPS-only settings for hosted mode, which sits behind a
# TLS-terminating proxy that sets X-Forwarded-Proto.
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"  # for old browsers; the CSP's frame-ancestors replaces it
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
if IS_HOSTED:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(env("HSTS_SECONDS", "0"))
    # Sent only when SECURE_HSTS_SECONDS > 0. Every subdomain of climpact.app is HTTPS
    # anyway (the .app TLD is on the browsers' HSTS preload list); no `preload` needed.
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    # The health check is fetched by the load balancer over plain HTTP.
    SECURE_REDIRECT_EXEMPT = [r"^healthz$"]


# Content Security Policy (#137; TECHNICAL.md, "Content Security Policy"), the same in both
# modes so violations show in development too. Pages load only same-origin files: no
# inline scripts, inline styles or style attributes (CSS custom properties come from
# classes, sizes from SVG attributes), and htmx runs without eval (the htmx-config meta in
# base.html). The one inline element is the stand-alone 500 page's <style>, allowed by its
# hash (test_csp.py checks it matches the template).
ERROR_PAGE_STYLE_HASH = "'sha256-3QU1IXV6xmQNVSeg+4AUl4ZTe0tAt89iFQwqOK7Wp70='"
# Cloudflare Web Analytics (#164): the beacon script Cloudflare's edge adds to every page
# when the zone's automatic setup is on, and the address it reports to without a version
# in its settings (with one, as injected, it reports to /cdn-cgi/rum on this origin).
WEB_ANALYTICS_SCRIPT_ORIGIN = "https://static.cloudflareinsights.com"
WEB_ANALYTICS_REPORT_ORIGIN = "https://cloudflareinsights.com"


def content_security_policy(turnstile: bool, analytics: bool = False) -> dict[str, list[str]]:
    """The policy's directives.

    ``script-src`` always has a per-response nonce (``CSP.NONCE``; #164). No template uses
    it: it is there for the scripts Cloudflare's edge injects (JavaScript detections), to
    which Cloudflare copies the nonce it finds in the header. With ``turnstile``, Cloudflare
    Turnstile's script and the challenge frame it shows are allowed from its origin; with
    ``analytics``, Cloudflare Web Analytics' beacon script and its reports.
    """
    turnstile_src = [TURNSTILE_ORIGIN] if turnstile else []
    script_analytics = [WEB_ANALYTICS_SCRIPT_ORIGIN] if analytics else []
    connect_analytics = [WEB_ANALYTICS_REPORT_ORIGIN] if analytics else []
    return {
        "default-src": [CSP.SELF],
        "script-src": [CSP.SELF, CSP.NONCE, *turnstile_src, *script_analytics],
        "style-src": [CSP.SELF, ERROR_PAGE_STYLE_HASH],
        "img-src": [CSP.SELF, "data:"],
        "font-src": [CSP.SELF],
        "connect-src": [CSP.SELF, *connect_analytics],
        "frame-src": turnstile_src or [CSP.NONE],
        "object-src": [CSP.NONE],
        "base-uri": [CSP.NONE],
        "form-action": [CSP.SELF],
        "frame-ancestors": [CSP.NONE],
    }


# Turnstile is on in hosted mode with both keys set (core/limits.py, turnstile_enabled).
# CLIMPACT_WEB_CF_WEB_ANALYTICS (hosted mode, on by default): allow Cloudflare Web
# Analytics; false when the zone's Web Analytics is off. Never in local mode, where no
# Cloudflare edge adds the beacon.
WEB_ANALYTICS = IS_HOSTED and env_bool("CF_WEB_ANALYTICS", True)
CSP_POLICY = content_security_policy(
    turnstile=IS_HOSTED and bool(TURNSTILE_SITE_KEY and TURNSTILE_SECRET_KEY),
    analytics=WEB_ANALYTICS,
)
# CLIMPACT_WEB_CSP_REPORT_ONLY: report violations (in the browser console) without
# blocking anything, for a first deployment; the policy is enforced by default.
if env_bool("CSP_REPORT_ONLY", False):
    SECURE_CSP, SECURE_CSP_REPORT_ONLY = {}, CSP_POLICY
else:
    SECURE_CSP, SECURE_CSP_REPORT_ONLY = CSP_POLICY, {}


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
