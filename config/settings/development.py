# config/settings/development.py
"""Lokale Einstellungen mit bewusst abgeschwächten Transportvorgaben."""

from config.settings.base import *

DEBUG = True
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
