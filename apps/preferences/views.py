# apps/preferences/views.py
"""Stellt persönliche Einstellungen und Carly-Aktionen bereit."""

from typing import Any

from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.preferences.models import CarlyState, UserSettings
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
        """Setzt Carly zurück, ohne andere Kontodaten zu verändern."""
        with transaction.atomic():
            CarlyState.objects.filter(user=request.user).delete()
            _, carly = bootstrap_preferences(user=request.user)
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
