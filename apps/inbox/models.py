# apps/inbox/models.py
"""Definiert Benachrichtigungen, Gespräche und Chatnachrichten."""

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.common.models import TimeStampedModel, UUIDModel, VersionedModel
from apps.common.validators import reject_control_characters, validate_material_icon
from apps.workspaces.models import Workspace


class NotificationKind(models.TextChoices):
    """Spiegelt die Inbox-Kategorien des Frontends."""

    TASK = "task", "Task"
    PROJECT = "project", "Projekt"
    MEMBER = "member", "Mitglied"
    AUTOMATION = "automation", "Automation"
    SYSTEM = "system", "System"


class SystemNotification(UUIDModel, TimeStampedModel):
    """Speichert eine persönliche, optionale Systembenachrichtigung."""

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="system_notifications",
    )
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="system_notifications",
        blank=True,
        null=True,
    )
    kind = models.CharField(max_length=16, choices=NotificationKind.choices)
    title = models.CharField(max_length=160, validators=[reject_control_characters])
    body = models.TextField(max_length=2000, validators=[reject_control_characters])
    icon = models.CharField(max_length=50, validators=[validate_material_icon])
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="triggered_system_notifications",
        blank=True,
        null=True,
    )
    route = models.CharField(
        max_length=300, blank=True, default="", validators=[reject_control_characters]
    )
    query_params = models.JSONField(default=dict, blank=True)
    read_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("recipient", "read_at", "created_at"), name="notification_recipient_idx"
            ),
        ]


class Conversation(UUIDModel, TimeStampedModel, VersionedModel):
    """Bündelt ein direktes oder gruppenbezogenes Gespräch."""

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="conversations")
    participants = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="ConversationParticipant",
        related_name="conversations",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_conversations",
    )

    class Meta:
        ordering = ("-updated_at",)


class ConversationParticipant(UUIDModel, TimeStampedModel):
    """Speichert Lesestand und aktive Teilnahme eines Gesprächs."""

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="participant_links"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="conversation_links",
    )
    last_read_at = models.DateTimeField(blank=True, null=True)
    left_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("conversation", "user"), name="conversation_participant_unique"
            ),
        ]
        indexes = [
            models.Index(fields=("user", "left_at"), name="conversation_user_active_idx"),
        ]


class ChatMessageKind(models.TextChoices):
    """Unterscheidet Nutzertexte von serverseitigen Hinweisen."""

    MESSAGE = "message", "Nachricht"
    SYSTEM = "system", "System"


class ChatMessage(UUIDModel, TimeStampedModel, VersionedModel):
    """Speichert eine unveränderliche Gesprächsnachricht."""

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    kind = models.CharField(
        max_length=16, choices=ChatMessageKind.choices, default=ChatMessageKind.MESSAGE
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="sent_chat_messages",
        blank=True,
        null=True,
    )
    subject = models.CharField(
        max_length=160, blank=True, default="", validators=[reject_control_characters]
    )
    body = models.TextField(max_length=5000, validators=[reject_control_characters])
    deleted_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ("created_at",)
        indexes = [
            models.Index(fields=("conversation", "created_at"), name="chat_conversation_time_idx")
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(kind=ChatMessageKind.SYSTEM, sender__isnull=True)
                | Q(kind=ChatMessageKind.MESSAGE, sender__isnull=False),
                name="chat_message_sender_consistent",
            )
        ]
