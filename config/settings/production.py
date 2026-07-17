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

if (
    _is_placeholder(EMAIL_HOST)
    or "example.com" in EMAIL_HOST
    or _is_placeholder(EMAIL_HOST_PASSWORD)
):
    raise ImproperlyConfigured("SMTP-Host und SMTP-Passwort müssen produktiv gesetzt werden.")
