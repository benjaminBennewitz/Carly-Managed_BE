# apps/preferences/rewards.py
"""Berechnet Carly-Bedürfnisse, Economy und missbrauchsbegrenzte Belohnungen."""

import logging
from dataclasses import asdict, dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.preferences.models import CarlyMood, CarlyRewardLog, CarlyState

logger = logging.getLogger(__name__)

DAILY_XP_SOFT_CAP = 200
DAILY_XP_HARD_CAP = 300
DAILY_CREDIT_SOFT_CAP = 500
DAILY_CREDIT_HARD_CAP = 650
MOON_XP_BONUS = 3
BERRY_FOCUS_XP_BONUS = 5
COOKIE_PROJECT_XP_BONUS = 10
FULL_ENERGY_XP_BONUS = 3
COMPLETION_EVENTS = frozenset({"task_completed", "subtask_completed", "project_completed"})
BERRY_FOCUS_EVENTS = frozenset({"task_completed", "subtask_completed"})

FOOD_RULES: dict[str, dict[str, Any]] = {
    "fish": {
        "label": "Mondfisch",
        "cost": 20,
        "satiety": 25,
        "affection": 1,
        "energy": 0,
        "effect": "moon",
        "bonusDurationSeconds": 15 * 60,
        "visualDurationSeconds": 2,
    },
    "berry": {
        "label": "Mystikbeeren",
        "cost": 35,
        "satiety": 18,
        "affection": 3,
        "energy": 0,
        "effect": "berry-dizzy",
        "bonusDurationSeconds": 30 * 60,
        "visualDurationSeconds": 6,
    },
    "cookie": {
        "label": "Sternenkeks",
        "cost": 60,
        "satiety": 12,
        "affection": 7,
        "energy": 1,
        "effect": "cookie-stars",
        "bonusDurationSeconds": 60 * 60,
        "visualDurationSeconds": 6,
    },
    "potion": {
        "label": "Energietrank",
        "cost": 100,
        "satiety": 4,
        "affection": 1,
        "energy": 0,
        "effect": "energy-aura",
        "visualDurationSeconds": 3,
    },
}

REWARD_RULES: dict[str, dict[str, Any]] = {
    "task_created": {"label": "Task erstellen", "xp": 3, "credits": 8, "fullUntil": 5},
    "task_completed": {
        "label": "Task abschließen",
        "xp": 15,
        "credits": 40,
        "fullUntil": 5,
        "subtaskXp": 2,
        "subtaskCredits": 4,
        "subtaskLimit": 5,
        "collaboratorXp": 2,
        "collaboratorCredits": 5,
        "collaboratorLimit": 3,
    },
    "subtask_completed": {
        "label": "Unteraufgabe abschließen",
        "xp": 2,
        "credits": 4,
        "fullUntil": 10,
    },
    "task_updated": {"label": "Task sinnvoll bearbeiten", "xp": 1, "credits": 2, "fullUntil": 10},
    "task_moved": {"label": "Task im Workflow verschieben", "xp": 1, "credits": 2, "fullUntil": 10},
    "project_created": {"label": "Projekt erstellen", "xp": 8, "credits": 25, "fullUntil": 3},
    "project_updated": {"label": "Projekt bearbeiten", "xp": 2, "credits": 5, "fullUntil": 8},
    "project_completed": {
        "label": "Projekt abschließen",
        "xp": 50,
        "credits": 150,
        "fullUntil": 2,
    },
    "comment_created": {"label": "Kommentar schreiben", "xp": 2, "credits": 4, "fullUntil": 10},
    "mention_created": {"label": "Person erwähnen", "xp": 2, "credits": 5, "fullUntil": 8},
    "message_sent": {"label": "Nachricht senden", "xp": 1, "credits": 2, "fullUntil": 5},
    "pet": {"label": "Carly streicheln", "xp": 5, "credits": 0, "fullUntil": 3},
    "play": {"label": "Mit Carly spielen", "xp": 8, "credits": 0, "fullUntil": 3},
    "feed": {"label": "Carly füttern", "xp": 2, "credits": 0, "fullUntil": 4},
}

PRODUCTIVE_EVENTS = {
    "task_created",
    "task_completed",
    "subtask_completed",
    "task_updated",
    "task_moved",
    "project_created",
    "project_updated",
    "project_completed",
    "comment_created",
    "mention_created",
    "message_sent",
}


