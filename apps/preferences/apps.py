# apps/preferences/apps.py
"""Registriert Einstellungen und Carly bei Django."""

from django.apps import AppConfig


class PreferencesConfig(AppConfig):
    """Konfiguriert persönliche Präferenzen und Motivation."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.preferences"
    verbose_name = "Einstellungen und Carly"
