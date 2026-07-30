# apps/preferences/services.py
"""Kapselt Einstellungsänderungen und missbrauchsbegrenzte Carly-Aktionen."""

from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import Throttled, ValidationError

from apps.accounts.models import User
from apps.common.exceptions import VersionConflictError
from apps.preferences.models import CarlyActionLog, CarlyMood, CarlyState, UserSettings
from apps.preferences.rewards import (
    FOOD_RULES,
    apply_carly_decay,
    award_carly_reward,
    synchronize_level,
)
from apps.workspaces.models import Workspace

ACTION_RULES = {
    "pet": {
        "cooldown": 20,
        "daily": 20,
        "affection": 2,
        "energy": 0,
        "satiety": 0,
        "xp": 5,
        "message": "Carly schnurrt zufrieden.",
    },
    "feed": {
        "cooldown": 20,
        "daily": 12,
        "affection": 0,
        "energy": 0,
        "satiety": 0,
        "xp": 2,
        "message": "Carly kaut mit bemerkenswertem Ernst.",
    },
    "play": {
        "cooldown": 90,
        "daily": 10,
        "affection": 3,
        "energy": -8,
        "satiety": -2,
        "xp": 8,
        "message": "Carly hatte Spaß.",
    },
    "sleep": {
        "cooldown": 10,
        "daily": 12,
        "affection": 0,
        "energy": 0,
        "satiety": 0,
        "xp": 0,
        "message": "Carly schläft jetzt.",
    },
    "wake": {
        "cooldown": 10,
        "daily": 12,
        "affection": 0,
        "energy": 0,
        "satiety": -2,
        "xp": 0,
        "message": "Carly ist wieder wach.",
    },
}


@transaction.atomic
def bootstrap_preferences(
    *, user: User, workspace: Workspace | None = None
) -> tuple[UserSettings, CarlyState]:
    """Erstellt die persönlichen Standardzustände idempotent."""
    settings_obj, _ = UserSettings.objects.get_or_create(
        user=user,
        defaults={"real_name": user.display_name, "nickname": user.display_name},
    )
    carly, _ = CarlyState.objects.get_or_create(user=user)
    apply_carly_decay(carly)
    return settings_obj, carly


def _assert_version(current: int, supplied: int) -> None:
    """Prüft eine optimistische Versionsnummer."""
    if current != supplied:
        raise VersionConflictError(
            {
                "message": "Die Einstellungen wurden zwischenzeitlich geändert.",
                "currentVersion": current,
            }
        )


@transaction.atomic
def update_settings(*, user: User, data: dict[str, Any]) -> UserSettings:
    """Überträgt validierte verschachtelte Einstellungen atomar."""
    settings_obj = UserSettings.objects.select_for_update().get(user=user)
    _assert_version(settings_obj.version, data.pop("version"))
    accessibility_map = {
        "colorVisionMode": "color_vision_mode",
        "neuroMode": "neuro_mode",
        "reduceMotion": "reduce_motion",
        "reduceHover": "reduce_hover",
        "magnifier": "magnifier",
        "fontSize": "font_size",
        "highContrast": "high_contrast",
    }
    general_map = {
        "dynamicNewColumns": "dynamic_new_columns",
        "tooltipsEnabled": "tooltips_enabled",
        "allowInvites": "allow_invites",
        "hideRealName": "hide_real_name",
        "realName": "real_name",
        "nickname": "nickname",
    }
    tools_map = {
        "pomodoro": "pomodoro",
        "taskTimer": "task_timer",
        "weather": "weather",
        "weatherLocation": "weather_location",
    }
    for key, field in accessibility_map.items():
        if key in data.get("accessibility", {}):
            setattr(settings_obj, field, data["accessibility"][key])
    general = data.get("general", {})
    for key, field in general_map.items():
        if key in general:
            setattr(settings_obj, field, general[key])
    if "alarms" in general:
        settings_obj.alarms = {**settings_obj.alarms, **general["alarms"]}
    for key, field in tools_map.items():
        if key in data.get("tools", {}):
            setattr(settings_obj, field, data["tools"][key])
    settings_obj.version += 1
    settings_obj.full_clean()
    settings_obj.save()
    return settings_obj


