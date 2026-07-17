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