@dataclass(frozen=True)
class CarlyRewardResult:
    """Beschreibt eine tatsächlich gutgeschriebene Belohnung."""

    id: str | None
    event_type: str
    xp: int
    credits: int
    multiplier: float
    created_at: str
    duplicate: bool = False

    def as_api_dict(self) -> dict[str, Any]:
        """Liefert camelCase-freundliche API-Daten."""
        data = asdict(self)
        return {
            "id": data["id"],
            "eventType": data["event_type"],
            "xp": data["xp"],
            "credits": data["credits"],
            "multiplier": data["multiplier"],
            "createdAt": data["created_at"],
            "duplicate": data["duplicate"],
        }


def _update_mood(carly: CarlyState) -> None:
    """Leitet Carlys Stimmung aus Bedürfnissen und Schlafzustand ab."""
    if carly.satiety < 30:
        carly.mood = CarlyMood.HUNGRY
    elif carly.energy < 25 or carly.is_sleeping:
        carly.mood = CarlyMood.TIRED
    elif carly.affection >= 70:
        carly.mood = CarlyMood.HAPPY
    else:
        carly.mood = CarlyMood.CURIOUS


def _whole_steps(now: Any, previous: Any, interval: timedelta) -> int:
    """Berechnet vollständige Intervalle seit dem letzten Decay-Zeitpunkt."""
    elapsed = max(0.0, (now - previous).total_seconds())
    return int(elapsed // interval.total_seconds())


def apply_carly_decay(carly: CarlyState, *, now: Any | None = None) -> bool:
    """Wendet zeitbasierten Decay ohne Hintergrundtimer deterministisch an."""
    current = now or timezone.now()
    changed = False

    affection_steps = _whole_steps(current, carly.last_affection_decay_at, timedelta(hours=6))
    if affection_steps:
        carly.affection = max(0, carly.affection - affection_steps)
        carly.last_affection_decay_at += timedelta(hours=6 * affection_steps)
        changed = True

    satiety_steps = _whole_steps(current, carly.last_satiety_decay_at, timedelta(minutes=45))
    if satiety_steps:
        carly.satiety = max(0, carly.satiety - satiety_steps)
        carly.last_satiety_decay_at += timedelta(minutes=45 * satiety_steps)
        changed = True

    energy_interval = timedelta(hours=1) if carly.is_sleeping else timedelta(minutes=30)
    energy_steps = _whole_steps(current, carly.last_energy_decay_at, energy_interval)
    if energy_steps:
        if carly.is_sleeping:
            carly.energy = min(100, carly.energy + energy_steps)
        else:
            carly.energy = max(0, carly.energy - energy_steps)
        carly.last_energy_decay_at += energy_interval * energy_steps
        changed = True

    if changed:
        _update_mood(carly)
        carly.version += 1
        carly.save(
            update_fields=(
                "affection",
                "energy",
                "satiety",
                "mood",
                "last_affection_decay_at",
                "last_energy_decay_at",
                "last_satiety_decay_at",
                "version",
                "updated_at",
            )
        )
    return changed


def level_state(total_experience: int) -> tuple[int, int, int]:
    """Leitet Level, XP im aktuellen Level und nächste Schwelle aus Gesamt-XP ab."""
    remaining = max(0, total_experience)
    level = 1
    threshold = 100
    while remaining >= threshold:
        remaining -= threshold
        level += 1
        threshold = 100 + (level - 1) * 25
    return level, remaining, threshold


def synchronize_level(carly: CarlyState) -> tuple[int, int]:
    """Synchronisiert das persistierte Level und liefert aktuelle Level-XP zurück."""
    level, level_xp, next_level_xp = level_state(carly.experience)
    carly.level = level
    return level_xp, next_level_xp


def _daily_totals(user: User) -> tuple[int, int]:
    """Summiert heutige XP und Credits aus dem unveränderlichen Reward-Ledger."""
    today = timezone.localdate()
    totals = CarlyRewardLog.objects.filter(user=user, created_at__date=today).aggregate(
        xp=Sum("xp"), credits=Sum("credits")
    )
    return int(totals["xp"] or 0), int(totals["credits"] or 0)


def daily_reward_summary(user: User) -> dict[str, int]:
    """Liefert Tagesfortschritt und serverseitige Caps für die Oberfläche."""
    xp, credits = _daily_totals(user)
    return {
        "xpEarned": xp,
        "xpSoftCap": DAILY_XP_SOFT_CAP,
        "xpHardCap": DAILY_XP_HARD_CAP,
        "creditsEarned": credits,
        "creditsSoftCap": DAILY_CREDIT_SOFT_CAP,
        "creditsHardCap": DAILY_CREDIT_HARD_CAP,
    }


def _event_multiplier(user: User, event_type: str, full_until: int) -> Decimal:
    """Skaliert wiederholte Ereignisse bis auf einen Minimalreward herunter."""
    today = timezone.localdate()
    count = CarlyRewardLog.objects.filter(
        user=user, event_type=event_type, created_at__date=today
    ).count()
    if count < full_until:
        return Decimal("1.00")
    if count < full_until * 2:
        return Decimal("0.50")
    if count < full_until * 4:
        return Decimal("0.25")
    return Decimal("0.00")


def _daily_soft_multiplier(current: int, soft_cap: int, hard_cap: int) -> Decimal:
    """Reduziert Rewards zusätzlich, sobald ein Nutzer das Tages-Soft-Cap erreicht."""
    if current < soft_cap:
        return Decimal("1.00")
    midpoint = soft_cap + (hard_cap - soft_cap) // 2
    if current < midpoint:
        return Decimal("0.50")
    return Decimal("0.25")


def _cap_reward(
    base: int,
    event_multiplier: Decimal,
    daily_multiplier: Decimal,
    remaining: int,
) -> int:
    """Wendet Wiederholungsfaktor, Tagesdrosselung und Hard-Cap auf einen Reward an."""
    if base <= 0 or remaining <= 0:
        return 0
    if event_multiplier == 0:
        scaled = 1
    else:
        scaled = max(1, int(Decimal(base) * event_multiplier * daily_multiplier))
    return max(0, min(scaled, remaining))


def _active_xp_bonuses(
    carly: CarlyState,
    *,
    event_type: str,
    now: Any,
    available_xp: int,
) -> tuple[list[dict[str, Any]], bool]:
    """Ermittelt additive Food-Boni innerhalb des verbleibenden Tageslimits."""
    bonuses: list[dict[str, Any]] = []
    remaining = max(0, available_xp)
    consume_berry_focus = False

    def append_bonus(effect: str, amount: int) -> int:
        """Fügt einen Bonus nur bis zum verbleibenden Hard-Cap hinzu."""
        nonlocal remaining
        applied = min(max(0, amount), remaining)
        if applied:
            bonuses.append({"effect": effect, "xp": applied})
            remaining -= applied
        return applied

    if carly.moon_until and carly.moon_until > now:
        append_bonus("moon", MOON_XP_BONUS)

    if (
        event_type in BERRY_FOCUS_EVENTS
        and carly.berry_focus_charges > 0
        and carly.berry_focus_until
        and carly.berry_focus_until > now
    ):
        consume_berry_focus = append_bonus("berry-focus", BERRY_FOCUS_XP_BONUS) > 0

    if event_type == "project_completed" and carly.cookie_until and carly.cookie_until > now:
        append_bonus("cookie-stars", COOKIE_PROJECT_XP_BONUS)

    if event_type in COMPLETION_EVENTS and carly.energy >= 100:
        append_bonus("full-energy", FULL_ENERGY_XP_BONUS)

    return bonuses, consume_berry_focus


@transaction.atomic
def award_carly_reward(
    *,
    user: User,
    event_type: str,
    event_key: str,
    source_type: str = "",
    source_id: str = "",
    xp: int | None = None,
    credits: int | None = None,
    metadata: dict[str, Any] | None = None,
    message: str = "",
) -> CarlyRewardResult:
    """Vergibt eine idempotente, täglich begrenzte und abnehmende Belohnung."""
    rule = REWARD_RULES.get(event_type)
    if rule is None and (xp is None or credits is None):
        raise ValidationError("Unbekannte Carly-Belohnungsregel.")

    existing = CarlyRewardLog.objects.filter(user=user, event_key=event_key).first()
    if existing:
        return CarlyRewardResult(
            id=str(existing.id),
            event_type=existing.event_type,
            xp=0,
            credits=0,
            multiplier=float(existing.multiplier),
            created_at=existing.created_at.isoformat(),
            duplicate=True,
        )

    carly, _ = CarlyState.objects.select_for_update().get_or_create(user=user)
    now = timezone.now()
    apply_carly_decay(carly, now=now)
    base_xp = int(rule["xp"] if xp is None else xp)
    base_credits = int(rule["credits"] if credits is None else credits)
    multiplier = _event_multiplier(user, event_type, int((rule or {}).get("fullUntil", 5)))
    xp_today, credits_today = _daily_totals(user)
    xp_daily_multiplier = _daily_soft_multiplier(xp_today, DAILY_XP_SOFT_CAP, DAILY_XP_HARD_CAP)
    credit_daily_multiplier = _daily_soft_multiplier(
        credits_today, DAILY_CREDIT_SOFT_CAP, DAILY_CREDIT_HARD_CAP
    )
    base_awarded_xp = _cap_reward(
        base_xp,
        multiplier,
        xp_daily_multiplier,
        DAILY_XP_HARD_CAP - xp_today,
    )
    xp_bonuses, consume_berry_focus = _active_xp_bonuses(
        carly,
        event_type=event_type,
        now=now,
        available_xp=DAILY_XP_HARD_CAP - xp_today - base_awarded_xp,
    )
    awarded_xp = base_awarded_xp + sum(int(item["xp"]) for item in xp_bonuses)
    awarded_credits = _cap_reward(
        base_credits,
        multiplier,
        credit_daily_multiplier,
        DAILY_CREDIT_HARD_CAP - credits_today,
    )
    reward_metadata = {**(metadata or {})}
    if xp_bonuses:
        reward_metadata["xpBonuses"] = xp_bonuses
    daily_limit_kinds: list[str] = []
    if base_xp > 0 and xp_today + awarded_xp >= DAILY_XP_HARD_CAP:
        daily_limit_kinds.append("xp")
    if base_credits > 0 and credits_today + awarded_credits >= DAILY_CREDIT_HARD_CAP:
        daily_limit_kinds.append("credits")
    if daily_limit_kinds:
        reward_metadata["dailyLimitReached"] = True
        reward_metadata["dailyLimitKinds"] = daily_limit_kinds

    try:
        with transaction.atomic():
            reward = CarlyRewardLog.objects.create(
                user=user,
                event_type=event_type,
                event_key=event_key[:220],
                source_type=source_type[:40],
                source_id=source_id[:80],
                xp=awarded_xp,
                credits=awarded_credits,
                multiplier=multiplier,
                metadata=reward_metadata,
            )
    except IntegrityError:
        existing = CarlyRewardLog.objects.get(user=user, event_key=event_key)
        return CarlyRewardResult(
            id=str(existing.id),
            event_type=existing.event_type,
            xp=0,
            credits=0,
            multiplier=float(existing.multiplier),
            created_at=existing.created_at.isoformat(),
            duplicate=True,
        )

    if awarded_xp or awarded_credits:
        if consume_berry_focus:
            carly.berry_focus_charges = max(0, carly.berry_focus_charges - 1)
            if carly.berry_focus_charges == 0:
                carly.berry_focus_until = None
        carly.experience += awarded_xp
        carly.credits += awarded_credits
        if event_type in PRODUCTIVE_EVENTS:
            today = timezone.localdate()
            if carly.last_productive_day == today - timedelta(days=1):
                carly.streak += 1
            elif carly.last_productive_day != today:
                carly.streak = 1
            carly.last_productive_day = today
            carly.affection = min(100, carly.affection + max(1, min(5, awarded_xp // 10)))
            if carly.is_sleeping:
                carly.is_sleeping = False
                carly.last_energy_decay_at = timezone.now()
        synchronize_level(carly)
        if message:
            carly.last_message = message[:300]
        _update_mood(carly)
        carly.version += 1
        carly.save()

    return CarlyRewardResult(
        id=str(reward.id),
        event_type=event_type,
        xp=awarded_xp,
        credits=awarded_credits,
        multiplier=float(multiplier),
        created_at=reward.created_at.isoformat(),
    )


def award_carly_reward_safely(**kwargs: Any) -> CarlyRewardResult | None:
    """Vergibt einen Reward fehlertolerant, damit Carly Kernworkflows niemals blockiert."""
    try:
        with transaction.atomic():
            return award_carly_reward(**kwargs)
    except Exception:
        logger.exception("Carly-Reward konnte nicht vergeben werden.")
        return None


def reward_task_completion(*, user: User, task: Any) -> CarlyRewardResult:
    """Bewertet einen Taskabschluss anhand von Unteraufgaben und Zusammenarbeit."""
    rule = REWARD_RULES["task_completed"]
    completed_subtasks = min(
        int(rule["subtaskLimit"]),
        task.subtasks.filter(is_done=True).count(),
    )
    participant_ids = {task.owner_id, task.assignee_id}
    participant_ids.update(task.collaborators.values_list("id", flat=True))
    participant_ids.discard(None)
    collaborator_bonus_count = min(
        int(rule["collaboratorLimit"]),
        max(0, len(participant_ids) - 1),
    )
    xp = (
        int(rule["xp"])
        + completed_subtasks * int(rule["subtaskXp"])
        + collaborator_bonus_count * int(rule["collaboratorXp"])
    )
    credits = (
        int(rule["credits"])
        + completed_subtasks * int(rule["subtaskCredits"])
        + collaborator_bonus_count * int(rule["collaboratorCredits"])
    )
    return award_carly_reward(
        user=user,
        event_type="task_completed",
        event_key=f"task-completed:{task.id}",
        source_type="task",
        source_id=str(task.id),
        xp=xp,
        credits=credits,
        metadata={
            "completedSubtasks": completed_subtasks,
            "collaboratorBonusCount": collaborator_bonus_count,
        },
        message=f"„{task.title}“ erledigt. Das zählt.",
    )


def reward_task_completion_safely(*, user: User, task: Any) -> CarlyRewardResult | None:
    """Bewertet einen Task fehlertolerant, ohne dessen Abschluss zurückzurollen."""
    try:
        with transaction.atomic():
            return reward_task_completion(user=user, task=task)
    except Exception:
        logger.exception("Carly-Reward für Taskabschluss konnte nicht vergeben werden.")
        return None


def get_reward_rules_payload() -> dict[str, Any]:
    """Liefert Regeln und Food-Katalog aus derselben Quelle wie die Vergabe."""
    return {
        "dailyCaps": {
            "xpSoft": DAILY_XP_SOFT_CAP,
            "xpHard": DAILY_XP_HARD_CAP,
            "creditsSoft": DAILY_CREDIT_SOFT_CAP,
            "creditsHard": DAILY_CREDIT_HARD_CAP,
        },
        "rewards": [
            {
                "eventType": key,
                "label": value["label"],
                "xp": value["xp"],
                "credits": value["credits"],
                "fullUntil": value["fullUntil"],
                "halfUntil": int(value["fullUntil"]) * 2,
                "quarterUntil": int(value["fullUntil"]) * 4,
                "bonuses": (
                    [
                        (
                            f"+{value['subtaskXp']} XP / +{value['subtaskCredits']} Credits "
                            f"je erledigter Unteraufgabe (max. {value['subtaskLimit']})"
                        ),
                        (
                            f"+{value['collaboratorXp']} XP / "
                            f"+{value['collaboratorCredits']} Credits "
                            f"je weiterem Mitwirkenden (max. {value['collaboratorLimit']})"
                        ),
                    ]
                    if key == "task_completed"
                    else []
                ),
            }
            for key, value in REWARD_RULES.items()
        ],
        "foods": [
            {
                "id": key,
                "label": value["label"],
                "cost": value["cost"],
                "satiety": value["satiety"],
                "affection": value["affection"],
                "effect": value["effect"],
                "bonusDurationSeconds": value.get("bonusDurationSeconds"),
                "visualDurationSeconds": value.get("visualDurationSeconds"),
            }
            for key, value in FOOD_RULES.items()
        ],
    }


def serialize_reward_log(log: CarlyRewardLog) -> dict[str, Any]:
    """Serialisiert einen Ledger-Eintrag ohne interne Anti-Cheat-Schlüssel."""
    return {
        "id": str(log.id),
        "eventType": log.event_type,
        "sourceType": log.source_type,
        "sourceId": log.source_id,
        "xp": log.xp,
        "credits": log.credits,
        "multiplier": float(log.multiplier),
        "metadata": log.metadata,
        "createdAt": log.created_at.isoformat(),
    }
