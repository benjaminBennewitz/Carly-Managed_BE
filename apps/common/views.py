# apps/common/views.py
"""Stellt öffentliche Betriebszustände ohne sensible Informationen bereit."""

from django.db import connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


@never_cache
@require_GET
def health_view(request: object) -> JsonResponse:
    """Prüft, ob Prozess und Datenbank Anfragen verarbeiten können."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    return JsonResponse({"status": "ok"})
