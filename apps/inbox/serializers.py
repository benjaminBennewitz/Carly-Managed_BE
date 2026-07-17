# apps/inbox/serializers.py
"""Bildet Inbox-Modelle auf die Angular-Datenverträge ab."""

from typing import Any

from rest_framework import serializers

from apps.accounts.models import User
from apps.inbox.models import ChatMessage, Conversation, SystemNotification
from apps.workspaces.models import WorkspaceMembership
from apps.workspaces.serializers import WorkspaceMemberSerializer


class InboxMemberMixin:
    """Serialisiert Nutzer im Kontext des jeweiligen Workspaces."""

    def member_data(self, user: User | None, workspace_id: Any) -> dict[str, Any] | None:
        """Liefert die Mitgliedsdarstellung oder null."""
        if user is None:
            return None
        membership = (
            WorkspaceMembership.objects.select_related("user")
            .filter(workspace_id=workspace_id, user=user, is_active=True)
            .first()
        )
        return (
            WorkspaceMemberSerializer(membership, context=self.context).data if membership else None
        )


class SystemNotificationSerializer(
    InboxMemberMixin, serializers.ModelSerializer[SystemNotification]
):
    """Entspricht dem WorkspaceSystemNotification-Interface."""

    actor = serializers.SerializerMethodField()
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    isRead = serializers.SerializerMethodField()
    queryParams = serializers.JSONField(source="query_params")

    class Meta:
        model = SystemNotification
        fields = (
            "id",
            "kind",
            "title",
            "body",
            "icon",
            "actor",
            "createdAt",
            "isRead",
            "route",
            "queryParams",
        )

    def get_actor(self, obj: SystemNotification) -> dict[str, Any] | None:
        """Liefert den optionalen Auslöser."""
        return self.member_data(obj.actor, obj.workspace_id) if obj.workspace_id else None

    def get_isRead(self, obj: SystemNotification) -> bool:
        """Leitet den Lesestatus aus dem Zeitstempel ab."""
        return obj.read_at is not None

    def to_representation(self, instance: SystemNotification) -> dict[str, Any]:
        """Wandelt leere optionale Werte in null um."""
        data = super().to_representation(instance)
        data["route"] = data["route"] or None
        data["queryParams"] = data["queryParams"] or None
        return data


class ChatMessageSerializer(InboxMemberMixin, serializers.ModelSerializer[ChatMessage]):
    """Entspricht dem WorkspaceChatMessage-Interface."""

    sender = serializers.SerializerMethodField()
    subject = serializers.SerializerMethodField()
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = ChatMessage
        fields = ("id", "kind", "sender", "subject", "body", "createdAt")

    def get_sender(self, obj: ChatMessage) -> dict[str, Any] | None:
        """Liefert den optionalen Absender."""
        return self.member_data(obj.sender, obj.conversation.workspace_id)

    def get_subject(self, obj: ChatMessage) -> str | None:
        """Wandelt einen leeren Betreff in null um."""
        return obj.subject or None


class ConversationSerializer(InboxMemberMixin, serializers.ModelSerializer[Conversation]):
    """Entspricht dem WorkspaceConversation-Interface."""

    participants = serializers.SerializerMethodField()
    messages = serializers.SerializerMethodField()
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)
    unreadCount = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = (
            "id",
            "participants",
            "messages",
            "createdAt",
            "updatedAt",
            "unreadCount",
            "version",
        )

    def get_participants(self, obj: Conversation) -> list[dict[str, Any]]:
        """Liefert aktive Gesprächsteilnehmende."""
        users = [link.user for link in obj.participant_links.all() if link.left_at is None]
        return [self.member_data(user, obj.workspace_id) for user in users]

    def get_messages(self, obj: Conversation) -> list[dict[str, Any]]:
        """Filtert gelöschte Nachrichten aus."""
        messages = [message for message in obj.messages.all() if message.deleted_at is None]
        return ChatMessageSerializer(messages, many=True, context=self.context).data

    def get_unreadCount(self, obj: Conversation) -> int:
        """Zählt Nachrichten nach dem persönlichen Lesestand."""
        request = self.context.get("request")
        if not request:
            return 0
        link = next(
            (item for item in obj.participant_links.all() if item.user_id == request.user.id), None
        )
        if link is None:
            return 0
        queryset = obj.messages.filter(deleted_at__isnull=True).exclude(sender=request.user)
        if link.last_read_at:
            queryset = queryset.filter(created_at__gt=link.last_read_at)
        return queryset.count()


class ConversationCreateSerializer(serializers.Serializer[dict[str, Any]]):
    """Validiert neue Gespräche und die erste Nachricht."""

    workspaceId = serializers.UUIDField()
    participantIds = serializers.PrimaryKeyRelatedField(
        source="participants", queryset=User.objects.all(), many=True, allow_empty=False
    )
    subject = serializers.CharField(min_length=1, max_length=160)
    body = serializers.CharField(min_length=1, max_length=5000)


class MessageCreateSerializer(serializers.Serializer[dict[str, Any]]):
    """Validiert eine neue Chatnachricht."""

    subject = serializers.CharField(max_length=160, allow_blank=True, required=False)
    body = serializers.CharField(min_length=1, max_length=5000)


class ParticipantsSerializer(serializers.Serializer[dict[str, Any]]):
    """Validiert eine Liste zu ändernder Gesprächsteilnehmender."""

    participantIds = serializers.PrimaryKeyRelatedField(
        source="participants", queryset=User.objects.all(), many=True, allow_empty=False
    )
    version = serializers.IntegerField(min_value=1)
