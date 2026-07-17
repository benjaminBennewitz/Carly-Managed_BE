# apps/inbox/admin.py
"""Registriert Inbox-Daten für Support und Moderation."""

from django.contrib import admin

from apps.inbox.models import (
    ChatMessage,
    Conversation,
    ConversationParticipant,
    SystemNotification,
)


class ReadOnlyTimestampAdmin(admin.ModelAdmin):
    """Markiert technische Schlüssel und Zeitstempel als schreibgeschützt."""

    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(SystemNotification)
class SystemNotificationAdmin(ReadOnlyTimestampAdmin):
    """Konfiguriert die Übersicht strukturierter Benachrichtigungen."""

    list_display = ("title", "recipient", "kind", "read_at", "created_at")
    list_filter = ("kind", "read_at")
    search_fields = ("title", "message", "recipient__email")
    list_select_related = ("recipient", "workspace")


@admin.register(Conversation)
class ConversationAdmin(ReadOnlyTimestampAdmin):
    """Zeigt Gesprächsmetadaten und Versionsstände."""

    list_display = ("id", "workspace", "created_by", "version", "updated_at")
    search_fields = ("workspace__name", "created_by__email", "created_by__display_name")
    list_select_related = ("workspace", "created_by")


@admin.register(ChatMessage)
class ChatMessageAdmin(ReadOnlyTimestampAdmin):
    """Ermöglicht Moderation und Fehleranalyse bei Nachrichten."""

    list_display = ("conversation", "sender", "created_at", "deleted_at")
    list_filter = ("deleted_at",)
    search_fields = ("body", "subject", "sender__email")
    list_select_related = ("conversation", "sender")


admin.site.register(ConversationParticipant, ReadOnlyTimestampAdmin)
