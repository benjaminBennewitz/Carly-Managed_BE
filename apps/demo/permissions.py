# apps/demo/permissions.py
"""Begrenzt den Demo-Reset auf ausdrücklich freigegebene Umgebungen."""

from django.conf import settings
from rest_framework.permissions import BasePermission


def can_reset_demo_data(user) -> bool:
    """Erlaubt lokale Resets und produktiv ausschließlich das Demo-Konto."""
    if not user or not user.is_authenticated:
        return False
    if not settings.DEMO_DATA_RESET_ENABLED:
        return False
    if settings.DEBUG:
        return True
    return bool(
        settings.DEMO_DATA_RESET_ALLOW_PRODUCTION
        and settings.DEMO_OWNER_EMAIL
        and user.email.strip().lower() == settings.DEMO_OWNER_EMAIL
    )


class CanResetDemoData(BasePermission):
    """Erlaubt den Reset lokal frei und produktiv nur für das definierte Demo-Konto."""

    message = "Der Testdaten-Reset ist in dieser Umgebung nicht verfügbar."

    def has_permission(self, request, view) -> bool:
        """Prüft Feature-Flag, Umgebung und Demo-Konto."""
        return can_reset_demo_data(request.user)
