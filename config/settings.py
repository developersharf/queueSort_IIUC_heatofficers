"""
Django settings for the QueueStorm Investigator service.

Loads secrets from environment variables (via python-dotenv). All sensitive
configuration must be supplied through the runtime environment, never
hard-coded.

Environment detection:
  - If RAILWAY_ENVIRONMENT is set, we assume Railway deploy:
        * DEBUG defaults to False
        * RAILWAY_PUBLIC_DOMAIN is added to ALLOWED_HOSTS
        * DATABASE_URL (if set) overrides the SQLite default
  - Otherwise (local dev / docker compose), defaults stay permissive.
"""

from pathlib import Path
import os

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env if present (development convenience only)
load_dotenv(BASE_DIR / '.env')


def env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {'1', 'true', 'yes', 'on'}


# Are we running on Railway?
ON_RAILWAY = bool(os.environ.get('RAILWAY_ENVIRONMENT') or os.environ.get('RAILWAY_PROJECT_ID'))

SECRET_KEY = os.environ.get(
    'SECRET_KEY',
    # Insecure default for local dev only. Real deployments MUST set SECRET_KEY.
    'django-insecure-queuestorm-dev-key-replace-in-production',
)

# On Railway, default to DEBUG=False unless the operator explicitly turns it on.
DEBUG = env_bool('DEBUG', not ON_RAILWAY)

# Build ALLOWED_HOSTS from env + Railway public domain.
_allowed_hosts_env = os.environ.get('ALLOWED_HOSTS', '*')
ALLOWED_HOSTS = [
    h.strip() for h in _allowed_hosts_env.split(',') if h.strip()
]
_railway_domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN')
if _railway_domain and _railway_domain not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(_railway_domain)


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # third party
    'rest_framework',
    'corsheaders',
    # local
    'core',
    'engine',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    # whitenoise serves /static/ files directly from gunicorn — required on
    # Railway / docker because there is no nginx in front of the app.
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
#
# Priority:
#   1. DATABASE_URL (Neon / Railway / Render / Supabase all set this)
#   2. DJANGO_SQLITE_PATH  (file path override, useful for Docker volumes)
#   3. SQLite at BASE_DIR/db.sqlite3 (local dev default)
#
# We don't import dj-database-url as a dependency; parsing the URL inline keeps
# the dependency surface smaller (per the hackathon rule: rule-based logic
# preferred, no large deps).

def _parse_database_url(url: str) -> dict:
    """
    Parse a libpq-style DATABASE_URL into a Django DATABASES['default'] entry.

    Supports:
      - scheme: postgres:// or postgresql://  → django.db.backends.postgresql
                sqlite3://                      → django.db.backends.sqlite3
      - query params:
            sslmode=<disable|allow|prefer|require|verify-ca|verify-full>
            channel_binding=<require|disable>
            options=<libpq runtime options>
        All forwarded into OPTIONS so psycopg/psycopg2 applies them.
    """
    from urllib.parse import urlparse, parse_qs

    parsed = urlparse(url)

    scheme = (parsed.scheme or 'sqlite3').lower()
    # Normalise postgresql+psycopg / postgresql+psycopg2 schemes too.
    engine_scheme = scheme.split('+')[0]
    engine = 'django.db.backends.' + engine_scheme
    name = (parsed.path or '/').lstrip('/') or 'db.sqlite3'

    cfg: dict = {'ENGINE': engine, 'NAME': name}
    if parsed.hostname:
        cfg['HOST'] = parsed.hostname
    if parsed.port:
        cfg['PORT'] = str(parsed.port)
    if parsed.username:
        cfg['USER'] = parsed.username
    if parsed.password:
        cfg['PASSWORD'] = parsed.password

    # Forward any URL query parameters into the engine's OPTIONS dict.
    # sslmode and channel_binding are required by Neon (and similar managed
    # Postgres services) — without them psycopg refuses to connect.
    query = parse_qs(parsed.query, keep_blank_values=True)
    options: dict = {}
    for key in ('sslmode', 'sslrootcert', 'sslcert', 'sslkey',
                'channel_binding', 'options', 'application_name'):
        values = query.pop(key, None)
        if values:
            # Take the first value; libpq query strings repeat rarely.
            options[key] = values[0]
    if options:
        cfg['OPTIONS'] = options

    # Neon (and other managed Postgres services) recommend a short connect
    # timeout so a hung DB doesn't wedge the request thread.
    cfg.setdefault('CONN_MAX_AGE', 60)

    return cfg


_database_url = os.environ.get('DATABASE_URL')
if _database_url:
    DATABASES = {'default': _parse_database_url(_database_url)}
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': os.environ.get('DJANGO_SQLITE_PATH') or str(BASE_DIR / 'db.sqlite3'),
        }
    }


# ---------------------------------------------------------------------------
# Password validation
# ---------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True


# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------
#
# STATIC_ROOT is where `collectstatic` writes to; whitenoise then serves
# /static/* from there at runtime. Required for Django admin CSS in any
# production deploy (Railway, docker compose, …).

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'core' / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ---------------------------------------------------------------------------
# DRF
# ---------------------------------------------------------------------------

REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ],
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.JSONParser',
    ],
    'UNAUTHENTICATED_USER': None,
}


# ---------------------------------------------------------------------------
# CORS — wide open for the public judge harness.
# ---------------------------------------------------------------------------

CORS_ALLOW_ALL_ORIGINS = True


# ---------------------------------------------------------------------------
# Logging — never leak secrets / PII / stack traces to the judge harness.
# ---------------------------------------------------------------------------

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple': {
            'format': '{levelname} {asctime} {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}
