# apps/accounts/serializers.py
"""Validiert alle öffentlichen Konto- und Authentifizierungsdaten."""

import re
from typing import Any

from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.accounts.models import User
from apps.common.validators import reject_control_characters

DISPLAY_NAME_PATTERN = re.compile(
    r"^[\wÀ-ÖØ-öø-ÿĀ-ž .,'\N{RIGHT SINGLE QUOTATION MARK}\-]+$", re.UNICODE
)
INVALID_EMAIL_CHARACTERS = re.compile(r"[\x00-\x20\x7F<>{}\\]")


class CurrentUserSerializer(serializers.ModelSerializer[User]):
    """Gibt ausschließlich die für das Frontend notwendigen Kontodaten aus."""

    displayName = serializers.CharField(source="display_name")
    emailVerified = serializers.BooleanField(source="email_verified", read_only=True)
    avatarUrl = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "displayName", "email", "emailVerified", "avatarUrl")
        read_only_fields = ("id", "email", "emailVerified", "avatarUrl")

    def get_avatarUrl(self, obj: User) -> str | None:
        """Erzeugt bei vorhandenem Avatar eine absolute URL."""
        if not obj.avatar:
            return None
        request = self.context.get("request")
        return request.build_absolute_uri(obj.avatar.url) if request else obj.avatar.url

    def validate_displayName(self, value: str) -> str:
        """Normalisiert den Anzeigenamen und begrenzt dessen Zeichensatz."""
        normalized = " ".join(value.strip().split())
        reject_control_characters(normalized)
        if not DISPLAY_NAME_PATTERN.fullmatch(normalized):
            raise serializers.ValidationError(
                "Der Anzeigename enthält unzulässige Zeichen.",
                code="invalid_display_name_characters",
            )
        return normalized


class EmailFieldMixin:
    """Stellt eine gemeinsame, strenge E-Mail-Normalisierung bereit."""

    def validate_email(self, value: str) -> str:
        """Entfernt Randabstände und lehnt problematische Zeichen ab."""
        normalized = value.strip().lower()
        if INVALID_EMAIL_CHARACTERS.search(normalized):
            raise serializers.ValidationError(
                "Die E-Mail-Adresse enthält unzulässige Zeichen.",
                code="invalid_email_characters",
            )
        return normalized


class RegistrationSerializer(EmailFieldMixin, serializers.Serializer[dict[str, Any]]):
    """Validiert eine Registrierung unabhängig von Frontendprüfungen."""

    displayName = serializers.CharField(min_length=2, max_length=60, trim_whitespace=True)
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(
        min_length=12, max_length=128, write_only=True, trim_whitespace=False
    )
    privacyAcknowledged = serializers.BooleanField()

    def validate_displayName(self, value: str) -> str:
        """Prüft den für Namen vorgesehenen Zeichensatz."""
        normalized = " ".join(value.strip().split())
        reject_control_characters(normalized)
        if not DISPLAY_NAME_PATTERN.fullmatch(normalized):
            raise serializers.ValidationError(
                "Der Anzeigename enthält unzulässige Zeichen.",
                code="invalid_display_name_characters",
            )
        return normalized

    def validate_privacyAcknowledged(self, value: bool) -> bool:
        """Erfordert die ausdrücklich bestätigte Datenschutzerklärung."""
        if not value:
            raise serializers.ValidationError(
                "Die Datenschutzerklärung muss bestätigt werden.",
                code="privacy_required",
            )
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Führt die serverseitige Django-Passwortprüfung aus."""
        candidate = User(email=attrs["email"], display_name=attrs["displayName"])
        try:
            password_validation.validate_password(attrs["password"], candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)}) from exc
        return attrs


class LoginSerializer(EmailFieldMixin, serializers.Serializer[dict[str, Any]]):
    """Begrenzt die Größe sämtlicher Anmeldedaten."""

    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(max_length=128, write_only=True, trim_whitespace=False)
    rememberMe = serializers.BooleanField(default=False)


class PasswordChangeSerializer(serializers.Serializer[dict[str, Any]]):
    """Validiert einen authentifizierten Passwortwechsel."""

    currentPassword = serializers.CharField(max_length=128, write_only=True, trim_whitespace=False)
    newPassword = serializers.CharField(
        min_length=12, max_length=128, write_only=True, trim_whitespace=False
    )

    def validate_newPassword(self, value: str) -> str:
        """Prüft das neue Passwort gegen alle konfigurierten Regeln."""
        try:
            password_validation.validate_password(value, self.context["request"].user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value


class EmailOnlySerializer(EmailFieldMixin, serializers.Serializer[dict[str, Any]]):
    """Validiert eine einzelne E-Mail-Adresse für Wiederherstellungen."""

    email = serializers.EmailField(max_length=254)


class TokenSerializer(serializers.Serializer[dict[str, Any]]):
    """Begrenzt die Länge eines URL-sicheren Einmal-Tokens."""

    token = serializers.CharField(min_length=32, max_length=256, trim_whitespace=True)


class PasswordResetConfirmSerializer(TokenSerializer):
    """Kombiniert ein Einmal-Token mit einem neuen sicheren Passwort."""

    newPassword = serializers.CharField(
        min_length=12, max_length=128, write_only=True, trim_whitespace=False
    )

    def validate_newPassword(self, value: str) -> str:
        """Prüft das neue Passwort ohne personenbezogene Kontodetails zu verraten."""
        try:
            password_validation.validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value
