# apps/demo/tasks.py
"""Automatisiert den periodischen Reset des öffentlichen Demo-Workspaces."""

from celery import shared_task
from django.conf import settings

from apps.accounts.models import User
from apps.demo.services import reset_public_demo_account


@shared_task(ignore_result=True)
def reset_public_demo_data() -> None:
    """Setzt den konfigurierten Demo-Workspace nur bei expliziter Freigabe zurück."""
    if not settings.DEMO_AUTO_RESET_ENABLED or not settings.DEMO_DATA_RESET_ENABLED:
        return
    if not settings.DEBUG and not settings.DEMO_DATA_RESET_ALLOW_PRODUCTION:
        return
    if not settings.DEMO_OWNER_EMAIL:
        return

    owner = User.objects.filter(
        email__iexact=settings.DEMO_OWNER_EMAIL,
        is_active=True,
    ).first()
    if owner is None:
        return
    reset_public_demo_account(owner=owner)
