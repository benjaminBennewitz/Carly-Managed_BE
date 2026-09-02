# config/settings/production.py
"""Produktive Einstellungen mit zwingender Sicherheitskonfiguration."""

from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

from config.settings.base import *

DEBUG = False


def _is_placeholder(value: str) -> bool:
    """Erkennt absichtlich unbrauchbare Beispiel- und Platzhalterwerte."""
    normalized = value.strip().lower()
    return not normalized or normalized.startswith(("change_me", "change-me", "django-insecure"))


if _is_placeholder(SECRET_KEY) or len(SECRET_KEY) < 50:
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY muss produktiv zufällig sein und mindestens 50 Zeichen besitzen."
    )

if not ALLOWED_HOSTS or any("example.com" in host for host in ALLOWED_HOSTS):
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS muss produktive Hosts enthalten.")

if not CSRF_TRUSTED_ORIGINS or not all(
    origin.startswith("https://") for origin in CSRF_TRUSTED_ORIGINS
):
    raise ImproperlyConfigured(
        "DJANGO_CSRF_TRUSTED_ORIGINS muss mindestens eine HTTPS-Origin enthalten."
    )

if not CORS_ALLOWED_ORIGINS or not all(
    origin.startswith("https://") for origin in CORS_ALLOWED_ORIGINS
):
    raise ImproperlyConfigured(
        "DJANGO_CORS_ALLOWED_ORIGINS muss mindestens eine HTTPS-Origin enthalten."
    )

if not FRONTEND_URL.startswith("https://") or "example.com" in FRONTEND_URL:
    raise ImproperlyConfigured("DJANGO_FRONTEND_URL muss auf die produktive HTTPS-App zeigen.")

if not FRONTEND_URLS or not all(
    url.startswith("https://") and "example.com" not in url for url in FRONTEND_URLS
):
    raise ImproperlyConfigured(
        "DJANGO_FRONTEND_URLS muss ausschließlich produktive HTTPS-Origins enthalten."
    )

frontend_hosts = {urlsplit(url).hostname for url in FRONTEND_URLS}
missing_email_hosts = sorted(
    host for host in frontend_hosts if host and host not in EMAIL_FROM_BY_HOST
)
if missing_email_hosts:
    raise ImproperlyConfigured(
        "DJANGO_EMAIL_FROM_BY_HOST fehlt für: " + ", ".join(missing_email_hosts)
    )

if not all((SESSION_COOKIE_SECURE, CSRF_COOKIE_SECURE, SECURE_SSL_REDIRECT)):
    raise ImproperlyConfigured(
        "Secure Cookies und SECURE_SSL_REDIRECT müssen produktiv aktiviert sein."
    )

if _is_placeholder(DATABASES["default"].get("PASSWORD", "")):
    raise ImproperlyConfigured("DB_PASSWORD muss produktiv ersetzt werden.")

redis_password = urlsplit(REDIS_CHANNEL_URL).password or ""
if _is_placeholder(redis_password):
    raise ImproperlyConfigured("REDIS_PASSWORD muss produktiv ersetzt werden.")

if EMAIL_BACKEND == "django.core.mail.backends.console.EmailBackend":
    raise ImproperlyConfigured("Produktiv muss ein versendendes E-Mail-Backend verwendet werden.")

if EMAIL_USE_TLS and EMAIL_USE_SSL:
    raise ImproperlyConfigured(
        "EMAIL_USE_TLS und EMAIL_USE_SSL dürfen nicht gleichzeitig aktiv sein."
    )

if _is_placeholder(EMAIL_HOST) or "example.com" in EMAIL_HOST:
    raise ImproperlyConfigured("EMAIL_HOST muss produktiv gesetzt werden.")

local_smtp_hosts = {"127.0.0.1", "localhost", "::1"}
if EMAIL_HOST not in local_smtp_hosts and _is_placeholder(EMAIL_HOST_PASSWORD):
    raise ImproperlyConfigured(
        "Für einen entfernten SMTP-Host muss EMAIL_HOST_PASSWORD gesetzt werden."
    )

if PUBLIC_DEMO_MODE:
    if not DEMO_OWNER_EMAIL or "@" not in DEMO_OWNER_EMAIL:
        raise ImproperlyConfigured(
            "DEMO_OWNER_EMAIL muss für den produktiven Demo-Modus gesetzt sein."
        )
    if not DEMO_LOGIN_PASSWORD or len(DEMO_LOGIN_PASSWORD) < 12:
        raise ImproperlyConfigured(
            "DEMO_LOGIN_PASSWORD muss für den produktiven Demo-Modus mindestens 12 Zeichen haben."
        )
