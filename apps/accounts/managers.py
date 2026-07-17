# apps/accounts/managers.py
"""Enthält den Manager für das E-Mail-basierte Benutzermodell."""

from typing import TYPE_CHECKING, Any

from django.contrib.auth.base_user import BaseUserManager
from django.utils import timezone

if TYPE_CHECKING:
    from apps.accounts.models import User


class UserManager(BaseUserManager["User"]):
    """Erzeugt normale und administrative Benutzer konsistent."""

    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra_fields: Any) -> "User":
        """Normalisiert die E-Mail-Adresse und speichert ein gehashtes Passwort."""
        if not email:
            raise ValueError("Eine E-Mail-Adresse ist erforderlich.")
        normalized_email = self.normalize_email(email).strip().lower()
        user = self.model(email=normalized_email, **extra_fields)
        user.set_password(password)
        user.full_clean(exclude={"password"})
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra_fields: Any) -> "User":
        """Erstellt ein reguläres Benutzerkonto."""
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(
        self,
        email: str,
        password: str | None = None,
        **extra_fields: Any,
    ) -> "User":
        """Erstellt ein administratives Konto mit allen Django-Rechten."""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("display_name", "Administration")
        extra_fields.setdefault("privacy_acknowledged_at", timezone.now())

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser benötigen is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser benötigen is_superuser=True.")

        return self._create_user(email, password, **extra_fields)
