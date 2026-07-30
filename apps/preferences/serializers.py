# apps/preferences/serializers.py
"""Validiert verschachtelte App-Einstellungen und Carly-Daten."""

from typing import Any

from rest_framework import serializers

from apps.preferences.models import (
    DEFAULT_ALARMS,
    AccessibilityFontSize,
    CarlyState,
    ColorVisionMode,
    UserSettings,
)
from apps.preferences.rewards import daily_reward_summary, level_state


class AccessibilitySettingsSerializer(serializers.Serializer[dict[str, Any]]):
    """Validiert alle barrierebezogenen Einstellungen."""

    colorVisionMode = serializers.ChoiceField(choices=ColorVisionMode.values, required=False)
    neuroMode = serializers.BooleanField(required=False)
    reduceMotion = serializers.BooleanField(required=False)
    reduceHover = serializers.BooleanField(required=False)
    magnifier = serializers.BooleanField(required=False)
    fontSize = serializers.ChoiceField(choices=AccessibilityFontSize.values, required=False)
    highContrast = serializers.BooleanField(required=False)


class GeneralSettingsSerializer(serializers.Serializer[dict[str, Any]]):
    """Validiert allgemeines Workspace-Verhalten."""

    dynamicNewColumns = serializers.BooleanField(required=False)
    tooltipsEnabled = serializers.BooleanField(required=False)
    allowInvites = serializers.BooleanField(required=False)
    hideRealName = serializers.BooleanField(required=False)
    realName = serializers.CharField(max_length=60, allow_blank=True, required=False)
    nickname = serializers.CharField(max_length=60, allow_blank=True, required=False)
    alarms = serializers.DictField(child=serializers.BooleanField(), required=False)

    def validate_alarms(self, value: dict[str, bool]) -> dict[str, bool]:
        """Erlaubt ausschließlich bekannte Alarmkategorien."""
        unknown = set(value) - set(DEFAULT_ALARMS)
        if unknown:
            raise serializers.ValidationError(
                "Unbekannte Alarmkategorien: " + ", ".join(sorted(unknown))
            )
        return value


class ToolSettingsSerializer(serializers.Serializer[dict[str, Any]]):
    """Validiert optionale Werkzeuge und Wetterort."""

    pomodoro = serializers.BooleanField(required=False)
    taskTimer = serializers.BooleanField(required=False)
    weather = serializers.BooleanField(required=False)
    weatherLocation = serializers.CharField(max_length=120, allow_blank=True, required=False)


class AppSettingsWriteSerializer(serializers.Serializer[dict[str, Any]]):
    """Validiert partielle verschachtelte Einstellungsänderungen."""

    accessibility = AccessibilitySettingsSerializer(required=False)
    general = GeneralSettingsSerializer(required=False)
    tools = ToolSettingsSerializer(required=False)
    version = serializers.IntegerField(min_value=1)


class AppSettingsSerializer(serializers.ModelSerializer[UserSettings]):
    """Entspricht dem AppSettings-Interface des Angular-Frontends."""

    accessibility = serializers.SerializerMethodField()
    general = serializers.SerializerMethodField()
    tools = serializers.SerializerMethodField()

    class Meta:
        model = UserSettings
        fields = ("accessibility", "general", "tools", "version")

    def get_accessibility(self, obj: UserSettings) -> dict[str, Any]:
        """Bündelt persistierte Barrierefreiheitsfelder."""
        return {
            "colorVisionMode": obj.color_vision_mode,
            "neuroMode": obj.neuro_mode,
            "reduceMotion": obj.reduce_motion,
            "reduceHover": obj.reduce_hover,
            "magnifier": obj.magnifier,
            "fontSize": obj.font_size,
            "highContrast": obj.high_contrast,
        }

    def get_general(self, obj: UserSettings) -> dict[str, Any]:
        """Bündelt allgemeine Einstellungen und Alarmkategorien."""
        return {
            "dynamicNewColumns": obj.dynamic_new_columns,
            "tooltipsEnabled": obj.tooltips_enabled,
            "allowInvites": obj.allow_invites,
            "hideRealName": obj.hide_real_name,
            "realName": obj.real_name,
            "nickname": obj.nickname,
            "alarms": {**DEFAULT_ALARMS, **obj.alarms},
        }

    def get_tools(self, obj: UserSettings) -> dict[str, Any]:
        """Bündelt optionale Werkzeugzustände."""
        return {
            "pomodoro": obj.pomodoro,
            "taskTimer": obj.task_timer,
            "weather": obj.weather,
            "weatherLocation": obj.weather_location,
        }


