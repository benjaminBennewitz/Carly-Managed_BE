# apps/workspaces/apps.py
"""Registriert das zentrale Workspace-Modul bei Django."""

from django.apps import AppConfig


class WorkspacesConfig(AppConfig):
    """Konfiguriert die kollaborative Projektdomäne."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.workspaces"
    verbose_name = "Workspaces und Aufgaben"
