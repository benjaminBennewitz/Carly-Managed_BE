# config/settings/base.py
"""Gemeinsame, sicherheitsorientierte Django-Einstellungen."""

from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import environ
from celery.schedules import crontab

from config.environment import load_environment

BASE_DIR = Path(__file__).resolve().parents[2]
load_environment()

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    SESSION_COOKIE_SECURE=(bool, True),
    CSRF_COOKIE_SECURE=(bool, True),
    SECURE_SSL_REDIRECT=(bool, True),
    SESSION_COOKIE_AGE=(int, 60 * 60 * 24 * 30),
    SECURE_HSTS_SECONDS=(int, 31_536_000),
    FILE_UPLOAD_MAX_BYTES=(int, 10 * 1024 * 1024),
    LOGIN_FAILURE_LIMIT=(int, 5),
    LOGIN_LOCK_MINUTES=(int, 15),
    TRUST_X_FORWARDED_FOR=(bool, False),
    DB_CONN_MAX_AGE=(int, 60),
    DB_CONN_HEALTH_CHECKS=(bool, True),
    REDIS_PORT=(int, 6379),
    REDIS_USE_ACL=(bool, False),
    REDIS_CHANNEL_DB=(int, 0),
    REDIS_CACHE_DB=(int, 1),
    REDIS_CELERY_DB=(int, 2),
    REDIS_SOCKET_CONNECT_TIMEOUT=(float, 5.0),
    REDIS_SOCKET_TIMEOUT=(float, 15.0),
    REDIS_HEALTH_CHECK_INTERVAL=(int, 30),
    REDIS_RETRY_ON_TIMEOUT=(bool, True),
    EMAIL_PORT=(int, 587),
    EMAIL_USE_TLS=(bool, True),
    EMAIL_USE_SSL=(bool, False),
    EMAIL_TIMEOUT=(int, 10),
)


def _database_url() -> str:
    """Erstellt eine PostgreSQL-URL aus getrennten, sicher kodierten Werten."""
    explicit_url = env("DATABASE_URL", default="").strip()
    if explicit_url:
        return explicit_url

    name = quote(env("DB_NAME", default="carly_managed"), safe="")
    user = quote(env("DB_USER", default="carly_admin"), safe="")
    password = quote(env("DB_PASSWORD", default=""), safe="")
    host = env("DB_HOST", default="127.0.0.1")
    port = env.int("DB_PORT", default=5432)
    credentials = f"{user}:{password}@" if password else f"{user}@"
    return f"postgresql://{credentials}{host}:{port}/{name}"


def _redis_url(database_number: int, explicit_variable: str) -> str:
    """Erstellt eine Redis-URL und trennt die logischen Datenbanken sauber."""
    explicit_url = env(explicit_variable, default="").strip()
    if explicit_url:
        return explicit_url

    shared_url = env("REDIS_URL", default="").strip()
    if shared_url:
        parsed = urlsplit(shared_url)
        return urlunsplit((parsed.scheme, parsed.netloc, f"/{database_number}", "", ""))

    scheme = env("REDIS_SCHEME", default="redis")
    host = env("REDIS_HOST", default="127.0.0.1")
    port = env.int("REDIS_PORT")
    password = quote(env("REDIS_PASSWORD", default=""), safe="")
    username = quote(env("REDIS_USERNAME", default="default"), safe="")
    use_acl = env.bool("REDIS_USE_ACL")

    if password and use_acl:
        authority = f"{username}:{password}@{host}:{port}"
    elif password:
        authority = f":{password}@{host}:{port}"
    else:
        authority = f"{host}:{port}"
    return f"{scheme}://{authority}/{database_number}"


SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "django_filters",
    "rest_framework",
    "drf_spectacular",
    "channels",
    "apps.common.apps.CommonConfig",
    "apps.accounts.apps.AccountsConfig",
    "apps.workspaces.apps.WorkspacesConfig",
    "apps.inbox.apps.InboxConfig",
    "apps.preferences.apps.PreferencesConfig",
    "apps.realtime.apps.RealtimeConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {"default": env.db_url_config(_database_url())}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE")
DATABASES["default"]["CONN_HEALTH_CHECKS"] = env.bool("DB_CONN_HEALTH_CHECKS")

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    {"NAME": "apps.accounts.validators.ControlCharacterPasswordValidator"},
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

LANGUAGE_CODE = "de-de"
TIME_ZONE = "Europe/Berlin"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"
SESSION_COOKIE_NAME = "cm_session"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = env("SESSION_COOKIE_SECURE")
SESSION_COOKIE_SAMESITE = env("SESSION_COOKIE_SAMESITE", default="Lax")
SESSION_COOKIE_DOMAIN = env("SESSION_COOKIE_DOMAIN", default=None) or None
SESSION_COOKIE_AGE = env.int("SESSION_COOKIE_AGE")
SESSION_SAVE_EVERY_REQUEST = False

CSRF_COOKIE_NAME = "cm_csrftoken"
CSRF_COOKIE_SECURE = env("CSRF_COOKIE_SECURE")
CSRF_COOKIE_SAMESITE = env("CSRF_COOKIE_SAMESITE", default="Lax")
CSRF_COOKIE_DOMAIN = env("CSRF_COOKIE_DOMAIN", default=None) or None
CSRF_COOKIE_HTTPONLY = False
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

