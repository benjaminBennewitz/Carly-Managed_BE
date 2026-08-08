# apps/accounts/tests/test_auth_api.py
"""Prüft Registrierung, CSRF, Anmeldung und Wiederherstellung."""

import re
from datetime import timedelta

import pytest
from django.core import mail
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import AccountToken, AccountTokenPurpose, User
from apps.accounts.services import get_client_ip
from apps.preferences.models import CarlyState, UserSettings
from apps.workspaces.models import Board, Workspace, WorkspaceMembership

pytestmark = pytest.mark.django_db

STRONG_PASSWORD = "Fokus!Board-2026-sicher"


def csrf_client() -> tuple[APIClient, str]:
    """Erzeugt einen Client mit aktivierter CSRF-Prüfung und gültigem Token."""
    client = APIClient(enforce_csrf_checks=True)
    response = client.get(reverse("csrf"))
    assert response.status_code == 200
    return client, response.data["csrfToken"]


def register(client: APIClient, token: str, email: str = "ben@example.test"):
    """Führt eine gültige Registrierung für mehrere Tests aus."""
    return client.post(
        reverse("register"),
        {
            "displayName": "Ben Beispiel",
            "email": email,
            "password": STRONG_PASSWORD,
            "privacyAcknowledged": True,
        },
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )


def test_public_auth_posts_require_csrf() -> None:
    """Verhindert Login- und Registrierungs-CSRF bei öffentlichen Endpunkten."""
    client = APIClient(enforce_csrf_checks=True)
    response = client.post(
        reverse("register"),
        {
            "displayName": "Ben Beispiel",
            "email": "ben@example.test",
            "password": STRONG_PASSWORD,
            "privacyAcknowledged": True,
        },
        format="json",
    )
    assert response.status_code == 403
    assert User.objects.count() == 0


def test_registration_bootstraps_complete_personal_context() -> None:
    """Erstellt Konto, Sitzung, Workspace, Board, Präferenzen und genau ein Token."""
    client, token = csrf_client()
    response = register(client, token)

    assert response.status_code == 201
    assert response.data["user"]["email"] == "ben@example.test"
    user = User.objects.get(email="ben@example.test")
    assert client.session.get("_auth_user_id") == str(user.id)
    assert Workspace.objects.filter(owner=user).count() == 1
    assert WorkspaceMembership.objects.filter(user=user, role="owner", is_active=True).exists()
    board = Board.objects.get(owner=user)
    assert list(board.columns.order_by("position").values_list("title", flat=True)) == [
        "Neu",
        "Offen",
        "In Arbeit",
        "Erledigt",
    ]
    assert UserSettings.objects.filter(user=user).exists()
    assert CarlyState.objects.filter(user=user).exists()
    assert (
        AccountToken.objects.filter(user=user, purpose=AccountTokenPurpose.VERIFY_EMAIL).count()
        == 1
    )
    assert len(mail.outbox) == 1
    assert "/auth/verify-email#token=" in mail.outbox[0].body
    assert "/auth/verify-email?token=" not in mail.outbox[0].body


