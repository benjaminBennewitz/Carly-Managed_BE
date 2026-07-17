# apps/demo/views.py
"""Stellt Status und kontrollierten Reset für lokale Testdaten bereit."""

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework import permissions
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.demo.permissions import CanResetDemoData
from apps.demo.serializers import DemoResetResultSerializer, DemoStatusSerializer
from apps.demo.services import reset_demo_workspace
from apps.demo.throttles import DemoResetRateThrottle


class DemoStatusView(APIView):
    """Informiert das Frontend, ob der Reset-Button angezeigt werden darf."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={200: DemoStatusSerializer})
    def get(self, request: Request) -> Response:
        """Bewertet Feature-Flag, Umgebung und Staff-Status ohne Seiteneffekt."""
        enabled = bool(settings.DEMO_DATA_RESET_ENABLED)
        can_reset = bool(
            enabled
            and request.user.is_staff
            and (settings.DEBUG or settings.DEMO_DATA_RESET_ALLOW_PRODUCTION)
        )
        return Response(
            {
                "enabled": enabled,
                "canReset": can_reset,
                "workspaceName": settings.DEMO_WORKSPACE_NAME,
            }
        )


class DemoResetView(APIView):
    """Setzt ausschließlich den Demo-Workspace des angemeldeten Staff-Nutzers zurück."""

    permission_classes = [CanResetDemoData]
    throttle_classes = [DemoResetRateThrottle]

    @extend_schema(request=None, responses={200: DemoResetResultSerializer})
    def post(self, request: Request) -> Response:
        """Erzeugt den reproduzierbaren Ausgangsstand in einer Transaktion neu."""
        result = reset_demo_workspace(owner=request.user)
        return Response(result.as_dict())
