# apps/common/apps.py
"""Registriert das Infrastrukturmodul bei Django."""

from django.apps import AppConfig


class CommonConfig(AppConfig):
    """Konfiguriert gemeinsam verwendete Basisklassen und Hilfsfunktionen."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.common"
    verbose_name = "Allgemeine Infrastruktur"
