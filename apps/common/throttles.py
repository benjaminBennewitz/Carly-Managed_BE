# apps/common/throttles.py
"""Enthält klar benannte Drosselklassen für sensible Endpunkte."""

from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


class LoginRateThrottle(AnonRateThrottle):
    """Begrenzt automatisierte Anmeldeversuche je Quelladresse."""

    scope = "auth_login"


class RegistrationRateThrottle(AnonRateThrottle):
    """Begrenzt massenhaft erzeugte Konten je Quelladresse."""

    scope = "auth_register"


class RecoveryRateThrottle(AnonRateThrottle):
    """Begrenzt E-Mail-basierte Wiederherstellungsaktionen."""

    scope = "auth_recovery"


class VerificationRateThrottle(UserRateThrottle):
    """Begrenzt erneut angeforderte Verifizierungsnachrichten."""

    scope = "auth_verify"


class UploadRateThrottle(UserRateThrottle):
    """Begrenzt Datei-Uploads je angemeldetem Nutzer."""

    scope = "uploads"


class SearchRateThrottle(UserRateThrottle):
    """Schützt die globale Suche vor unnötiger Last."""

    scope = "search"
