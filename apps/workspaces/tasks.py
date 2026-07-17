# apps/workspaces/tasks.py
"""Führt zeitgesteuerte Wiederholungen und Einladungsbereinigung aus."""

from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.workspaces.choices import InvitationStatus
from apps.workspaces.models import Task, TaskRecurrenceRule, WorkspaceInvitation
from apps.workspaces.services import calculate_next_run


@shared_task
def run_due_recurrences() -> int:
    """Erzeugt fällige Task-Kopien idempotent unter Zeilensperren."""
    today = timezone.localdate()
    processed = 0
    rule_ids = list(
        TaskRecurrenceRule.objects.filter(is_active=True, next_run_on__lte=today).values_list(
            "id", flat=True
        )
    )
    for rule_id in rule_ids:
        with transaction.atomic():
            rule = (
                TaskRecurrenceRule.objects.select_for_update(skip_locked=True)
                .select_related(
                    "task", "task__board", "task__column", "task__owner", "task__assignee"
                )
                .filter(pk=rule_id, is_active=True, next_run_on__lte=today)
                .first()
            )
            if rule is None:
                continue
            template = rule.task
            clone = Task.objects.create(
                workspace=template.workspace,
                board=template.board,
                column=template.column,
                project=template.project,
                owner=template.owner,
                assignee=template.assignee,
                title=template.title,
                description=template.description,
                priority=template.priority,
                start_date=rule.next_run_on,
                due_date=rule.next_run_on,
                due_time=template.due_time,
                tags=template.tags,
                position=template.position + 1,
            )
            clone.collaborators.set(template.collaborators.all())
            rule.last_run_at = timezone.now()
            rule.next_run_on = calculate_next_run(rule, rule.next_run_on + timedelta(days=1))
            rule.version += 1
            rule.save(update_fields=("last_run_at", "next_run_on", "version", "updated_at"))
            processed += 1
    return processed


@shared_task
def expire_invitations() -> int:
    """Markiert nicht mehr nutzbare Einladungen explizit als abgelaufen."""
    return WorkspaceInvitation.objects.filter(
        status=InvitationStatus.PENDING,
        expires_at__lte=timezone.now(),
    ).update(status=InvitationStatus.EXPIRED, updated_at=timezone.now())