@transaction.atomic
def reset_carly_settings(*, user: User) -> CarlyState:
    """Setzt nur Carlys Anzeigeeinstellungen zurück und bewahrt Economy und Fortschritt."""
    carly = CarlyState.objects.select_for_update().get(user=user)
    apply_carly_decay(carly)
    carly.enabled = True
    carly.show_globally = True
    carly.messages_enabled = True
    carly.task_reactions_enabled = True
    carly.auto_sleep = True
    carly.reduce_animations = False
    carly.reward_popups_enabled = True
    carly.show_xp_rewards = True
    carly.show_credit_rewards = True
    carly.position_x = 0.85
    carly.version += 1
    carly.save(
        update_fields=(
            "enabled",
            "show_globally",
            "messages_enabled",
            "task_reactions_enabled",
            "auto_sleep",
            "reduce_animations",
            "reward_popups_enabled",
            "show_xp_rewards",
            "show_credit_rewards",
            "position_x",
            "version",
            "updated_at",
        )
    )
    return carly


@transaction.atomic
def update_carly_settings(*, user: User, data: dict[str, Any]) -> CarlyState:
    """Ändert ausschließlich nutzersteuerbare Carly-Felder."""
    carly = CarlyState.objects.select_for_update().get(user=user)
    _assert_version(carly.version, data.pop("version"))
    field_map = {
        "enabled": "enabled",
        "showGlobally": "show_globally",
        "messagesEnabled": "messages_enabled",
        "taskReactionsEnabled": "task_reactions_enabled",
        "autoSleep": "auto_sleep",
        "reduceAnimations": "reduce_animations",
        "rewardPopupsEnabled": "reward_popups_enabled",
        "showXpRewards": "show_xp_rewards",
        "showCreditRewards": "show_credit_rewards",
        "positionX": "position_x",
    }
    for key, field in field_map.items():
        if key in data:
            setattr(carly, field, data[key])
    carly.version += 1
    carly.full_clean()
    carly.save()
    return carly


def _update_mood(carly: CarlyState) -> None:
    """Leitet die Stimmung nachvollziehbar aus Energie und Sättigung ab."""
    if carly.satiety < 30:
        carly.mood = CarlyMood.HUNGRY
    elif carly.energy < 25 or carly.is_sleeping:
        carly.mood = CarlyMood.TIRED
    elif carly.affection >= 70:
        carly.mood = CarlyMood.HAPPY
    else:
        carly.mood = CarlyMood.CURIOUS


