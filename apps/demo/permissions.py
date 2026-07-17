# apps/demo/permissions.py
"""Begrenzt den Demo-Reset auf lokale, autorisierte Administrationskonten."""

from django.conf import settings
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission


class CanResetDemoData(BasePermission):
    """Erlaubt den Reset nur für Staff und freigeschaltete Umgebungen."""

    message = "Der Testdaten-Reset ist in dieser Umgebung nicht verfügbar."

    def has_permission(self, request, view) -> bool:
        """Prüft Feature-Flag, Umgebung und administrative Berechtigung."""
        user = request.user
        if not user or not user.is_authenticated or not user.is_staff:
            return False
        if not settings.DEMO_DATA_RESET_ENABLED:
            return False
        if not settings.DEBUG and not settings.DEMO_DATA_RESET_ALLOW_PRODUCTION:
            raise PermissionDenied("Der Testdaten-Reset ist produktiv deaktiviert.")
        return True
