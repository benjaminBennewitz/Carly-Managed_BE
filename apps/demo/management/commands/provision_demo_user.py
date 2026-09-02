# apps/demo/management/commands/provision_demo_user.py
"""Legt das öffentliche Demo-Konto reproduzierbar an oder aktualisiert es."""

from django.conf import settings
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import User
from apps.demo.services import reset_public_demo_account


class Command(BaseCommand):
    """Provisioniert das definierte Demo-Konto ohne öffentlichen Registrierungsflow."""

    help = "Legt den Carly-Managed-Demo-User an/aktualisiert ihn und erzeugt Demo-Daten."

    def add_arguments(self, parser) -> None:
        """Erlaubt bei Bedarf explizite Zugangsdaten für einen einzelnen Lauf."""
        parser.add_argument("--email", default=settings.DEMO_OWNER_EMAIL)
        parser.add_argument("--password", default=settings.DEMO_LOGIN_PASSWORD)
        parser.add_argument("--display-name", default=settings.DEMO_DISPLAY_NAME)
        parser.add_argument(
            "--skip-data-reset",
            action="store_true",
            help="Aktualisiert nur das Konto und lässt vorhandene Demo-Daten unverändert.",
        )

    def handle(self, *args, **options) -> None:
        """Erstellt einen normalen, verifizierten Nutzer und setzt seinen Demo-Workspace."""
        email = str(options["email"] or "").strip().lower()
        password = str(options["password"] or "")
        display_name = str(options["display_name"] or "Demo User").strip() or "Demo User"

        if not email or "@" not in email:
            raise CommandError("Eine gültige Demo-E-Mail-Adresse ist erforderlich.")
        if not password:
            raise CommandError("Ein Demo-Passwort ist erforderlich.")

        preview_user = User(email=email, display_name=display_name)
        try:
            password_validation.validate_password(password, preview_user)
        except DjangoValidationError as exc:
            messages = getattr(exc, "messages", [str(exc)])
            raise CommandError("Demo-Passwort ungültig: " + " ".join(messages)) from exc

        now = timezone.now()
        user = User.objects.filter(email__iexact=email).first()
        created = user is None
        if user is None:
            user = User(
                email=email,
                display_name=display_name,
                privacy_acknowledged_at=now,
                email_verified_at=now,
                is_active=True,
                is_staff=False,
                is_superuser=False,
            )
        else:
            user.email = email
            user.display_name = display_name
            user.privacy_acknowledged_at = user.privacy_acknowledged_at or now
            user.email_verified_at = user.email_verified_at or now
            user.is_active = True
            user.is_staff = False
            user.is_superuser = False
            user.failed_login_count = 0
            user.locked_until = None

        user.set_password(password)
        user.full_clean(exclude={"password"})
        user.save()

        if not options["skip_data_reset"]:
            reset_public_demo_account(owner=user)

        action = "angelegt" if created else "aktualisiert"
        self.stdout.write(self.style.SUCCESS(f"Demo-Konto {action}: {email}"))
