# apps/preferences/admin.py
"""Registriert Einstellungen und Carly-Zustände für die Administration."""

from django.contrib import admin

from apps.preferences.models import CarlyActionLog, CarlyState, UserSettings


@admin.register(UserSettings)
class UserSettingsAdmin(admin.ModelAdmin):
    """Zeigt nutzerspezifische UI- und Barrierefreiheitseinstellungen."""

    readonly_fields = ("id", "created_at", "updated_at")
    list_display = ("user", "color_vision_mode", "font_size", "updated_at")
    list_filter = ("color_vision_mode", "font_size", "reduce_motion", "high_contrast")
    search_fields = ("user__email", "user__display_name")
    list_select_related = ("user",)


@admin.register(CarlyState)
class CarlyStateAdmin(admin.ModelAdmin):
    """Stellt Carly-Fortschritt ohne Aktionsmanipulation übersichtlich dar."""

    readonly_fields = ("id", "created_at", "updated_at")
    list_display = ("user", "level", "affection", "mood", "streak")
    list_filter = ("mood", "level")
    search_fields = ("user__email", "user__display_name")
    list_select_related = ("user",)


@admin.register(CarlyActionLog)
class CarlyActionLogAdmin(admin.ModelAdmin):
    """Hält serverseitig geprüfte Carly-Aktionen nachvollziehbar."""

    readonly_fields = ("id", "created_at", "updated_at")
    list_display = ("user", "action", "points", "created_at")
    list_filter = ("action",)
    search_fields = ("user__email", "workspace__name", "action")
    list_select_related = ("user",)
