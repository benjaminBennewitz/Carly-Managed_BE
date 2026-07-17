# apps/accounts/apps.py
"""Registriert das Kontomodul bei Django."""

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """Konfiguriert das benutzerdefinierte Kontomodell."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    verbose_name = "Benutzerkonten"

    def ready(self) -> None:
        """Registriert OpenAPI-Erweiterungen beim Start der Anwendung."""
        from apps.accounts import schema  # noqa: F401
