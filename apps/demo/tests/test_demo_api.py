# apps/demo/tests/test_demo_api.py
"""Prüft Berechtigung, Reproduzierbarkeit und Isolation des Demo-Resets."""

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.workspaces.choices import BoardKind
from apps.workspaces.models import Board, Workspace


@override_settings(DEMO_DATA_RESET_ENABLED=True, DEMO_DATA_RESET_ALLOW_PRODUCTION=False, DEBUG=True)
class DemoResetApiTests(APITestCase):
    """Sichert den destruktiven Endpunkt gegen unberechtigte Aufrufe ab."""

    def setUp(self) -> None:
        """Erstellt Staff und regulären Nutzer mit sicheren Testpasswörtern."""
        self.staff = User.objects.create_user(
            email="staff@example.test",
            display_name="Staff Nutzer",
            password="Sicheres-Testpasswort-2026!",
            privacy_acknowledged_at=timezone.now(),
            is_staff=True,
        )
        self.member = User.objects.create_user(
            email="member@example.test",
            display_name="Mitglied",
            password="Noch-Ein-Testpasswort-2026!",
            privacy_acknowledged_at=timezone.now(),
        )

    def test_regular_user_can_reset_own_demo_data_in_debug(self) -> None:
        """Erlaubt lokalen Testkonten den Reset ihrer eigenen Demo-Daten."""
        self.client.force_authenticate(self.member)
        response = self.client.post(reverse("demo-reset"), format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            Workspace.objects.filter(owner=self.member, name="Carly Managed Demo").count(),
            1,
        )
        self.assertEqual(
            Board.objects.filter(owner=self.member, kind=BoardKind.PERSONAL).count(),
            1,
        )

    def test_staff_reset_is_reproducible_and_preserves_other_workspaces(self) -> None:
        """Ersetzt nur den benannten Demo-Workspace des aufrufenden Staff-Kontos."""
        untouched = Workspace.objects.create(name="Echter Workspace", owner=self.staff)
        self.client.force_authenticate(self.staff)

        first = self.client.post(reverse("demo-reset"), format="json")
        second = self.client.post(reverse("demo-reset"), format="json")

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(first.data["workspaceId"], second.data["workspaceId"])
        self.assertTrue(Workspace.objects.filter(pk=untouched.pk).exists())
        self.assertEqual(
            Workspace.objects.filter(owner=self.staff, name="Carly Managed Demo").count(), 1
        )
        self.assertGreaterEqual(second.data["projects"], 4)
        self.assertGreaterEqual(second.data["tasks"], 10)
        self.assertEqual(
            Board.objects.filter(owner=self.staff, kind=BoardKind.PERSONAL).count(),
            1,
        )

    def test_status_exposes_reset_to_authenticated_users_in_debug(self) -> None:
        """Zeigt den Reset lokal für reguläre und administrative Testkonten an."""
        self.client.force_authenticate(self.member)
        member_response = self.client.get(reverse("demo-status"))
        self.client.force_authenticate(self.staff)
        staff_response = self.client.get(reverse("demo-status"))

        self.assertTrue(member_response.data["canReset"])
        self.assertTrue(staff_response.data["canReset"])

    @override_settings(DEBUG=False, DEMO_DATA_RESET_ALLOW_PRODUCTION=False)
    def test_reset_stays_disabled_in_production_without_explicit_opt_in(self) -> None:
        """Verhindert den destruktiven Reset produktiv trotz Staff-Konto."""
        self.client.force_authenticate(self.staff)
        status_response = self.client.get(reverse("demo-status"))
        reset_response = self.client.post(reverse("demo-reset"), format="json")

        self.assertFalse(status_response.data["canReset"])
        self.assertEqual(reset_response.status_code, status.HTTP_403_FORBIDDEN)
