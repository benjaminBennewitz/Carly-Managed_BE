# apps/inbox/apps.py
"""Registriert die Inbox-Domäne bei Django."""

from django.apps import AppConfig


class InboxConfig(AppConfig):
    """Konfiguriert Benachrichtigungen und Gespräche."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.inbox"
    verbose_name = "Inbox und Nachrichten"
