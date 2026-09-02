# apps/demo/management/commands/reset_demo_data.py
"""Setzt den definierten Demo-Workspace für einen Staff-Nutzer zurück."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.demo.services import reset_demo_workspace


class Command(BaseCommand):
    """Erzeugt denselben atomaren Ausgangsstand wie der Einstellungsbutton."""

    help = "Setzt die Carly-Managed-Testdaten für einen Staff-Nutzer zurück."

    def add_arguments(self, parser) -> None:
        """Erlaubt eine explizite Owner-E-Mail für geplante Aufgaben."""
        parser.add_argument(
            "--owner-email",
            default=settings.DEMO_OWNER_EMAIL,
            help="E-Mail-Adresse des Staff-Nutzers, dem der Demo-Workspace gehört.",
        )

    def handle(self, *args, **options) -> None:
        """Prüft Umgebung und Konto und führt den gemeinsamen Reset-Service aus."""
        if not settings.DEMO_DATA_RESET_ENABLED:
            raise CommandError("DEMO_DATA_RESET_ENABLED muss ausdrücklich aktiviert sein.")
        if not settings.DEBUG and not settings.DEMO_DATA_RESET_ALLOW_PRODUCTION:
            raise CommandError("Der Demo-Reset ist in dieser Umgebung nicht freigegeben.")

        email = str(options["owner_email"] or "").strip().lower()
        eligible_users = User.objects.filter(is_active=True)
        if email:
            owner = eligible_users.filter(email__iexact=email).first()
            if owner is None:
                raise CommandError("Das angegebene aktive Demo-Konto wurde nicht gefunden.")
        else:
            staff_users = eligible_users.filter(is_staff=True)
            candidates = list(staff_users.order_by("date_joined")[:2])
            if len(candidates) != 1:
                raise CommandError(
                    "DEMO_OWNER_EMAIL oder --owner-email ist erforderlich, sobald nicht genau "
                    "ein aktives Staff-Konto existiert."
                )
            owner = candidates[0]
        result = reset_demo_workspace(owner=owner)
        self.stdout.write(
            self.style.SUCCESS(
                f"Demo-Daten zurückgesetzt: {result.workspace_name} · "
                f"{result.projects} Projekte · {result.tasks} Tasks · {result.members} Mitglieder"
            )
        )
