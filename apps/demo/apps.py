# apps/demo/apps.py
"""Konfiguriert die ausschließlich kontrolliert nutzbaren Demo-Daten."""

from django.apps import AppConfig


class DemoConfig(AppConfig):
    """Registriert die Demo-Daten-Funktionen ohne automatische Seiteneffekte."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.demo"
    verbose_name = "Demo-Daten"
