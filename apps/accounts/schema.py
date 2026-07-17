# apps/accounts/schema.py
"""Dokumentiert die Cookie-basierte Sitzungsauthentifizierung in OpenAPI."""

from django.conf import settings
from drf_spectacular.extensions import OpenApiAuthenticationExtension


class SessionCookieAuthenticationScheme(OpenApiAuthenticationExtension):
    """Beschreibt das sichere Django-Sitzungscookie für API-Clients."""

    target_class = "apps.accounts.authentication.CsrfEnforcedSessionAuthentication"
    name = "sessionCookie"
    priority = 1

    def get_security_definition(self, auto_schema: object) -> dict[str, str]:
        """Liefert die OpenAPI-Sicherheitsdefinition des Sitzungscookies."""
        return {
            "type": "apiKey",
            "in": "cookie",
            "name": settings.SESSION_COOKIE_NAME,
            "description": (
                "HttpOnly-Sitzungscookie. Schreibende Anfragen benötigen zusätzlich "
                "den X-CSRFToken-Header."
            ),
        }
