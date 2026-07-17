# apps/workspaces/admin.py
"""Registriert die Workspace-Domäne für eine sichere Administration."""

from django.contrib import admin

from apps.workspaces.models import (
    AutomationRule,
    Board,
    BoardColumn,
    Project,
    ProjectParticipant,
    ProjectPreference,
    Subtask,
    Task,
    TaskAttachment,
    TaskComment,
    TaskHistoryEntry,
    TaskRecurrenceRule,
    Workspace,
    WorkspaceInvitation,
    WorkspaceJoinRequest,
    WorkspaceMembership,
)


class ReadOnlyTimestampAdmin(admin.ModelAdmin):
    """Schützt technische Identifikatoren und Zeitstempel vor Änderungen."""

    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Workspace)
class WorkspaceAdmin(ReadOnlyTimestampAdmin):
    """Konfiguriert die Workspace-Übersicht."""

    list_display = ("name", "owner", "allow_invites", "version", "updated_at")
    search_fields = ("name", "owner__email", "owner__display_name")
    list_select_related = ("owner",)


@admin.register(WorkspaceMembership)
class WorkspaceMembershipAdmin(ReadOnlyTimestampAdmin):
    """Zeigt Rollen und aktive Mitgliedschaften kompakt an."""

    list_display = ("workspace", "user", "role", "is_active", "updated_at")
    list_filter = ("role", "is_active")
    search_fields = ("workspace__name", "user__email", "user__display_name")
    list_select_related = ("workspace", "user")


@admin.register(Project)
class ProjectAdmin(ReadOnlyTimestampAdmin):
    """Stellt Projektstatus und Termine für Supportfälle bereit."""

    list_display = ("name", "workspace", "status", "owner", "due_at", "version")
    list_filter = ("status", "allows_on_demand_tasks")
    search_fields = ("name", "description", "workspace__name", "owner__email")
    list_select_related = ("workspace", "owner")


@admin.register(Board)
class BoardAdmin(ReadOnlyTimestampAdmin):
    """Zeigt persönliche und projektbezogene Boards."""

    list_display = ("title", "workspace", "kind", "project", "owner", "version")
    list_filter = ("kind",)
    search_fields = ("title", "workspace__name", "project__name", "owner__email")
    list_select_related = ("workspace", "project", "owner")


@admin.register(BoardColumn)
class BoardColumnAdmin(ReadOnlyTimestampAdmin):
    """Ermöglicht die Diagnose von Boardspalten."""

    list_display = ("title", "board", "position", "system_role", "version")
    list_filter = ("is_fixed_position", "is_dynamic", "system_role")
    search_fields = ("title", "board__title")
    list_select_related = ("board",)


@admin.register(Task)
class TaskAdmin(ReadOnlyTimestampAdmin):
    """Stellt zentrale Task-Daten ohne private Dateiinhalte dar."""

    list_display = (
        "title",
        "workspace",
        "project",
        "assignee",
        "priority",
        "is_done",
        "due_date",
        "version",
    )
    list_filter = ("priority", "is_done", "is_shared_pool", "requires_review")
    search_fields = ("title", "description", "owner__email", "assignee__email")
    list_select_related = ("workspace", "project", "owner", "assignee")
    raw_id_fields = ("parent_task", "source_task", "source_subtask")


@admin.register(TaskAttachment)
class TaskAttachmentAdmin(ReadOnlyTimestampAdmin):
    """Zeigt nur Metadaten privater Anhänge."""

    list_display = ("original_name", "task", "mime_type", "size_bytes", "uploaded_by")
    search_fields = ("original_name", "task__title", "uploaded_by__email")
    list_select_related = ("task", "uploaded_by")


@admin.register(WorkspaceInvitation)
class WorkspaceInvitationAdmin(ReadOnlyTimestampAdmin):
    """Erlaubt Support bei Einladungen ohne Klartext-Tokens."""

    list_display = ("email", "workspace", "project", "status", "expires_at")
    list_filter = ("status",)
    search_fields = ("email", "workspace__name", "project__name")
    exclude = ("token_hash",)


admin.site.register(ProjectParticipant, ReadOnlyTimestampAdmin)
admin.site.register(ProjectPreference, ReadOnlyTimestampAdmin)
admin.site.register(Subtask, ReadOnlyTimestampAdmin)
admin.site.register(TaskComment, ReadOnlyTimestampAdmin)
admin.site.register(TaskHistoryEntry, ReadOnlyTimestampAdmin)
admin.site.register(TaskRecurrenceRule, ReadOnlyTimestampAdmin)
admin.site.register(AutomationRule, ReadOnlyTimestampAdmin)
admin.site.register(WorkspaceJoinRequest, ReadOnlyTimestampAdmin)
