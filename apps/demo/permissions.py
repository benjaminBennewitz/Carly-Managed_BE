# apps/demo/permissions.py
"""Begrenzt den Demo-Reset auf ausdrücklich freigegebene Umgebungen."""

from django.conf import settings
from rest_framework.permissions import BasePermission


def can_reset_demo_data(user) -> bool:
    """Erlaubt lokale Test-Resets und schützt produktive Umgebungen administrativ."""
    if not user or not user.is_authenticated:
        return False
    if not settings.DEMO_DATA_RESET_ENABLED:
        return False
    if settings.DEBUG:
        return True
    return bool(settings.DEMO_DATA_RESET_ALLOW_PRODUCTION and user.is_staff)


class CanResetDemoData(BasePermission):
    """Erlaubt den Reset lokal für Testkonten und produktiv nur für Staff."""

    message = "Der Testdaten-Reset ist in dieser Umgebung nicht verfügbar."

    def has_permission(self, request, view) -> bool:
        """Prüft Feature-Flag, Umgebung und erforderliche Berechtigung."""
        return can_reset_demo_data(request.user)
