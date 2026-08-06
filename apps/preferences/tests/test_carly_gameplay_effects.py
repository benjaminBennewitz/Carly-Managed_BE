# apps/preferences/tests/test_carly_gameplay_effects.py
"""Prüft Carlys Food-Boni, Energieverbrauch und Schlafregeneration."""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.preferences.models import CarlyRewardLog, CarlyState
from apps.preferences.rewards import apply_carly_decay, award_carly_reward
from apps.preferences.services import perform_carly_action
from apps.workspaces.services import bootstrap_personal_workspace

pytestmark = pytest.mark.django_db


def create_user(suffix: str) -> User:
    """Erstellt einen Nutzer mit vollständig initialisiertem Carly-Zustand."""
    user = User.objects.create_user(
        email=f"carly-{suffix}@example.test",
        password="Fokus!Board-2026-sicher",
        display_name=f"Carly Test {suffix}",
        privacy_acknowledged_at=timezone.now(),
    )
    bootstrap_personal_workspace(user)
    return user


def test_sleep_restores_exactly_one_energy_per_full_hour() -> None:
    """Regeneriert im Schlaf nur volle Stunden und höchstens bis 100 Prozent."""
    user = create_user("sleep")
    carly = CarlyState.objects.get(user=user)
    now = timezone.now()
    carly.energy = 60
    carly.is_sleeping = True
    carly.last_energy_decay_at = now - timedelta(hours=3, minutes=59)
    carly.save()

    apply_carly_decay(carly, now=now)

    carly.refresh_from_db()
    assert carly.energy == 63


def test_moonfish_adds_three_xp_to_every_reward() -> None:
    """Addiert den Mondbonus nach Skalierung innerhalb des Hard-Caps."""
    user = create_user("moon")
    carly = CarlyState.objects.get(user=user)
    carly.moon_until = timezone.now() + timedelta(minutes=15)
    carly.save()

    reward = award_carly_reward(
        user=user,
        event_type="task_created",
        event_key="task-created:moon",
    )

    assert reward.xp == 6
    log = CarlyRewardLog.objects.get(user=user, event_key="task-created:moon")
    assert log.metadata["xpBonuses"] == [{"effect": "moon", "xp": 3}]


def test_expired_moonfish_does_not_add_xp() -> None:
    """Ignoriert einen bereits abgelaufenen Mondfisch-Bonus."""
    user = create_user("moon-expired")
    carly = CarlyState.objects.get(user=user)
    carly.moon_until = timezone.now() - timedelta(seconds=1)
    carly.save()

    reward = award_carly_reward(
        user=user,
        event_type="task_created",
        event_key="task-created:moon-expired",
    )

    assert reward.xp == 3


def test_mystic_focus_is_consumed_by_next_task_completion() -> None:
    """Verbraucht den Mystik-Fokus beim nächsten passenden Abschluss."""
    user = create_user("berry")
    carly = CarlyState.objects.get(user=user)
    carly.berry_focus_until = timezone.now() + timedelta(minutes=30)
    carly.berry_focus_charges = 1
    carly.save()

    reward = award_carly_reward(
        user=user,
        event_type="task_completed",
        event_key="task-completed:berry",
        xp=10,
        credits=0,
    )

    carly.refresh_from_db()
    assert reward.xp == 15
    assert carly.berry_focus_charges == 0
    assert carly.berry_focus_until is None


def test_mystic_focus_is_not_consumed_by_other_rewards() -> None:
    """Bewahrt den Mystik-Fokus bei nicht passenden Belohnungen."""
    user = create_user("berry-preserved")
    carly = CarlyState.objects.get(user=user)
    carly.berry_focus_until = timezone.now() + timedelta(minutes=30)
    carly.berry_focus_charges = 1
    carly.save()

    reward = award_carly_reward(
        user=user,
        event_type="task_created",
        event_key="task-created:berry-preserved",
    )

    carly.refresh_from_db()
    assert reward.xp == 3
    assert carly.berry_focus_charges == 1


def test_cookie_and_full_energy_stack_on_project_completion() -> None:
    """Kombiniert den spezialisierten Keksbonus mit dem Bonus voller Energie."""
    user = create_user("cookie")
    carly = CarlyState.objects.get(user=user)
    carly.energy = 100
    carly.cookie_until = timezone.now() + timedelta(hours=1)
    carly.save()

    reward = award_carly_reward(
        user=user,
        event_type="project_completed",
        event_key="project-completed:cookie",
        xp=20,
        credits=0,
    )

    assert reward.xp == 33
    log = CarlyRewardLog.objects.get(user=user, event_key="project-completed:cookie")
    assert log.metadata["xpBonuses"] == [
        {"effect": "cookie-stars", "xp": 10},
        {"effect": "full-energy", "xp": 3},
    ]


def test_bonus_xp_never_exceeds_daily_hard_cap() -> None:
    """Kürzt additive Food-Boni am täglichen XP-Hard-Cap."""
    user = create_user("hard-cap")
    carly = CarlyState.objects.get(user=user)
    carly.moon_until = timezone.now() + timedelta(minutes=15)
    carly.save()
    CarlyRewardLog.objects.create(
        user=user,
        event_type="seed",
        event_key="seed:hard-cap",
        xp=299,
        credits=0,
    )

    reward = award_carly_reward(
        user=user,
        event_type="task_created",
        event_key="task-created:hard-cap",
    )

    assert reward.xp == 1
    log = CarlyRewardLog.objects.get(user=user, event_key="task-created:hard-cap")
    assert "xpBonuses" not in log.metadata


def test_potion_fills_energy_and_playing_consumes_it() -> None:
    """Füllt Energie serverseitig auf und zieht beim Spielen acht Punkte ab."""
    user = create_user("potion")
    carly = CarlyState.objects.get(user=user)
    carly.energy = 12
    carly.inventory = {**carly.inventory, "potion": 1}
    carly.save()

    fed = perform_carly_action(
        user=user,
        action="feed",
        supplied_version=carly.version,
        food="potion",
    )

    assert fed.energy == 100
    assert fed.aura_until is not None

    played = perform_carly_action(
        user=user,
        action="play",
        supplied_version=fed.version,
    )

    assert played.energy == 92


def test_play_is_rejected_without_energy() -> None:
    """Verhindert Spielen, wenn Carly keine Energie mehr besitzt."""
    user = create_user("play-empty")
    carly = CarlyState.objects.get(user=user)
    carly.energy = 0
    carly.save()

    with pytest.raises(ValidationError, match="keine Energie"):
        perform_carly_action(
            user=user,
            action="play",
            supplied_version=carly.version,
        )