CORS_ALLOWED_ORIGINS = env.list("DJANGO_CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = [
    "accept",
    "accept-language",
    "content-type",
    "if-match",
    "x-csrftoken",
    "x-requested-with",
]

SECURE_SSL_REDIRECT = env("SECURE_SSL_REDIRECT")
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS")
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
X_FRAME_OPTIONS = "DENY"

DATA_UPLOAD_MAX_MEMORY_SIZE = env("FILE_UPLOAD_MAX_BYTES") + 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = env("FILE_UPLOAD_MAX_BYTES")
FILE_UPLOAD_MAX_BYTES = env("FILE_UPLOAD_MAX_BYTES")

LOGIN_FAILURE_LIMIT = env("LOGIN_FAILURE_LIMIT")
LOGIN_LOCK_MINUTES = env("LOGIN_LOCK_MINUTES")
TRUST_X_FORWARDED_FOR = env("TRUST_X_FORWARDED_FOR")
TRUSTED_PROXY_IPS = set(env.list("TRUSTED_PROXY_IPS", default=[]))
FRONTEND_URL = env("DJANGO_FRONTEND_URL", default="http://localhost:4200")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Carly Managed <noreply@localhost>")
EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend",
)
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT")
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS")
EMAIL_USE_SSL = env.bool("EMAIL_USE_SSL")
EMAIL_TIMEOUT = env.int("EMAIL_TIMEOUT")

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.accounts.authentication.CsrfEnforcedSessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.DefaultPagination",
    "PAGE_SIZE": 50,
    "EXCEPTION_HANDLER": "apps.common.exceptions.api_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_RATES": {
        "auth_login": "10/min",
        "auth_register": "5/hour",
        "auth_recovery": "5/hour",
        "auth_verify": "10/hour",
        "uploads": "30/hour",
        "search": "60/min",
    },
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Carly Managed API",
    "DESCRIPTION": "REST-API für Carly Managed mit Session-Authentifizierung und WebSockets.",
    "VERSION": "1.0.1",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "ENUM_NAME_OVERRIDES": {
        "ProjectStatusEnum": "apps.workspaces.choices.ProjectStatus.choices",
        "InvitationStatusEnum": "apps.workspaces.choices.InvitationStatus.choices",
        "JoinRequestStatusEnum": "apps.workspaces.choices.JoinRequestStatus.choices",
    },
    "SCHEMA_PATH_PREFIX": r"/api/v1",
}

REDIS_CHANNEL_URL = _redis_url(env.int("REDIS_CHANNEL_DB"), "REDIS_CHANNEL_URL")
REDIS_CACHE_URL = _redis_url(env.int("REDIS_CACHE_DB"), "REDIS_CACHE_URL")
REDIS_CELERY_URL = _redis_url(env.int("REDIS_CELERY_DB"), "REDIS_CELERY_URL")
REDIS_SOCKET_CONNECT_TIMEOUT = env.float("REDIS_SOCKET_CONNECT_TIMEOUT")
REDIS_SOCKET_TIMEOUT = env.float("REDIS_SOCKET_TIMEOUT")
REDIS_HEALTH_CHECK_INTERVAL = env.int("REDIS_HEALTH_CHECK_INTERVAL")
REDIS_RETRY_ON_TIMEOUT = env.bool("REDIS_RETRY_ON_TIMEOUT")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_CACHE_URL,
        "OPTIONS": {
            "socket_connect_timeout": REDIS_SOCKET_CONNECT_TIMEOUT,
            "socket_timeout": REDIS_SOCKET_TIMEOUT,
            "health_check_interval": REDIS_HEALTH_CHECK_INTERVAL,
            "retry_on_timeout": REDIS_RETRY_ON_TIMEOUT,
        },
        "TIMEOUT": 300,
    }
}
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_CHANNEL_URL], "capacity": 1500, "expiry": 60},
    }
}

CELERY_BROKER_URL = REDIS_CELERY_URL
CELERY_RESULT_BACKEND = REDIS_CELERY_URL
CELERY_BROKER_TRANSPORT_OPTIONS = {
    "socket_connect_timeout": REDIS_SOCKET_CONNECT_TIMEOUT,
    "socket_timeout": REDIS_SOCKET_TIMEOUT,
    "retry_on_timeout": REDIS_RETRY_ON_TIMEOUT,
}
CELERY_RESULT_BACKEND_TRANSPORT_OPTIONS = CELERY_BROKER_TRANSPORT_OPTIONS
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 300
CELERY_BEAT_SCHEDULE = {
    "run-due-recurrences": {
        "task": "apps.workspaces.tasks.run_due_recurrences",
        "schedule": crontab(minute="*/5"),
    },
    "expire-invitations": {
        "task": "apps.workspaces.tasks.expire_invitations",
        "schedule": crontab(minute=15, hour="*/2"),
    },
    "refresh-carly-streaks": {
        "task": "apps.preferences.tasks.refresh_carly_streaks",
        "schedule": crontab(minute=10, hour=0),
    },
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {name} request_id={request_id} {message}",
            "style": "{",
            "defaults": {"request_id": "-"},
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "apps": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
