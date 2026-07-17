# apps/realtime/apps.py
"""Registriert den WebSocket-Layer bei Django."""

from django.apps import AppConfig


class RealtimeConfig(AppConfig):
    """Konfiguriert Presence, Cursor und Live-Aktivitäten."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.realtime"
    verbose_name = "Echtzeit-Zusammenarbeit"
