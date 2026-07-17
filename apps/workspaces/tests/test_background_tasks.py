# apps/workspaces/tests/test_background_tasks.py
"""Prüft wiederkehrende Tasks und zeitgesteuerte Wartungsoperationen."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.preferences.models import CarlyState
from apps.preferences.tasks import refresh_carly_streaks
from apps.workspaces.choices import InvitationStatus, RecurrenceScheduleType
from apps.workspaces.models import Board, Task, TaskRecurrenceRule, WorkspaceInvitation
from apps.workspaces.services import bootstrap_personal_workspace
from apps.workspaces.tasks import expire_invitations, run_due_recurrences

pytestmark = pytest.mark.django_db


def create_context() -> tuple[User, Board]:
    """Erstellt einen vollständigen persönlichen Testkontext."""
    user = User.objects.create_user(
        email="jobs@example.test",
        password="Fokus!Board-2026-sicher",
        display_name="Job Test",
        privacy_acknowledged_at=timezone.now(),
    )
    bootstrap_personal_workspace(user)
    return user, Board.objects.get(owner=user)


def test_due_recurrence_creates_exactly_one_task_clone() -> None:
    """Erzeugt eine fällige Kopie und verschiebt den nächsten Lauf."""
    user, board = create_context()
    today = timezone.localdate()
    template = Task.objects.create(
        workspace=board.workspace,
        board=board,
        column=board.columns.first(),
        owner=user,
        title="Wöchentlicher Bericht",
        tags=["Reporting"],
    )
    rule = TaskRecurrenceRule.objects.create(
        task=template,
        schedule_type=RecurrenceScheduleType.INTERVAL_DAYS,
        start_date=today,
        interval_value=7,
        next_run_on=today,
    )

    assert run_due_recurrences() == 1

    clones = Task.objects.filter(board=board).exclude(pk=template.pk)
    assert clones.count() == 1
    assert clones.get().title == template.title
    rule.refresh_from_db()
    assert rule.next_run_on == today + timedelta(days=7)
    assert rule.last_run_at is not None


def test_expired_invitations_are_marked_explicitly() -> None:
    """Ändert nur abgelaufene offene Einladungen."""
    user, board = create_context()
    expired = WorkspaceInvitation.objects.create(
        workspace=board.workspace,
        invited_by=user,
        email="expired@example.test",
        token_hash="a" * 64,
        expires_at=timezone.now() - timedelta(minutes=1),
    )
    active = WorkspaceInvitation.objects.create(
        workspace=board.workspace,
        invited_by=user,
        email="active@example.test",
        token_hash="b" * 64,
        expires_at=timezone.now() + timedelta(days=1),
    )

    assert expire_invitations() == 1
    expired.refresh_from_db()
    active.refresh_from_db()
    assert expired.status == InvitationStatus.EXPIRED
    assert active.status == InvitationStatus.PENDING


def test_daily_carly_refresh_resets_streak_and_reduces_passive_values() -> None:
    """Pflegt zeitabhängige Carly-Werte ohne negative Ergebnisse."""
    user, _ = create_context()
    carly = CarlyState.objects.get(user=user)
    carly.streak = 5
    carly.energy = 1
    carly.satiety = 2
    carly.last_productive_day = timezone.localdate() - timedelta(days=2)
    carly.save()

    assert refresh_carly_streaks() == 1

    carly.refresh_from_db()
    assert carly.streak == 0
    assert carly.energy == 0
    assert carly.satiety == 0
    assert carly.version == 2
