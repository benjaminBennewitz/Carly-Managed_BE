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
from apps.workspaces.models import Workspace

ACTION_RULES = {
    "pet": {
        "cooldown": 20,
        "daily": 20,
        "affection": 2,
        "energy": 0,
        "satiety": 0,
        "xp": 1,
        "message": "Carly schnurrt zufrieden.",
    },
    "feed": {
        "cooldown": 60,
        "daily": 8,
        "affection": 1,
        "energy": 2,
        "satiety": 14,
        "xp": 2,
        "message": "Carly ist wieder satt.",
    },
    "play": {
        "cooldown": 90,
        "daily": 10,
        "affection": 3,
        "energy": -8,
        "satiety": -2,
        "xp": 3,
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
        "energy": 12,
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
    """Führt eine begrenzte Carly-Aktion mit Cooldown und Tageslimit aus."""
    rule = ACTION_RULES.get(action)
    if rule is None:
        raise ValidationError("Diese Carly-Aktion ist nicht unterstützt.")
    carly = CarlyState.objects.select_for_update().get(user=user)
    _assert_version(carly.version, supplied_version)
    now = timezone.now()
    today = timezone.localdate()
    latest = CarlyActionLog.objects.filter(user=user, action=action).order_by("-created_at").first()
    if latest and latest.created_at > now - timedelta(seconds=rule["cooldown"]):
        wait = (
            int((latest.created_at + timedelta(seconds=rule["cooldown"]) - now).total_seconds()) + 1
        )
        raise Throttled(wait=wait, detail="Carly braucht kurz Zeit bis zur nächsten Aktion.")
    daily_count = CarlyActionLog.objects.filter(
        user=user, action=action, created_at__date=today
    ).count()
    if daily_count >= rule["daily"]:
        raise Throttled(wait=3600, detail="Das Tageslimit dieser Carly-Aktion ist erreicht.")
    if action == "sleep":
        carly.is_sleeping = True
    elif action == "wake":
        carly.is_sleeping = False
    elif carly.is_sleeping:
        raise ValidationError("Carly schläft gerade. Wecke sie zuerst.")
    if action == "feed" and not food:
        raise ValidationError({"food": "Bitte wähle ein Futter aus."})
    carly.affection = max(0, min(100, carly.affection + rule["affection"]))
    carly.energy = max(0, min(100, carly.energy + rule["energy"]))
    carly.satiety = max(0, min(100, carly.satiety + rule["satiety"]))
    carly.experience += rule["xp"]
    carly.level = 1 + carly.experience // 100
    carly.last_message = rule["message"]
    _update_mood(carly)
    carly.version += 1
    carly.save()
    CarlyActionLog.objects.create(user=user, action=action, points=rule["xp"])
    return carly


@transaction.atomic
def reward_productivity(*, user: User, points: int, message: str) -> CarlyState:
    """Belohnt echte Produktivität mit serverseitig begrenztem Fortschritt."""
    carly = CarlyState.objects.select_for_update().get(user=user)
    today = timezone.localdate()
    if carly.last_productive_day == today:
        daily_points = (
            CarlyActionLog.objects.filter(
                user=user, action="productivity", created_at__date=today
            ).aggregate(total=__import__("django.db.models", fromlist=["Sum"]).Sum("points"))[
                "total"
            ]
            or 0
        )
        points = max(0, min(points, 50 - daily_points))
    if points <= 0:
        return carly
    if carly.last_productive_day == today - timedelta(days=1):
        carly.streak += 1
    elif carly.last_productive_day != today:
        carly.streak = 1
    carly.last_productive_day = today
    carly.experience += points
    carly.affection = min(100, carly.affection + max(1, points // 5))
    carly.level = 1 + carly.experience // 100
    carly.last_message = message[:300]
    _update_mood(carly)
    carly.version += 1
    carly.save()
    CarlyActionLog.objects.create(user=user, action="productivity", points=points)
    return carly
