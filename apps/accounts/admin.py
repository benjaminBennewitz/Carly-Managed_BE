# apps/accounts/admin.py
"""Konfiguriert eine sichere Administration der Benutzerkonten."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from apps.accounts.models import AccountToken, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Zeigt Kontostatus, Verifizierung und Sperren ohne Passwörter an."""

    ordering = ("email",)
    list_display = ("email", "display_name", "email_verified", "is_active", "is_staff")
    search_fields = ("email", "display_name")
    readonly_fields = ("date_joined", "last_login", "email_verified_at")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profil", {"fields": ("display_name", "avatar", "email_verified_at")}),
        ("Sicherheit", {"fields": ("failed_login_count", "locked_until", "last_login_ip")}),
        (
            "Berechtigungen",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Zeitpunkte", {"fields": ("date_joined", "last_login", "privacy_acknowledged_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "display_name",
                    "password1",
                    "password2",
                    "is_staff",
                    "is_active",
                ),
            },
        ),
    )


@admin.register(AccountToken)
class AccountTokenAdmin(admin.ModelAdmin):
    """Erlaubt nur die Prüfung von Metadaten, nicht geheimer Klartext-Tokens."""

    list_display = ("user", "purpose", "expires_at", "used_at", "created_at")
    list_filter = ("purpose", "used_at")
    search_fields = ("user__email",)
    readonly_fields = ("token_hash", "created_at", "updated_at")
