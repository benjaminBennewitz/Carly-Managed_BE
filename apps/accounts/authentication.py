# apps/accounts/authentication.py
"""Dokumentiert die bewusst CSRF-geschützte Session-Authentifizierung."""

from rest_framework.authentication import SessionAuthentication


class CsrfEnforcedSessionAuthentication(SessionAuthentication):
    """Verwendet Django-Sitzungen und erzwingt CSRF für unsichere Methoden."""

    pass