def test_registration_rejects_missing_privacy_acknowledgement() -> None:
    """Vertraut bei der Datenschutzzustimmung nicht auf das Frontend."""
    client, token = csrf_client()
    response = client.post(
        reverse("register"),
        {
            "displayName": "Ben Beispiel",
            "email": "ben@example.test",
            "password": STRONG_PASSWORD,
            "privacyAcknowledged": False,
        },
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert response.status_code == 400
    assert response.data["code"] == "validation_error"
    assert "privacyAcknowledged" in response.data["fields"]


def test_registration_rejects_weak_password() -> None:
    """Validiert Passwörter vollständig und unabhängig vom Frontend."""
    client, token = csrf_client()
    response = client.post(
        reverse("register"),
        {
            "displayName": "Ben Beispiel",
            "email": "ben@example.test",
            "password": "123456789012",
            "privacyAcknowledged": True,
        },
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert response.status_code == 400
    assert response.data["code"] == "validation_error"
    assert "password" in response.data["fields"]


def test_duplicate_registration_returns_clear_email_error() -> None:
    """Kennzeichnet eine bereits verwendete E-Mail-Adresse verständlich am Feld."""
    client, token = csrf_client()
    assert register(client, token).status_code == 201
    client.logout()
    client.get(reverse("csrf"))
    duplicate = register(client, client.cookies["cm_csrftoken"].value)
    assert duplicate.status_code == 400
    assert duplicate.data["fields"]["email"][0]["code"] == "email_in_use"
    assert duplicate.data["fields"]["email"][0]["message"] == (
        "Diese E-Mail-Adresse wird bereits verwendet."
    )


def test_login_uses_generic_error_and_locks_repeated_failures() -> None:
    """Begrenzt Passwortversuche ohne unterschiedliche Kontoantworten."""
    user = User.objects.create_user(
        email="ben@example.test",
        password=STRONG_PASSWORD,
        display_name="Ben Beispiel",
        privacy_acknowledged_at=timezone.now(),
    )
    client, token = csrf_client()

    with override_settings(LOGIN_FAILURE_LIMIT=3, LOGIN_LOCK_MINUTES=10):
        for _ in range(3):
            response = client.post(
                reverse("login"),
                {"email": user.email, "password": "falsch", "rememberMe": False},
                format="json",
                HTTP_X_CSRFTOKEN=token,
            )
            assert response.status_code == 403
            assert response.data["message"] == "E-Mail-Adresse oder Passwort sind nicht korrekt."

    user.refresh_from_db()
    assert user.locked_until is not None
    assert user.locked_until > timezone.now()
    blocked = client.post(
        reverse("login"),
        {"email": user.email, "password": STRONG_PASSWORD, "rememberMe": False},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert blocked.status_code == 403


def test_password_reset_is_non_enumerating_and_token_is_single_use() -> None:
    """Antwortet identisch und verbraucht Reset-Tokens atomar genau einmal."""
    user = User.objects.create_user(
        email="ben@example.test",
        password=STRONG_PASSWORD,
        display_name="Ben Beispiel",
        privacy_acknowledged_at=timezone.now(),
    )
    client, token = csrf_client()
    unknown = client.post(
        reverse("password-reset-request"),
        {"email": "unknown@example.test"},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )
    known = client.post(
        reverse("password-reset-request"),
        {"email": user.email},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert unknown.status_code == known.status_code == 200
    assert unknown.data == known.data
    assert "/auth/reset-password#token=" in mail.outbox[-1].body
    assert "/auth/reset-password?token=" not in mail.outbox[-1].body

    raw_token = re.search(r"token=([^\s]+)", mail.outbox[-1].body).group(1)
    new_password = "Neu!Und-Sicher-2026-Backend"
    confirmed = client.post(
        reverse("password-reset-confirm"),
        {"token": raw_token, "newPassword": new_password},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert confirmed.status_code == 204
    user.refresh_from_db()
    assert user.check_password(new_password)

    replay = client.post(
        reverse("password-reset-confirm"),
        {"token": raw_token, "newPassword": "Noch!Ein-Neues-2026-Passwort"},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert replay.status_code == 400


def test_expired_verification_token_is_rejected() -> None:
    """Akzeptiert keine abgelaufenen Bestätigungstokens."""
    user = User.objects.create_user(
        email="ben@example.test",
        password=STRONG_PASSWORD,
        display_name="Ben Beispiel",
        privacy_acknowledged_at=timezone.now(),
    )
    raw = "a" * 64
    AccountToken.objects.create(
        user=user,
        purpose=AccountTokenPurpose.VERIFY_EMAIL,
        token_hash=AccountToken.hash_token(raw),
        expires_at=timezone.now() - timedelta(seconds=1),
    )
    client, csrf = csrf_client()
    response = client.post(
        reverse("email-verify-confirm"),
        {"token": raw},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert response.status_code == 400
    user.refresh_from_db()
    assert user.email_verified_at is None


def test_forwarded_ip_is_only_trusted_from_configured_proxy(rf) -> None:
    """Verhindert frei gefälschte X-Forwarded-For-Adressen."""
    request = rf.get(
        "/",
        REMOTE_ADDR="203.0.113.10",
        HTTP_X_FORWARDED_FOR="198.51.100.77, 203.0.113.10",
    )
    with override_settings(TRUST_X_FORWARDED_FOR=False, TRUSTED_PROXY_IPS=set()):
        assert get_client_ip(request) == "203.0.113.10"
    with override_settings(
        TRUST_X_FORWARDED_FOR=True,
        TRUSTED_PROXY_IPS={"203.0.113.10"},
    ):
        assert get_client_ip(request) == "198.51.100.77"


def test_password_change_rejects_same_password_and_revokes_open_reset_tokens() -> None:
    """Verhindert Passwort-Reuse und widerruft offene Wiederherstellungslinks."""
    user = User.objects.create_user(
        email="change@example.test",
        password=STRONG_PASSWORD,
        display_name="Passwort Test",
        privacy_acknowledged_at=timezone.now(),
    )
    pending = AccountToken.objects.create(
        user=user,
        purpose=AccountTokenPurpose.RESET_PASSWORD,
        token_hash=AccountToken.hash_token("offener-reset-link"),
        expires_at=timezone.now() + timedelta(hours=1),
    )
    client = APIClient()
    client.force_authenticate(user=user)

    unchanged = client.post(
        reverse("password-change"),
        {"currentPassword": STRONG_PASSWORD, "newPassword": STRONG_PASSWORD},
        format="json",
    )
    assert unchanged.status_code == 400
    pending.refresh_from_db()
    assert pending.used_at is None

    new_password = "Ganz!Neu-und-sicher-2026"
    changed = client.post(
        reverse("password-change"),
        {"currentPassword": STRONG_PASSWORD, "newPassword": new_password},
        format="json",
    )
    assert changed.status_code == 204
    user.refresh_from_db()
    pending.refresh_from_db()
    assert user.check_password(new_password)
    assert pending.used_at is not None
