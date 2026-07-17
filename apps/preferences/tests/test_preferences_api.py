# apps/preferences/tests/test_preferences_api.py
"""Prüft versionierte Einstellungen und Carly-Missbrauchsschutz."""

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.preferences.models import CarlyActionLog
from apps.workspaces.services import bootstrap_personal_workspace

pytestmark = pytest.mark.django_db


def create_user() -> User:
    """Erstellt einen Nutzer mit initialisierten Präferenzen."""
    user = User.objects.create_user(
        email="ben@example.test",
        password="Fokus!Board-2026-sicher",
        display_name="Ben Beispiel",
        privacy_acknowledged_at=timezone.now(),
    )
    bootstrap_personal_workspace(user)
    return user


def client_for(user: User) -> APIClient:
    """Liefert einen authentifizierten API-Client."""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def test_settings_update_requires_current_version() -> None:
    """Schützt parallele Einstellungsänderungen vor stillen Überschreibungen."""
    user = create_user()
    client = client_for(user)
    initial = client.get(reverse("settings"))
    assert initial.status_code == 200

    changed = client.patch(
        reverse("settings"),
        {
            "version": initial.data["version"],
            "accessibility": {"reduceMotion": True, "fontSize": "large"},
            "general": {"nickname": "Benny"},
        },
        format="json",
    )
    assert changed.status_code == 200
    assert changed.data["accessibility"]["reduceMotion"] is True
    assert changed.data["general"]["nickname"] == "Benny"

    stale = client.patch(
        reverse("settings"),
        {"version": initial.data["version"], "general": {"nickname": "Alt"}},
        format="json",
    )
    assert stale.status_code == 409


def test_carly_action_uses_version_and_cooldown() -> None:
    """Begrenzt wiederholte Fortschrittsaktionen vollständig serverseitig."""
    user = create_user()
    client = client_for(user)
    state = client.get(reverse("carly-state"))
    response = client.post(
        reverse("carly-action", args=["pet"]),
        {"version": state.data["version"]},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["progress"]["affection"] > state.data["progress"]["affection"]
    assert CarlyActionLog.objects.filter(user=user, action="pet").count() == 1

    throttled = client.post(
        reverse("carly-action", args=["pet"]),
        {"version": response.data["version"]},
        format="json",
    )
    assert throttled.status_code == 429


def test_unknown_carly_action_is_rejected() -> None:
    """Verhindert frei erfundene Aktionen und Fortschrittspunkte."""
    user = create_user()
    client = client_for(user)
    state = client.get(reverse("carly-state"))
    response = client.post(
        reverse("carly-action", args=["instant-level-up"]),
        {"version": state.data["version"]},
        format="json",
    )
    assert response.status_code == 400
    assert CarlyActionLog.objects.count() == 0
