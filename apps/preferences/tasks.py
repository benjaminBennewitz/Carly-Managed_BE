# apps/preferences/tasks.py
"""Pflegt Carlys zeitabhängigen Zustand in einem täglichen Hintergrundlauf."""

from celery import shared_task
from django.utils import timezone

from apps.preferences.models import CarlyState
from apps.preferences.rewards import apply_carly_decay


@shared_task
def refresh_carly_streaks() -> int:
    """Setzt unterbrochene Streaks zurück und synchronisiert den zeitbasierten Decay."""
    today = timezone.localdate()
    changed = 0
    for carly in CarlyState.objects.iterator(chunk_size=500):
        decay_changed = apply_carly_decay(carly)
        streak_changed = bool(
            carly.last_productive_day
            and (today - carly.last_productive_day).days > 1
            and carly.streak
        )
        if streak_changed:
            carly.streak = 0
            carly.version += 1
            carly.save(update_fields=("streak", "version", "updated_at"))
        if decay_changed or streak_changed:
            changed += 1
    return changed
