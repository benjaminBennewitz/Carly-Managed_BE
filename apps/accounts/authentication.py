# apps/accounts/authentication.py
"""Dokumentiert und begrenzt die bewusst CSRF-geschützte Session-Authentifizierung."""

from django.conf import settings
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import AuthenticationFailed


class CsrfEnforcedSessionAuthentication(SessionAuthentication):
    """Verwendet Django-Sitzungen und erzwingt CSRF für unsichere Methoden.

    Im öffentlichen Demo-Modus dürfen ausschließlich Sitzungen des explizit
    konfigurierten Demo-Kontos verwendet werden. Dadurch bleiben eventuell noch
    vorhandene Sessions anderer lokaler oder administrativer Konten wirkungslos.
    """

    def authenticate(self, request):
        """Authentifiziert die Session und begrenzt Production auf das Demo-Konto."""
        authenticated = super().authenticate(request)
        if authenticated is None:
            return None

        user, auth = authenticated
        if settings.PUBLIC_DEMO_MODE and user.email.strip().lower() != settings.DEMO_OWNER_EMAIL:
            raise AuthenticationFailed(
                "Diese Sitzung ist in der öffentlichen Demo nicht freigegeben.",
                code="demo_account_required",
            )
        return user, auth
