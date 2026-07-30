# apps/preferences/tests/test_preferences_api.py
"""Prüft versionierte Einstellungen und Carly-Missbrauchsschutz."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.preferences.models import CarlyActionLog, CarlyRewardLog, CarlyState
from apps.preferences.rewards import award_carly_reward
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


def test_carly_decay_is_applied_when_state_is_read() -> None:
    """Baut Bedürfnisse anhand verstrichener Serverzeit ohne Hintergrundtimer ab."""
    user = create_user()
    carly = CarlyState.objects.get(user=user)
    carly.affection = 60
    carly.energy = 60
    carly.satiety = 60
    carly.last_affection_decay_at = timezone.now() - timedelta(hours=12, minutes=1)
    carly.last_energy_decay_at = timezone.now() - timedelta(hours=1, minutes=1)
    carly.last_satiety_decay_at = timezone.now() - timedelta(hours=1, minutes=31)
    carly.save()

    response = client_for(user).get(reverse("carly-state"))

    assert response.status_code == 200
    assert response.data["progress"]["affection"] == 58
    assert response.data["progress"]["energy"] == 58
    assert response.data["progress"]["satiety"] == 58


def test_food_purchase_and_feeding_use_server_inventory() -> None:
    """Kauft Futter mit Credits und verbraucht anschließend genau ein Inventarstück."""
    user = create_user()
    client = client_for(user)
    state = client.get(reverse("carly-state")).data

    bought = client.post(
        reverse("carly-action", args=["buy-food"]),
        {"version": state["version"], "food": "berry"},
        format="json",
    )
    assert bought.status_code == 200
    assert bought.data["progress"]["inventory"]["berry"] == 1
    assert bought.data["progress"]["credits"] == state["progress"]["credits"] - 35

    fed = client.post(
        reverse("carly-action", args=["feed"]),
        {"version": bought.data["version"], "food": "berry"},
        format="json",
    )
    assert fed.status_code == 200
    assert fed.data["progress"]["inventory"]["berry"] == 0
    assert fed.data["effect"] == "berry-dizzy"
    assert fed.data["reward"]["xp"] > 0


def test_reward_rules_and_history_are_server_authoritative() -> None:
    """Veröffentlicht dieselben Regeln, aus denen das Reward-Ledger gespeist wird."""
    user = create_user()
    client = client_for(user)
    state = client.get(reverse("carly-state")).data
    response = client.post(
        reverse("carly-action", args=["pet"]),
        {"version": state["version"]},
        format="json",
    )
    assert response.status_code == 200
    assert CarlyRewardLog.objects.filter(user=user, event_type="pet").count() == 1

    rules = client.get(reverse("carly-reward-rules"))
    history = client.get(reverse("carly-reward-history"))
    assert rules.status_code == 200
    assert rules.data["dailyCaps"]["xpHard"] == 300
    assert any(item["eventType"] == "pet" for item in rules.data["rewards"])
    assert history.status_code == 200
    assert history.data["items"][0]["eventType"] == "pet"


def test_reward_ledger_is_idempotent_and_scales_repetitions() -> None:
    """Vergibt dasselbe Ereignis nur einmal und reduziert wiederholte Events bis auf Minimal-XP."""
    user = create_user()

    first = award_carly_reward(
        user=user,
        event_type="task_created",
        event_key="task-created:fixed",
        source_type="task",
        source_id="fixed",
    )
    duplicate = award_carly_reward(
        user=user,
        event_type="task_created",
        event_key="task-created:fixed",
        source_type="task",
        source_id="fixed",
    )

    assert first.xp == 3
    assert duplicate.duplicate is True
    assert duplicate.xp == 0
    assert CarlyRewardLog.objects.filter(user=user, event_key="task-created:fixed").count() == 1

    last = first
    for index in range(1, 22):
        last = award_carly_reward(
            user=user,
            event_type="task_created",
            event_key=f"task-created:repeat-{index}",
            source_type="task",
            source_id=f"repeat-{index}",
        )

    assert last.xp == 1
    assert last.credits == 1


def test_carly_settings_reset_preserves_economy() -> None:
    """Verhindert, dass ein Einstellungsreset Credits oder Inventar neu erzeugt."""
    user = create_user()
    carly = CarlyState.objects.get(user=user)
    carly.credits = 123
    carly.experience = 87
    carly.inventory = {"fish": 2, "berry": 1, "cookie": 3, "potion": 0}
    carly.show_globally = False
    carly.save()

    response = client_for(user).delete(reverse("carly-state"))

    assert response.status_code == 200
    assert response.data["settings"]["showGlobally"] is True
    assert response.data["progress"]["credits"] == 123
    assert response.data["progress"]["experience"] == 87
    assert response.data["progress"]["inventory"]["cookie"] == 3
