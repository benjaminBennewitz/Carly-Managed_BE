# apps/accounts/models.py
"""Definiert Benutzerkonten und kurzlebige Einmal-Tokens."""

import hashlib
from datetime import timedelta

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.validators import MaxLengthValidator, MinLengthValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from apps.accounts.managers import UserManager
from apps.common.models import TimeStampedModel, UUIDModel
from apps.common.validators import reject_control_characters


class User(UUIDModel, AbstractBaseUser, PermissionsMixin):
    """Verwendet E-Mail-Adressen als eindeutige Anmeldekennung."""

    email = models.EmailField(max_length=254, unique=True)
    display_name = models.CharField(
        max_length=60,
        validators=[MinLengthValidator(2), reject_control_characters],
    )
    avatar = models.ImageField(upload_to="avatars/%Y/%m/", blank=True, null=True)
    email_verified_at = models.DateTimeField(blank=True, null=True)
    privacy_acknowledged_at = models.DateTimeField()
    failed_login_count = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(blank=True, null=True)
    last_login_ip = models.GenericIPAddressField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["display_name"]

    class Meta:
        ordering = ("display_name", "email")
        constraints = [
            models.UniqueConstraint(Lower("email"), name="accounts_user_email_ci_unique"),
        ]
        indexes = [models.Index(Lower("email"), name="accounts_user_email_ci_idx")]

    def __str__(self) -> str:
        """Liefert eine kurze administrative Darstellung."""
        return f"{self.display_name} <{self.email}>"

    @property
    def email_verified(self) -> bool:
        """Zeigt an, ob die E-Mail-Adresse bestätigt wurde."""
        return self.email_verified_at is not None

    @property
    def is_login_locked(self) -> bool:
        """Prüft eine aktive zeitliche Anmeldesperre."""
        return bool(self.locked_until and self.locked_until > timezone.now())

    def clean(self) -> None:
        """Normalisiert persistierte Kontodaten vor der Validierung."""
        super().clean()
        self.email = self.__class__.objects.normalize_email(self.email).strip().lower()
        self.display_name = self.display_name.strip()


class AccountTokenPurpose(models.TextChoices):
    """Beschränkt Einmal-Tokens auf definierte Sicherheitsabläufe."""

    VERIFY_EMAIL = "verify_email", "E-Mail verifizieren"
    RESET_PASSWORD = "reset_password", "Passwort zurücksetzen"


class AccountToken(UUIDModel, TimeStampedModel):
    """Speichert ausschließlich den Hash eines kurzlebigen Einmal-Tokens."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="account_tokens")
    purpose = models.CharField(max_length=32, choices=AccountTokenPurpose.choices)
    token_hash = models.CharField(max_length=64, unique=True, validators=[MaxLengthValidator(64)])
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(blank=True, null=True)
    requested_ip = models.GenericIPAddressField(blank=True, null=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("purpose", "expires_at"), name="account_token_expiry_idx"),
            models.Index(fields=("user", "purpose"), name="account_token_user_idx"),
        ]

    def __str__(self) -> str:
        """Liefert eine Darstellung ohne das geheime Token."""
        return f"{self.user_id}: {self.purpose}"

    @staticmethod
    def hash_token(raw_token: str) -> str:
        """Bildet einen stabilen SHA-256-Hash für die Datenbanksuche."""
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    @classmethod
    def default_expiry(cls, purpose: str) -> timezone.datetime:
        """Berechnet eine zweckabhängige kurze Gültigkeit."""
        duration = timedelta(hours=24 if purpose == AccountTokenPurpose.VERIFY_EMAIL else 1)
        return timezone.now() + duration

    @property
    def is_usable(self) -> bool:
        """Prüft Ablauf und bisherige Verwendung."""
        return self.used_at is None and self.expires_at > timezone.now()
