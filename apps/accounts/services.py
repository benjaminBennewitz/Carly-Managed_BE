# apps/accounts/services.py
"""Kapselt sicherheitskritische Kontooperationen in atomaren Diensten."""

import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.http import HttpRequest
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed, ErrorDetail, ValidationError

from apps.accounts.models import AccountToken, AccountTokenPurpose, User

logger = logging.getLogger(__name__)
GENERIC_LOGIN_ERROR = "E-Mail-Adresse oder Passwort sind nicht korrekt."
DUMMY_PASSWORD_HASH = make_password("carly-managed-dummy-password")


@dataclass(frozen=True, slots=True)
class IssuedToken:
    """Transportiert ein neu erzeugtes Klartext-Token nur im Arbeitsspeicher."""

    raw: str
    record: AccountToken


def get_client_ip(request: HttpRequest) -> str | None:
    """Liest hinter einem vertrauenswürdigen Reverse Proxy die Quelladresse."""
    remote_addr = request.META.get("REMOTE_ADDR")
    if not settings.TRUST_X_FORWARDED_FOR or remote_addr not in settings.TRUSTED_PROXY_IPS:
        return remote_addr
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return forwarded.split(",", maxsplit=1)[0].strip() or remote_addr


@transaction.atomic
def register_user(
    *,
    request: HttpRequest,
    display_name: str,
    email: str,
    password: str,
) -> User:
    """Erstellt Konto, Standard-Workspace und eine rotierte Sitzung."""
    try:
        user = User.objects.create_user(
            email=email,
            password=password,
            display_name=display_name,
            privacy_acknowledged_at=timezone.now(),
            last_login_ip=get_client_ip(request),
        )
    except (DjangoValidationError, IntegrityError) as exc:
        raise ValidationError(
            {
                "email": [
                    ErrorDetail(
                        "Die Registrierung konnte nicht abgeschlossen werden.",
                        code="registration_failed",
                    )
                ]
            }
        ) from exc

    from apps.workspaces.services import bootstrap_personal_workspace

    bootstrap_personal_workspace(user)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.session.set_expiry(0)
    return user


def authenticate_user(
    *,
    request: HttpRequest,
    email: str,
    password: str,
    remember_me: bool,
) -> User:
    """Authentifiziert ohne Kontoenumeration und pflegt eine zeitliche Sperre."""
    normalized_email = email.strip().lower()
    authenticated: User | None = None
    authentication_failed = False

    with transaction.atomic():
        user = User.objects.select_for_update().filter(email__iexact=normalized_email).first()

        if user and user.is_login_locked:
            authentication_failed = True
        else:
            candidate = authenticate(
                request=request,
                email=normalized_email,
                password=password,
            )
            if candidate is None or not candidate.is_active:
                authentication_failed = True
                if user:
                    user.failed_login_count += 1
                    if user.failed_login_count >= settings.LOGIN_FAILURE_LIMIT:
                        user.locked_until = timezone.now() + timedelta(
                            minutes=settings.LOGIN_LOCK_MINUTES
                        )
                        user.failed_login_count = 0
                    user.save(update_fields=("failed_login_count", "locked_until"))
                else:
                    check_password(password, DUMMY_PASSWORD_HASH)
            else:
                authenticated = candidate
                authenticated.failed_login_count = 0
                authenticated.locked_until = None
                authenticated.last_login_ip = get_client_ip(request)
                authenticated.save(
                    update_fields=(
                        "failed_login_count",
                        "locked_until",
                        "last_login_ip",
                    )
                )

    if authentication_failed or authenticated is None:
        raise AuthenticationFailed(
            GENERIC_LOGIN_ERROR,
            code="invalid_credentials",
        )

    login(request, authenticated)
    request.session.set_expiry(settings.SESSION_COOKIE_AGE if remember_me else 0)
    return authenticated


def end_session(request: HttpRequest) -> None:
    """Invalidiert die serverseitige Sitzung vollständig."""
    logout(request)


@transaction.atomic
def issue_account_token(*, user: User, purpose: str, request: HttpRequest) -> IssuedToken:
    """Widerruft ältere Tokens desselben Zwecks und erzeugt ein neues."""
    AccountToken.objects.filter(user=user, purpose=purpose, used_at__isnull=True).update(
        used_at=timezone.now()
    )
    raw = secrets.token_urlsafe(48)
    record = AccountToken.objects.create(
        user=user,
        purpose=purpose,
        token_hash=AccountToken.hash_token(raw),
        expires_at=AccountToken.default_expiry(purpose),
        requested_ip=get_client_ip(request),
    )
    return IssuedToken(raw=raw, record=record)


@transaction.atomic
def consume_account_token(*, raw_token: str, purpose: str) -> AccountToken:
    """Verbraucht ein gültiges Token genau einmal unter Datenbanksperre."""
    token_hash = AccountToken.hash_token(raw_token)
    token = (
        AccountToken.objects.select_for_update()
        .select_related("user")
        .filter(token_hash=token_hash, purpose=purpose)
        .first()
    )
    if token is None or not token.is_usable:
        raise ValidationError("Das Token ist ungültig oder abgelaufen.", code="invalid_token")
    token.used_at = timezone.now()
    token.save(update_fields=("used_at", "updated_at"))
    return token


def send_verification_email(*, user: User, request: HttpRequest) -> None:
    """Versendet einen neuen Link zur E-Mail-Bestätigung."""
    issued = issue_account_token(
        user=user, purpose=AccountTokenPurpose.VERIFY_EMAIL, request=request
    )
    url = f"{settings.FRONTEND_URL}/auth/verify-email?token={issued.raw}"
    send_mail(
        subject="E-Mail-Adresse für Carly Managed bestätigen",
        message=(
            "Bestätige deine E-Mail-Adresse über diesen Link:\n\n"
            f"{url}\n\nDer Link ist 24 Stunden gültig."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )


def request_password_reset(*, email: str, request: HttpRequest) -> None:
    """Versendet bei vorhandenem Konto eine nicht unterscheidbare Reset-Nachricht."""
    user = User.objects.filter(email__iexact=email, is_active=True).first()
    if not user:
        return
    issued = issue_account_token(
        user=user, purpose=AccountTokenPurpose.RESET_PASSWORD, request=request
    )
    url = f"{settings.FRONTEND_URL}/auth/reset-password?token={issued.raw}"
    send_mail(
        subject="Passwort für Carly Managed zurücksetzen",
        message=(
            "Setze dein Passwort über diesen Link zurück:\n\n"
            f"{url}\n\nDer Link ist eine Stunde gültig."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )
