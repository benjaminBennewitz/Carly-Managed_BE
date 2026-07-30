# apps/inbox/services.py
"""Kapselt Nachrichtenerstellung und persönliche Benachrichtigungen."""

from collections.abc import Iterable
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.inbox.models import ChatMessage, Conversation, ConversationParticipant, SystemNotification
from apps.preferences.rewards import award_carly_reward_safely
from apps.workspaces.models import Workspace, WorkspaceMembership


def _broadcast_inbox(user_ids: Iterable[Any], event_type: str, payload: dict[str, Any]) -> None:
    """Sendet Inbox-Ereignisse erst nach erfolgreichem Commit."""
    from apps.realtime.events import broadcast_inbox_event

    ids = [str(user_id) for user_id in user_ids]
    transaction.on_commit(lambda: broadcast_inbox_event(ids, event_type, payload))


@transaction.atomic
def create_notification(
    *,
    recipient: User,
    kind: str,
    title: str,
    body: str,
    icon: str,
    workspace: Workspace | None = None,
    actor: User | None = None,
    route: str = "",
    query_params: dict[str, str] | None = None,
) -> SystemNotification:
    """Erstellt und verteilt eine persönliche Systembenachrichtigung."""
    notification = SystemNotification.objects.create(
        recipient=recipient,
        workspace=workspace,
        kind=kind,
        title=title,
        body=body,
        icon=icon,
        actor=actor,
        route=route,
        query_params=query_params or {},
    )
    _broadcast_inbox(
        [recipient.id], "notification.created", {"notificationId": str(notification.id)}
    )
    return notification


@transaction.atomic
def create_conversation(
    *,
    workspace: Workspace,
    creator: User,
    participants: list[User],
    subject: str,
    body: str,
) -> Conversation:
    """Erstellt ein Gespräch einschließlich Eröffnungsnachricht."""
    unique_users = {user.id: user for user in [creator, *participants]}
    active_ids = set(
        WorkspaceMembership.objects.filter(
            workspace=workspace, user_id__in=unique_users, is_active=True
        ).values_list("user_id", flat=True)
    )
    if set(unique_users) != active_ids:
        raise ValidationError("Alle Teilnehmenden müssen aktive Workspace-Mitglieder sein.")
    conversation = Conversation.objects.create(workspace=workspace, created_by=creator)
    ConversationParticipant.objects.bulk_create(
        [
            ConversationParticipant(
                conversation=conversation,
                user=user,
                last_read_at=timezone.now() if user.id == creator.id else None,
            )
            for user in unique_users.values()
        ]
    )
    repeated_recently = ChatMessage.objects.filter(
        sender=creator,
        body=body,
        created_at__gte=timezone.now() - timedelta(minutes=2),
    ).exists()
    message = ChatMessage.objects.create(
        conversation=conversation, sender=creator, subject=subject, body=body
    )
    if not repeated_recently:
        award_carly_reward_safely(
            user=creator,
            event_type="message_sent",
            event_key=f"message-sent:{message.id}",
            source_type="message",
            source_id=str(message.id),
        )
    _broadcast_inbox(unique_users, "conversation.created", {"conversationId": str(conversation.id)})
    return conversation


@transaction.atomic
def send_message(
    *, conversation: Conversation, sender: User, subject: str, body: str
) -> ChatMessage:
    """Speichert eine Nachricht und aktualisiert den Gesprächszeitpunkt."""
    link = ConversationParticipant.objects.filter(
        conversation=conversation, user=sender, left_at__isnull=True
    ).first()
    if link is None:
        raise ValidationError("Du nimmst nicht mehr an diesem Gespräch teil.")
    message = ChatMessage.objects.create(
        conversation=conversation, sender=sender, subject=subject, body=body
    )
    conversation.version += 1
    conversation.save(update_fields=("version", "updated_at"))
    link.last_read_at = timezone.now()
    link.save(update_fields=("last_read_at", "updated_at"))
    recipient_ids = conversation.participant_links.filter(left_at__isnull=True).values_list(
        "user_id", flat=True
    )
    _broadcast_inbox(
        recipient_ids,
        "message.created",
        {
            "conversationId": str(conversation.id),
            "messageId": str(message.id),
            "version": conversation.version,
        },
    )
    repeated_recently = ChatMessage.objects.filter(
        sender=sender,
        body=body,
        created_at__gte=timezone.now() - timedelta(minutes=2),
    ).exclude(pk=message.pk).exists()
    if not repeated_recently:
        award_carly_reward_safely(
            user=sender,
            event_type="message_sent",
            event_key=f"message-sent:{message.id}",
            source_type="message",
            source_id=str(message.id),
        )
    return message