class CarlySettingsWriteSerializer(serializers.Serializer[dict[str, Any]]):
    """Validiert ausschließlich nutzersteuerbare Carly-Einstellungen."""

    enabled = serializers.BooleanField(required=False)
    showGlobally = serializers.BooleanField(required=False)
    messagesEnabled = serializers.BooleanField(required=False)
    taskReactionsEnabled = serializers.BooleanField(required=False)
    autoSleep = serializers.BooleanField(required=False)
    reduceAnimations = serializers.BooleanField(required=False)
    rewardPopupsEnabled = serializers.BooleanField(required=False)
    showXpRewards = serializers.BooleanField(required=False)
    showCreditRewards = serializers.BooleanField(required=False)
    positionX = serializers.FloatField(min_value=0.0, max_value=1.0, required=False)
    version = serializers.IntegerField(min_value=1)


class CarlyStateSerializer(serializers.ModelSerializer[CarlyState]):
    """Entspricht dem CarlyState-Interface des Frontends."""

    settings = serializers.SerializerMethodField()
    progress = serializers.SerializerMethodField()
    reward = serializers.SerializerMethodField()
    effect = serializers.SerializerMethodField()

    class Meta:
        model = CarlyState
        fields = ("settings", "progress", "reward", "effect", "version")

    def get_settings(self, obj: CarlyState) -> dict[str, Any]:
        """Bündelt die optionalen Carly-Funktionen."""
        return {
            "enabled": obj.enabled,
            "showGlobally": obj.show_globally,
            "messagesEnabled": obj.messages_enabled,
            "taskReactionsEnabled": obj.task_reactions_enabled,
            "autoSleep": obj.auto_sleep,
            "reduceAnimations": obj.reduce_animations,
            "rewardPopupsEnabled": obj.reward_popups_enabled,
            "showXpRewards": obj.show_xp_rewards,
            "showCreditRewards": obj.show_credit_rewards,
        }

    def get_progress(self, obj: CarlyState) -> dict[str, Any]:
        """Gibt serverkontrollierte Fortschritts-, Inventar- und Economy-Werte aus."""
        level, level_xp, next_level_xp = level_state(obj.experience)
        return {
            "level": level,
            "experience": obj.experience,
            "levelExperience": level_xp,
            "nextLevelExperience": next_level_xp,
            "credits": obj.credits,
            "inventory": obj.inventory,
            "affection": obj.affection,
            "energy": obj.energy,
            "satiety": obj.satiety,
            "streak": obj.streak,
            "mood": obj.mood,
            "isSleeping": obj.is_sleeping,
            "lastMessage": obj.last_message,
            "positionX": obj.position_x,
            "auraUntil": obj.aura_until.isoformat() if obj.aura_until else None,
            "moonUntil": obj.moon_until.isoformat() if obj.moon_until else None,
            "dailyRewards": daily_reward_summary(obj.user),
        }

    def get_reward(self, obj: CarlyState) -> dict[str, Any] | None:
        """Liefert den Reward der gerade ausgeführten Aktion, sofern vorhanden."""
        reward = getattr(obj, "_reward_result", None)
        return reward.as_api_dict() if reward else None

    def get_effect(self, obj: CarlyState) -> str | None:
        """Liefert einen unmittelbar auszulösenden Food-Effekt."""
        effect = getattr(obj, "_special_effect", None)
        return effect if effect and effect != "none" else None


class CarlyActionSerializer(serializers.Serializer[dict[str, Any]]):
    """Validiert optionale Aktionsparameter."""

    food = serializers.ChoiceField(choices=("fish", "berry", "cookie", "potion"), required=False)
    version = serializers.IntegerField(min_value=1)
