# apps/preferences/views.py
"""Stellt persönliche Einstellungen und Carly-Aktionen bereit."""

from typing import Any

from django.db import transaction
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.preferences.models import CarlyRewardLog, UserSettings
from apps.preferences.rewards import (
    daily_reward_summary,
    get_reward_rules_payload,
    serialize_reward_log,
)
from apps.preferences.serializers import (
    AppSettingsSerializer,
    AppSettingsWriteSerializer,
    CarlyActionSerializer,
    CarlySettingsWriteSerializer,
    CarlyStateSerializer,
)
from apps.preferences.services import (
    bootstrap_preferences,
    perform_carly_action,
    reset_carly_settings,
    update_carly_settings,
    update_settings,
)


class AppSettingsView(APIView):
    """Liest, ändert und setzt persönliche App-Einstellungen zurück."""

    @extend_schema(responses={200: AppSettingsSerializer})
    def get(self, request: Any) -> Response:
        """Liefert den vollständigen Einstellungszustand."""
        settings_obj, _ = bootstrap_preferences(user=request.user)
        return Response(AppSettingsSerializer(settings_obj).data)

    @extend_schema(request=AppSettingsWriteSerializer, responses={200: AppSettingsSerializer})
    def patch(self, request: Any) -> Response:
        """Aktualisiert partielle verschachtelte Einstellungen."""
        bootstrap_preferences(user=request.user)
        serializer = AppSettingsWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        settings_obj = update_settings(user=request.user, data=dict(serializer.validated_data))
        return Response(AppSettingsSerializer(settings_obj).data)

    @extend_schema(responses={200: AppSettingsSerializer})
    def delete(self, request: Any) -> Response:
        """Setzt die Einstellungen atomar auf sichere Standardwerte zurück."""
        with transaction.atomic():
            UserSettings.objects.filter(user=request.user).delete()
            settings_obj, _ = bootstrap_preferences(user=request.user)
        return Response(AppSettingsSerializer(settings_obj).data)


class CarlyStateView(APIView):
    """Liest und ändert den persönlichen Carly-Zustand."""

    @extend_schema(responses={200: CarlyStateSerializer})
    def get(self, request: Any) -> Response:
        """Liefert Einstellungen und Fortschritt."""
        _, carly = bootstrap_preferences(user=request.user)
        return Response(CarlyStateSerializer(carly).data)

    @extend_schema(request=CarlySettingsWriteSerializer, responses={200: CarlyStateSerializer})
    def patch(self, request: Any) -> Response:
        """Ändert ausschließlich freigegebene Carly-Einstellungen."""
        bootstrap_preferences(user=request.user)
        serializer = CarlySettingsWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        carly = update_carly_settings(user=request.user, data=dict(serializer.validated_data))
        return Response(CarlyStateSerializer(carly).data)

    @extend_schema(responses={200: CarlyStateSerializer})
    def delete(self, request: Any) -> Response:
        """Setzt nur Carlys UI-Einstellungen zurück und bewahrt Economy sowie Fortschritt."""
        bootstrap_preferences(user=request.user)
        carly = reset_carly_settings(user=request.user)
        return Response(CarlyStateSerializer(carly).data)


class CarlyActionView(APIView):
    """Führt eine benannte, serverseitig begrenzte Carly-Aktion aus."""

    @extend_schema(request=CarlyActionSerializer, responses={200: CarlyStateSerializer})
    def post(self, request: Any, action: str) -> Response:
        """Validiert Parameter, Cooldown, Tageslimit und Versionsstand."""
        bootstrap_preferences(user=request.user)
        serializer = CarlyActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        carly = perform_carly_action(
            user=request.user,
            action=action,
            supplied_version=serializer.validated_data["version"],
            food=serializer.validated_data.get("food"),
        )
        return Response(CarlyStateSerializer(carly).data)


class CarlyRewardRulesView(APIView):
    """Liefert transparente serverseitige Reward- und Futterregeln."""

    def get(self, request: Any) -> Response:
        """Liefert Regeln sowie den aktuellen Tagesfortschritt."""
        bootstrap_preferences(user=request.user)
        payload = get_reward_rules_payload()
        payload["today"] = daily_reward_summary(request.user)
        return Response(payload)


class CarlyRewardHistoryView(APIView):
    """Liefert die letzten servergeprüften Carly-Belohnungen des Nutzers."""

    def get(self, request: Any) -> Response:
        """Filtert optional ab einem ISO-Zeitpunkt und begrenzt die Ergebniszahl."""
        bootstrap_preferences(user=request.user)
        try:
            limit = max(1, min(50, int(request.query_params.get("limit", 20))))
        except (TypeError, ValueError):
            limit = 20
        queryset = CarlyRewardLog.objects.filter(user=request.user)
        after_raw = request.query_params.get("after")
        if after_raw:
            after = parse_datetime(after_raw)
            if after is not None:
                queryset = queryset.filter(created_at__gt=after)
        rewards = list(queryset.order_by("-created_at")[:limit])
        return Response(
            {
                "items": [serialize_reward_log(item) for item in rewards],
                "today": daily_reward_summary(request.user),
            }
        )