@transaction.atomic
def perform_carly_action(
    *, user: User, action: str, supplied_version: int, food: str | None = None
) -> CarlyState:
    """Führt Pflege, Füttern und Käufe vollständig serverautoritativ aus."""
    carly = CarlyState.objects.select_for_update().get(user=user)
    _assert_version(carly.version, supplied_version)
    apply_carly_decay(carly)
    now = timezone.now()
    today = timezone.localdate()

    if action == "buy-food":
        if not food or food not in FOOD_RULES:
            raise ValidationError({"food": "Bitte wähle ein gültiges Futter aus."})
        food_rule = FOOD_RULES[food]
        cost = int(food_rule["cost"])
        if carly.credits < cost:
            raise ValidationError({"food": "Dafür reichen deine Carly-Credits noch nicht."})
        inventory = {**carly.inventory}
        inventory[food] = int(inventory.get(food, 0)) + 1
        carly.inventory = inventory
        carly.credits -= cost
        carly.last_message = f"{food_rule['label']} gekauft. Vorrat: {inventory[food]}."
        carly.version += 1
        carly.save()
        setattr(carly, "_special_effect", "purchase")
        return carly

    rule = ACTION_RULES.get(action)
    if rule is None:
        raise ValidationError("Diese Carly-Aktion ist nicht unterstützt.")
    latest = CarlyActionLog.objects.filter(user=user, action=action).order_by("-created_at").first()
    if latest and latest.created_at > now - timedelta(seconds=rule["cooldown"]):
        cooldown_ends_at = latest.created_at + timedelta(seconds=rule["cooldown"])
        wait = int((cooldown_ends_at - now).total_seconds()) + 1
        raise Throttled(wait=wait, detail="Carly braucht kurz Zeit bis zur nächsten Aktion.")
    daily_count = CarlyActionLog.objects.filter(
        user=user, action=action, created_at__date=today
    ).count()
    if daily_count >= rule["daily"]:
        raise Throttled(wait=3600, detail="Das Tageslimit dieser Carly-Aktion ist erreicht.")

    special_effect = "none"
    if action == "sleep":
        carly.is_sleeping = True
        carly.last_energy_decay_at = now
    elif action == "wake":
        carly.is_sleeping = False
        carly.last_energy_decay_at = now
    elif carly.is_sleeping:
        raise ValidationError("Carly schläft gerade. Wecke sie zuerst.")

    if action == "feed":
        if not food or food not in FOOD_RULES:
            raise ValidationError({"food": "Bitte wähle ein gültiges Futter aus."})
        inventory = {**carly.inventory}
        if int(inventory.get(food, 0)) <= 0:
            raise ValidationError({"food": "Dieses Futter ist nicht in deinem Inventar."})
        inventory[food] = int(inventory.get(food, 0)) - 1
        carly.inventory = inventory
        food_rule = FOOD_RULES[food]
        carly.affection = min(100, carly.affection + int(food_rule["affection"]))
        carly.satiety = min(100, carly.satiety + int(food_rule["satiety"]))
        if food == "potion":
            carly.energy = 100
            carly.aura_until = now + timedelta(seconds=int(food_rule["effectDurationSeconds"]))
        else:
            carly.energy = min(100, carly.energy + int(food_rule["energy"]))
        if food == "fish":
            carly.moon_until = now + timedelta(seconds=int(food_rule["effectDurationSeconds"]))
        special_effect = str(food_rule["effect"])
        carly.last_message = f"{food_rule['label']} – eine akzeptable Wahl."
    else:
        carly.affection = max(0, min(100, carly.affection + rule["affection"]))
        carly.energy = max(0, min(100, carly.energy + rule["energy"]))
        carly.satiety = max(0, min(100, carly.satiety + rule["satiety"]))
        carly.last_message = rule["message"]

    _update_mood(carly)
    carly.version += 1
    carly.save()
    action_log = CarlyActionLog.objects.create(user=user, action=action, points=0)

    reward_result = None
    if action in {"pet", "play", "feed"}:
        reward_result = award_carly_reward(
            user=user,
            event_type=action,
            event_key=f"care:{action}:{today.isoformat()}:{daily_count + 1}",
            source_type="carly",
            source_id=str(carly.id),
            message=carly.last_message,
        )
        carly.refresh_from_db()
        action_log.points = reward_result.xp
        action_log.save(update_fields=("points", "updated_at"))

    synchronize_level(carly)
    setattr(carly, "_reward_result", reward_result)
    setattr(carly, "_special_effect", special_effect)
    return carly


@transaction.atomic
def reward_productivity(*, user: User, points: int, message: str) -> CarlyState:
    """Erhält die alte Service-Schnittstelle und nutzt intern das neue Reward-Ledger."""
    now = timezone.now()
    result = award_carly_reward(
        user=user,
        event_type="task_updated",
        event_key=f"legacy-productivity:{user.id}:{int(now.timestamp() // 300)}",
        source_type="legacy",
        xp=max(0, points),
        credits=max(0, points * 2),
        message=message,
    )
    carly = CarlyState.objects.get(user=user)
    setattr(carly, "_reward_result", result)
    return carly
