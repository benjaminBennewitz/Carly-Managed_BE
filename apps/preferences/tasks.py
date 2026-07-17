# apps/preferences/tasks.py
"""Pflegt zeitabhängige Carly-Zustände in einem täglichen Hintergrundlauf."""

from celery import shared_task
from django.utils import timezone

from apps.preferences.models import CarlyState


@shared_task
def refresh_carly_streaks() -> int:
    """Setzt unterbrochene Streaks zurück und reduziert passive Werte moderat."""
    today = timezone.localdate()
    changed = 0
    for carly in CarlyState.objects.iterator(chunk_size=500):
        fields = []
        if (
            carly.last_productive_day
            and (today - carly.last_productive_day).days > 1
            and carly.streak
        ):
            carly.streak = 0
            fields.append("streak")
        if not carly.is_sleeping:
            carly.energy = max(0, carly.energy - 2)
            carly.satiety = max(0, carly.satiety - 3)
            fields.extend(("energy", "satiety"))
        if fields:
            carly.version += 1
            fields.extend(("version", "updated_at"))
            carly.save(update_fields=tuple(set(fields)))
            changed += 1
    return changed
