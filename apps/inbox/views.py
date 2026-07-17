# apps/inbox/views.py
"""Stellt persönliche Inbox- und Gesprächsendpunkte bereit."""

from typing import Any

from django.db import transaction
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.inbox.models import Conversation, ConversationParticipant, SystemNotification
from apps.inbox.serializers import (
    ConversationCreateSerializer,
    ConversationSerializer,
    MessageCreateSerializer,
    ParticipantsSerializer,
    SystemNotificationSerializer,
)
from apps.inbox.services import create_conversation, send_message
from apps.workspaces.models import WorkspaceMembership
from apps.workspaces.selectors import workspaces_for_user
from apps.workspaces.services import assert_version, increment_version


class NotificationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet[SystemNotification],
):
    """Listet, liest und entfernt persönliche Systembenachrichtigungen."""

    queryset = SystemNotification.objects.none()
    serializer_class = SystemNotificationSerializer

    def get_queryset(self):
        """Liefert ausschließlich Benachrichtigungen des aktuellen Nutzers."""
        queryset = SystemNotification.objects.filter(recipient=self.request.user).select_related(
            "actor", "workspace"
        )
        if self.request.query_params.get("unread") == "true":
            queryset = queryset.filter(read_at__isnull=True)
        return queryset

    @action(detail=True, methods=["post"], url_path="mark-read")
    def mark_read(self, request: Any, pk: str | None = None) -> Response:
        """Markiert eine Benachrichtigung als gelesen."""
        notification = self.get_object()
        if notification.read_at is None:
            notification.read_at = timezone.now()
            notification.save(update_fields=("read_at", "updated_at"))
        return Response(self.get_serializer(notification).data)

    @action(detail=False, methods=["post"], url_path="mark-all-read")
    def mark_all_read(self, request: Any) -> Response:
        """Markiert alle offenen Benachrichtigungen als gelesen."""
        self.get_queryset().filter(read_at__isnull=True).update(
            read_at=timezone.now(), updated_at=timezone.now()
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["delete"], url_path="clear")
    def clear(self, request: Any) -> Response:
        """Löscht alle persönlichen Systembenachrichtigungen."""
        self.get_queryset().delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ConversationViewSet(viewsets.ModelViewSet[Conversation]):
    """Verwaltet Gespräche ausschließlich für aktive Teilnehmende."""

    queryset = Conversation.objects.none()
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        """Lädt Gespräche mit Nachrichten, Teilnehmenden und Leseständen."""
        return (
            Conversation.objects.filter(
                participant_links__user=self.request.user, participant_links__left_at__isnull=True
            )
            .prefetch_related("participant_links__user", "messages__sender")
            .distinct()
        )

    def get_serializer_class(self):
        """Trennt die Gesprächserstellung von der Ausgabe."""
        return ConversationCreateSerializer if self.action == "create" else ConversationSerializer

    def create(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """Erstellt ein Gespräch in einem zugänglichen Workspace."""
        serializer = ConversationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        workspace = (
            workspaces_for_user(request.user)
            .filter(pk=serializer.validated_data["workspaceId"])
            .first()
        )
        if workspace is None:
            raise NotFound("Workspace nicht gefunden.")
        conversation = create_conversation(
            workspace=workspace,
            creator=request.user,
            participants=serializer.validated_data["participants"],
            subject=serializer.validated_data["subject"],
            body=serializer.validated_data["body"],
        )
        conversation = self.get_queryset().get(pk=conversation.pk)
        return Response(
            ConversationSerializer(conversation, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    def retrieve(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """Liest das Gespräch und aktualisiert den persönlichen Lesestand."""
        conversation = self.get_object()
        ConversationParticipant.objects.filter(conversation=conversation, user=request.user).update(
            last_read_at=timezone.now(), updated_at=timezone.now()
        )
        return Response(ConversationSerializer(conversation, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def messages(self, request: Any, pk: str | None = None) -> Response:
        """Sendet eine neue Nachricht in das Gespräch."""
        conversation = self.get_object()
        serializer = MessageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        send_message(
            conversation=conversation,
            sender=request.user,
            subject=serializer.validated_data.get("subject", ""),
            body=serializer.validated_data["body"],
        )
        refreshed = self.get_queryset().get(pk=conversation.pk)
        return Response(
            ConversationSerializer(refreshed, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post", "delete"], url_path="participants")
    def participants(self, request: Any, pk: str | None = None) -> Response:
        """Fügt Teilnehmende hinzu oder entfernt sie unter Versionskontrolle."""
        conversation = self.get_object()
        if conversation.created_by_id != request.user.id:
            raise PermissionDenied("Nur die erstellende Person darf Teilnehmende ändern.")
        serializer = ParticipantsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            locked = Conversation.objects.select_for_update().get(pk=conversation.pk)
            assert_version(locked, serializer.validated_data["version"])
            users = serializer.validated_data["participants"]
            active_ids = set(
                WorkspaceMembership.objects.filter(
                    workspace=locked.workspace, user__in=users, is_active=True
                ).values_list("user_id", flat=True)
            )
            if any(user.id not in active_ids for user in users):
                raise ValidationError("Teilnehmende müssen aktive Workspace-Mitglieder sein.")
            if request.method == "POST":
                for user in users:
                    ConversationParticipant.objects.update_or_create(
                        conversation=locked, user=user, defaults={"left_at": None}
                    )
            else:
                if any(user.id == request.user.id for user in users):
                    raise ValidationError(
                        "Die erstellende Person kann sich nicht selbst entfernen."
                    )
                ConversationParticipant.objects.filter(conversation=locked, user__in=users).update(
                    left_at=timezone.now(), updated_at=timezone.now()
                )
            increment_version(locked)
            locked.save(update_fields=("version", "updated_at"))
        refreshed = self.get_queryset().get(pk=conversation.pk)
        return Response(ConversationSerializer(refreshed, context={"request": request}).data)

    def destroy(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """Verlässt ein Gespräch, statt es für andere zu löschen."""
        conversation = self.get_object()
        ConversationParticipant.objects.filter(conversation=conversation, user=request.user).update(
            left_at=timezone.now(), updated_at=timezone.now()
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
