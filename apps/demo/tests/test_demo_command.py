# apps/demo/tests/test_demo_command.py
"""Prüft die sichere Owner-Auswahl des Testdaten-Management-Commands."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import User
from apps.workspaces.models import Workspace


@override_settings(DEMO_DATA_RESET_ENABLED=True, DEMO_DATA_RESET_ALLOW_PRODUCTION=False, DEBUG=True)
class TestDemoResetCommand(TestCase):
    """Sichert explizite und eindeutige Staff-Zuordnungen ab."""

    def test_uses_only_active_staff_when_exactly_one_exists(self) -> None:
        """Nutzt ohne E-Mail ausschließlich ein eindeutig bestimmbares Staff-Konto."""
        owner = User.objects.create_user(
            email="owner@example.test",
            display_name="Demo Owner",
            password="Sicheres-Testpasswort-2026!",
            privacy_acknowledged_at=timezone.now(),
            is_staff=True,
        )
        output = StringIO()

        call_command("reset_demo_data", stdout=output)

        assert Workspace.objects.filter(owner=owner, name="Carly Managed Demo").exists()
        assert "Demo-Daten zurückgesetzt" in output.getvalue()

    def test_requires_email_when_multiple_staff_accounts_exist(self) -> None:
        """Verhindert eine zufällige Owner-Auswahl bei mehreren Staff-Konten."""
        for index in range(2):
            User.objects.create_user(
                email=f"staff-{index}@example.test",
                display_name=f"Staff {index}",
                password="Sicheres-Testpasswort-2026!",
                privacy_acknowledged_at=timezone.now(),
                is_staff=True,
            )

        with pytest.raises(CommandError, match="DEMO_OWNER_EMAIL"):
            call_command("reset_demo_data")

    @override_settings(DEMO_DATA_RESET_ENABLED=False)
    def test_refuses_reset_without_feature_flag(self) -> None:
        """Verhindert unbeabsichtigte Command-Ausführung ohne Freigabe."""
        with pytest.raises(CommandError, match="DEMO_DATA_RESET_ENABLED"):
            call_command("reset_demo_data")

    @override_settings(
        DEMO_OWNER_EMAIL="demo@carly-managed.de",
        DEMO_LOGIN_PASSWORD="Boards!Preview2026",
        DEMO_DISPLAY_NAME="Demo User",
        DEMO_DATA_RESET_ENABLED=True,
    )
    def test_provision_demo_user_creates_verified_non_staff_account(self) -> None:
        """Provisioniert den öffentlichen Zugang ohne Registrierungs- oder Adminrechte."""
        output = StringIO()

        call_command("provision_demo_user", stdout=output)

        user = User.objects.get(email="demo@carly-managed.de")
        assert user.check_password("Boards!Preview2026")
        assert user.email_verified_at is not None
        assert user.is_active
        assert not user.is_staff
        assert not user.is_superuser
        assert Workspace.objects.filter(owner=user, name="Carly Managed Demo").exists()
        assert "Demo-Konto angelegt" in output.getvalue()
