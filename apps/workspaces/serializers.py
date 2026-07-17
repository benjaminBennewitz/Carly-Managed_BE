# apps/workspaces/serializers.py
"""Bildet die Angular-Datenverträge auf validierte Django-Modelle ab."""

from typing import Any

from django.utils import timezone
from rest_framework import serializers

from apps.accounts.models import User
from apps.common.validators import reject_control_characters
from apps.workspaces.choices import (
    ProjectRole,
    RecurrenceScheduleType,
    WorkspaceRole,
)
from apps.workspaces.models import (
    AutomationRule,
    Board,
    BoardColumn,
    Project,
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

WEEKDAY_LABELS = {
    "MO": "Mo",
    "TU": "Di",
    "WE": "Mi",
    "TH": "Do",
    "FR": "Fr",
    "SA": "Sa",
    "SU": "So",
}


def _initials(display_name: str) -> str:
    """Erzeugt höchstens zwei robuste Initialen."""
    parts = [part for part in display_name.split() if part]
    if not parts:
        return "?"
    return "".join(part[0].upper() for part in parts[:2])


def _contrast_text(color: str) -> str:
    """Wählt anhand der relativen Helligkeit schwarze oder weiße Schrift."""
    try:
        red, green, blue = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    except (ValueError, IndexError):
        return "#ffffff"
    luminance = (0.299 * red + 0.587 * green + 0.114 * blue) / 255
    return "#111111" if luminance > 0.58 else "#ffffff"


class WorkspaceMemberSerializer(serializers.ModelSerializer[WorkspaceMembership]):
    """Entspricht dem WorkspaceMember-Interface des Frontends."""

    id = serializers.UUIDField(source="user.id", read_only=True)
    fullName = serializers.CharField(source="user.display_name", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    initials = serializers.SerializerMethodField()
    avatarColor = serializers.CharField(source="avatar_color")
    avatarTextColor = serializers.SerializerMethodField()
    isOnline = serializers.SerializerMethodField()

    class Meta:
        model = WorkspaceMembership
        fields = (
            "id",
            "fullName",
            "email",
            "initials",
            "avatarColor",
            "avatarTextColor",
            "role",
            "isOnline",
        )

    def get_initials(self, obj: WorkspaceMembership) -> str:
        """Leitet Initialen aus dem Anzeigenamen ab."""
        return _initials(obj.user.display_name)

    def get_avatarTextColor(self, obj: WorkspaceMembership) -> str:
        """Berechnet eine kontrastreiche Avatar-Schriftfarbe."""
        return _contrast_text(obj.avatar_color)

    def get_isOnline(self, obj: WorkspaceMembership) -> bool:
        """Überlässt den echten Online-Status bewusst dem WebSocket-Kanal."""
        online_ids = self.context.get("online_user_ids", set())
        return str(obj.user_id) in online_ids


class MemberLookupMixin:
    """Stellt verschachtelte Mitgliedsdaten mit Request-lokalem Cache bereit."""

    def member_data(self, user: User | None, workspace_id: Any) -> dict[str, Any] | None:
        """Serialisiert einen Nutzer über dessen Workspace-Mitgliedschaft."""
        if user is None:
            return None
        cache = self.context.setdefault("membership_cache", {})
        key = (str(workspace_id), str(user.id))
        membership = cache.get(key)
        if membership is None:
            membership = (
                WorkspaceMembership.objects.select_related("user")
                .filter(
                    workspace_id=workspace_id,
                    user=user,
                    is_active=True,
                )
                .first()
            )
            cache[key] = membership
        if membership is None:
            return {
                "id": str(user.id),
                "fullName": user.display_name,
                "email": user.email,
                "initials": _initials(user.display_name),
                "avatarColor": "#6558d3",
                "avatarTextColor": "#ffffff",
                "role": WorkspaceRole.MEMBER,
                "isOnline": False,
            }
        return WorkspaceMemberSerializer(membership, context=self.context).data


class SubtaskSerializer(MemberLookupMixin, serializers.ModelSerializer[Subtask]):
    """Gibt zuweisbare Unteraufgaben im Frontendformat aus."""

    assignee = serializers.SerializerMethodField()
    isDone = serializers.BooleanField(source="is_done")
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = Subtask
        fields = ("id", "title", "assignee", "isDone", "createdAt", "version")

    def get_assignee(self, obj: Subtask) -> dict[str, Any] | None:
        """Liefert die Zuweisung als WorkspaceMember."""
        return self.member_data(obj.assignee, obj.task.workspace_id)


class CommentSerializer(MemberLookupMixin, serializers.ModelSerializer[TaskComment]):
    """Gibt nicht gelöschte Kommentare mit Autor aus."""

    author = serializers.SerializerMethodField()
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = TaskComment
        fields = ("id", "author", "body", "createdAt", "version")

    def get_author(self, obj: TaskComment) -> dict[str, Any] | None:
        """Liefert den Kommentarautor als WorkspaceMember."""
        return self.member_data(obj.author, obj.task.workspace_id)


class AttachmentSerializer(MemberLookupMixin, serializers.ModelSerializer[TaskAttachment]):
    """Gibt nur Metadaten und eine geschützte Download-URL aus."""

    fileName = serializers.CharField(source="original_name")
    mimeType = serializers.CharField(source="mime_type")
    sizeBytes = serializers.IntegerField(source="size_bytes")
    uploadedBy = serializers.SerializerMethodField()
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    downloadUrl = serializers.SerializerMethodField()

    class Meta:
        model = TaskAttachment
        fields = (
            "id",
            "fileName",
            "mimeType",
            "sizeBytes",
            "uploadedBy",
            "createdAt",
            "downloadUrl",
        )

    def get_uploadedBy(self, obj: TaskAttachment) -> dict[str, Any] | None:
        """Liefert den hochladenden Nutzer."""
        return self.member_data(obj.uploaded_by, obj.task.workspace_id)

    def get_downloadUrl(self, obj: TaskAttachment) -> str:
        """Erzeugt eine API-URL, die erneut Berechtigungen prüft."""
        request = self.context.get("request")
        path = f"/api/v1/workspaces/attachments/{obj.id}/download/"
        return request.build_absolute_uri(path) if request else path


class HistorySerializer(MemberLookupMixin, serializers.ModelSerializer[TaskHistoryEntry]):
    """Gibt nachvollziehbare Task-Aktivitäten aus."""

    actor = serializers.SerializerMethodField()
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = TaskHistoryEntry
        fields = ("id", "actor", "action", "icon", "createdAt", "metadata")

    def get_actor(self, obj: TaskHistoryEntry) -> dict[str, Any] | None:
        """Liefert die ausführende Person."""
        return self.member_data(obj.actor, obj.task.workspace_id)


class RecurrenceRuleSerializer(serializers.ModelSerializer[TaskRecurrenceRule]):
    """Entspricht dem WorkspaceTaskRecurrenceRule-Interface."""

    taskId = serializers.UUIDField(source="task_id", read_only=True)
    taskTitle = serializers.CharField(source="task.title", read_only=True)
    taskIsDone = serializers.BooleanField(source="task.is_done", read_only=True)
    boardId = serializers.UUIDField(source="task.board_id", read_only=True)
    scheduleType = serializers.CharField(source="schedule_type")
    startDate = serializers.DateField(source="start_date")
    intervalValue = serializers.IntegerField(source="interval_value")
    dayOfMonth = serializers.IntegerField(source="day_of_month", allow_null=True)
    nextRunOn = serializers.DateField(source="next_run_on", allow_null=True, read_only=True)
    lastRunAt = serializers.DateTimeField(source="last_run_at", allow_null=True, read_only=True)
    isActive = serializers.BooleanField(source="is_active")
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)
    summary = serializers.SerializerMethodField()

    class Meta:
        model = TaskRecurrenceRule
        fields = (
            "id",
            "taskId",
            "taskTitle",
            "taskIsDone",
            "boardId",
            "scheduleType",
            "startDate",
            "intervalValue",
            "weekdays",
            "dayOfMonth",
            "summary",
            "nextRunOn",
            "lastRunAt",
            "isActive",
            "createdAt",
            "updatedAt",
            "version",
        )

    def get_summary(self, obj: TaskRecurrenceRule) -> str:
        """Formuliert eine kurze deutsche Wiederholungsbeschreibung."""
        if obj.schedule_type == RecurrenceScheduleType.INTERVAL_DAYS:
            return "Täglich" if obj.interval_value == 1 else f"Alle {obj.interval_value} Tage"
        if obj.schedule_type == RecurrenceScheduleType.WEEKLY_DAYS:
            labels = [WEEKDAY_LABELS.get(day, day) for day in obj.weekdays]
            return "Wöchentlich: " + ", ".join(labels)
        return f"Monatlich am {obj.day_of_month}."

    def validate_weekdays(self, value: list[str]) -> list[str]:
        """Erlaubt ausschließlich eindeutige ISO-Wochentagskürzel."""
        allowed = set(WEEKDAY_LABELS)
        if any(day not in allowed for day in value) or len(value) != len(set(value)):
            raise serializers.ValidationError("Die Wochentage sind ungültig.")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Prüft die zum Zeitplan gehörenden Pflichtfelder."""
        schedule_type = attrs.get("schedule_type", getattr(self.instance, "schedule_type", None))
        weekdays = attrs.get("weekdays", getattr(self.instance, "weekdays", []))
        day_of_month = attrs.get("day_of_month", getattr(self.instance, "day_of_month", None))
        if schedule_type == RecurrenceScheduleType.WEEKLY_DAYS and not weekdays:
            raise serializers.ValidationError(
                {"weekdays": "Mindestens ein Wochentag ist erforderlich."}
            )
        if schedule_type == RecurrenceScheduleType.MONTHLY_DAY and day_of_month is None:
            raise serializers.ValidationError({"dayOfMonth": "Ein Monatstag ist erforderlich."})
        return attrs


class TaskSerializer(MemberLookupMixin, serializers.ModelSerializer[Task]):
    """Gibt einen vollständigen WorkspaceTask-Datensatz aus."""

    projectId = serializers.UUIDField(source="project_id", allow_null=True, read_only=True)
    projectTitle = serializers.CharField(source="project.name", allow_null=True, read_only=True)
    projectAllowsOnDemandTasks = serializers.SerializerMethodField()
    parentTaskId = serializers.UUIDField(source="parent_task_id", allow_null=True, read_only=True)
    parentTaskTitle = serializers.CharField(
        source="parent_task.title", allow_null=True, read_only=True
    )
    isSubtaskMirror = serializers.SerializerMethodField()
    sourceTaskId = serializers.UUIDField(source="source_task_id", allow_null=True, read_only=True)
    sourceSubtaskId = serializers.UUIDField(
        source="source_subtask_id", allow_null=True, read_only=True
    )
    owner = serializers.SerializerMethodField()
    assignee = serializers.SerializerMethodField()
    collaborators = serializers.SerializerMethodField()
    startDate = serializers.DateField(source="start_date", allow_null=True)
    dueDate = serializers.DateField(source="due_date", allow_null=True)
    dueTime = serializers.TimeField(source="due_time", allow_null=True, format="%H:%M")
    subtasks = SubtaskSerializer(many=True, read_only=True)
    comments = serializers.SerializerMethodField()
    attachments = AttachmentSerializer(many=True, read_only=True)
    history = HistorySerializer(many=True, read_only=True)
    subtaskCount = serializers.SerializerMethodField()
    completedSubtaskCount = serializers.SerializerMethodField()
    commentCount = serializers.SerializerMethodField()
    attachmentCount = serializers.SerializerMethodField()
    isRecurring = serializers.SerializerMethodField()
    recurrenceLabel = serializers.SerializerMethodField()
    recurrenceRule = serializers.SerializerMethodField()
    isDone = serializers.BooleanField(source="is_done")
    completedAt = serializers.DateTimeField(source="completed_at", allow_null=True, read_only=True)
    isSharedPool = serializers.BooleanField(source="is_shared_pool")
    requiresReview = serializers.BooleanField(source="requires_review")
    reviewHint = serializers.CharField(source="review_hint", allow_blank=True)
    createdOutsideColumn = serializers.BooleanField(source="created_outside_column")
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = Task
        fields = (
            "id",
            "title",
            "description",
            "projectId",
            "projectTitle",
            "projectAllowsOnDemandTasks",
            "parentTaskId",
            "parentTaskTitle",
            "isSubtaskMirror",
            "sourceTaskId",
            "sourceSubtaskId",
            "owner",
            "assignee",
            "collaborators",
            "priority",
            "startDate",
            "dueDate",
            "dueTime",
            "tags",
            "subtasks",
            "comments",
            "attachments",
            "history",
            "subtaskCount",
            "completedSubtaskCount",
            "commentCount",
            "attachmentCount",
            "isRecurring",
            "recurrenceLabel",
            "recurrenceRule",
            "isDone",
            "completedAt",
            "isSharedPool",
            "requiresReview",
            "reviewHint",
            "createdOutsideColumn",
            "createdAt",
            "updatedAt",
            "version",
        )

    def get_projectAllowsOnDemandTasks(self, obj: Task) -> bool:
        """Liefert die projektspezifische Abruf-Aufgaben-Einstellung."""
        return bool(obj.project and obj.project.allows_on_demand_tasks)

    def get_isSubtaskMirror(self, obj: Task) -> bool:
        """Erkennt persönliche Spiegelaufgaben einer Unteraufgabe."""
        return obj.source_subtask_id is not None

    def get_owner(self, obj: Task) -> dict[str, Any] | None:
        """Liefert den Task-Owner."""
        return self.member_data(obj.owner, obj.workspace_id)

    def get_assignee(self, obj: Task) -> dict[str, Any] | None:
        """Liefert die verantwortliche Person."""
        return self.member_data(obj.assignee, obj.workspace_id)

    def get_collaborators(self, obj: Task) -> list[dict[str, Any]]:
        """Liefert weitere Mitwirkende."""
        return [self.member_data(user, obj.workspace_id) for user in obj.collaborators.all()]

    def get_comments(self, obj: Task) -> list[dict[str, Any]]:
        """Filtert weich gelöschte Kommentare aus."""
        comments = [comment for comment in obj.comments.all() if comment.deleted_at is None]
        return CommentSerializer(comments, many=True, context=self.context).data

    def get_subtaskCount(self, obj: Task) -> int:
        """Zählt alle Unteraufgaben."""
        return len(obj.subtasks.all())

    def get_completedSubtaskCount(self, obj: Task) -> int:
        """Zählt erledigte Unteraufgaben."""
        return sum(1 for subtask in obj.subtasks.all() if subtask.is_done)

    def get_commentCount(self, obj: Task) -> int:
        """Zählt sichtbare Kommentare."""
        return sum(1 for comment in obj.comments.all() if comment.deleted_at is None)

    def get_attachmentCount(self, obj: Task) -> int:
        """Zählt gespeicherte Anhänge."""
        return len(obj.attachments.all())

    def get_isRecurring(self, obj: Task) -> bool:
        """Prüft eine vorhandene Wiederholungsregel ohne Fehler bei fehlender Relation."""
        return hasattr(obj, "recurrence_rule")

    def get_recurrenceLabel(self, obj: Task) -> str | None:
        """Liefert die kurze Wiederholungsbeschreibung."""
        if not hasattr(obj, "recurrence_rule"):
            return None
        return RecurrenceRuleSerializer(obj.recurrence_rule, context=self.context).data["summary"]

    def get_recurrenceRule(self, obj: Task) -> dict[str, Any] | None:
        """Liefert die vollständige Regel."""
        if not hasattr(obj, "recurrence_rule"):
            return None
        return RecurrenceRuleSerializer(obj.recurrence_rule, context=self.context).data


class TaskWriteSerializer(serializers.ModelSerializer[Task]):
    """Validiert schreibbare Task-Felder ohne verschachtelte Fremddaten."""

    id = serializers.UUIDField(required=False)
    assigneeId = serializers.PrimaryKeyRelatedField(
        source="assignee",
        queryset=User.objects.all(),
        allow_null=True,
        required=False,
    )
    collaboratorIds = serializers.PrimaryKeyRelatedField(
        source="collaborators",
        queryset=User.objects.all(),
        many=True,
        required=False,
    )
    startDate = serializers.DateField(source="start_date", allow_null=True, required=False)
    dueDate = serializers.DateField(source="due_date", allow_null=True, required=False)
    dueTime = serializers.TimeField(source="due_time", allow_null=True, required=False)
    isSharedPool = serializers.BooleanField(source="is_shared_pool", required=False)
    requiresReview = serializers.BooleanField(source="requires_review", required=False)
    reviewHint = serializers.CharField(source="review_hint", allow_blank=True, required=False)
    columnId = serializers.PrimaryKeyRelatedField(
        source="column", queryset=BoardColumn.objects.all(), allow_null=True, required=False
    )

    class Meta:
        model = Task
        fields = (
            "id",
            "title",
            "description",
            "assigneeId",
            "collaboratorIds",
            "priority",
            "startDate",
            "dueDate",
            "dueTime",
            "tags",
            "isSharedPool",
            "requiresReview",
            "reviewHint",
            "columnId",
            "version",
        )
        extra_kwargs = {"version": {"required": False}}

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Prüft Board-Zugehörigkeit, Mitgliedschaften und Datumsreihenfolge."""
        task = self.instance
        board = self.context["board"] if task is None else task.board
        workspace = board.workspace
        assignee = attrs.get("assignee", getattr(task, "assignee", None))
        collaborators = attrs.get("collaborators")
        column = attrs.get("column", getattr(task, "column", None))
        start_date = attrs.get("start_date", getattr(task, "start_date", None))
        due_date = attrs.get("due_date", getattr(task, "due_date", None))
        if column and column.board_id != board.id:
            raise serializers.ValidationError(
                {"columnId": "Die Spalte gehört nicht zu diesem Board."}
            )
        user_ids = [user.id for user in ([assignee] if assignee else [])]
        if collaborators is not None:
            user_ids.extend(user.id for user in collaborators)
        active_ids = set(
            WorkspaceMembership.objects.filter(
                workspace=workspace, user_id__in=user_ids, is_active=True
            ).values_list("user_id", flat=True)
        )
        if any(user_id not in active_ids for user_id in user_ids):
            raise serializers.ValidationError(
                "Zuweisungen sind nur an aktive Workspace-Mitglieder möglich."
            )
        if start_date and due_date and due_date < start_date:
            raise serializers.ValidationError(
                {"dueDate": "Das Fälligkeitsdatum liegt vor dem Startdatum."}
            )
        tags = attrs.get("tags")
        if tags is not None:
            if not isinstance(tags, list) or len(tags) > 20:
                raise serializers.ValidationError({"tags": "Es sind maximal 20 Labels erlaubt."})
            for tag in tags:
                if not isinstance(tag, str) or not 1 <= len(tag.strip()) <= 40:
                    raise serializers.ValidationError(
                        {"tags": "Labels müssen 1 bis 40 Zeichen lang sein."}
                    )
                reject_control_characters(tag)
            attrs["tags"] = [tag.strip() for tag in tags]
        return attrs


class BoardColumnSerializer(serializers.ModelSerializer[BoardColumn]):
    """Gibt Spalten mit vollständig serialisierten Tasks aus."""

    tasks = serializers.SerializerMethodField()
    isFixedPosition = serializers.BooleanField(source="is_fixed_position")
    sortMode = serializers.SerializerMethodField()
    isDynamic = serializers.BooleanField(source="is_dynamic")
    systemRole = serializers.SerializerMethodField()

    class Meta:
        model = BoardColumn
        fields = (
            "id",
            "title",
            "color",
            "tasks",
            "isFixedPosition",
            "sortMode",
            "isDynamic",
            "systemRole",
            "position",
            "version",
        )

    def get_tasks(self, obj: BoardColumn) -> list[dict[str, Any]]:
        """Liefert nicht archivierte Tasks in gespeicherter Reihenfolge."""
        tasks = [task for task in obj.tasks.all() if task.archived_at is None]
        return TaskSerializer(tasks, many=True, context=self.context).data

    def get_sortMode(self, obj: BoardColumn) -> str | None:
        """Wandelt den leeren Datenbankwert in null um."""
        return obj.sort_mode or None

    def get_systemRole(self, obj: BoardColumn) -> str | None:
        """Wandelt den leeren Datenbankwert in null um."""
        return obj.system_role or None


class BoardSerializer(serializers.ModelSerializer[Board]):
    """Liefert ein Board als geordneten Spalten-Snapshot."""

    columns = BoardColumnSerializer(many=True, read_only=True)
    projectId = serializers.UUIDField(source="project_id", allow_null=True, read_only=True)

    class Meta:
        model = Board
        fields = ("id", "title", "kind", "projectId", "columns", "version", "updated_at")


class ProjectSerializer(MemberLookupMixin, serializers.ModelSerializer[Project]):
    """Entspricht dem WorkspaceProject-Interface des Frontends."""

    routeKey = serializers.CharField(source="route_key")
    slugLabel = serializers.CharField(source="slug_label")
    owner = serializers.SerializerMethodField()
    managers = serializers.SerializerMethodField()
    collaborators = serializers.SerializerMethodField()
    startedAt = serializers.DateField(source="started_at")
    dueAt = serializers.DateField(source="due_at")
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)
    completedAt = serializers.DateTimeField(source="completed_at", allow_null=True, read_only=True)
    archivedAt = serializers.DateTimeField(source="archived_at", allow_null=True, read_only=True)
    lastOpenedAt = serializers.SerializerMethodField()
    isPinned = serializers.SerializerMethodField()
    allowsOnDemandTasks = serializers.BooleanField(source="allows_on_demand_tasks")
    dueState = serializers.SerializerMethodField()
    dueSummary = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = (
            "id",
            "routeKey",
            "slugLabel",
            "name",
            "description",
            "color",
            "icon",
            "status",
            "owner",
            "managers",
            "collaborators",
            "startedAt",
            "dueAt",
            "updatedAt",
            "completedAt",
            "archivedAt",
            "lastOpenedAt",
            "isPinned",
            "allowsOnDemandTasks",
            "dueState",
            "dueSummary",
            "version",
        )

    def get_owner(self, obj: Project) -> dict[str, Any] | None:
        """Liefert den Projekt-Owner."""
        return self.member_data(obj.owner, obj.workspace_id)

    def _participants(self, obj: Project, role: str) -> list[dict[str, Any]]:
        participants = [
            participant.user for participant in obj.participants.all() if participant.role == role
        ]
        return [self.member_data(user, obj.workspace_id) for user in participants]

    def get_managers(self, obj: Project) -> list[dict[str, Any]]:
        """Liefert projektbezogene Manager."""
        return self._participants(obj, ProjectRole.MANAGER)

    def get_collaborators(self, obj: Project) -> list[dict[str, Any]]:
        """Liefert projektbezogene Mitwirkende."""
        return self._participants(obj, ProjectRole.COLLABORATOR)

    def _preference(self, obj: Project) -> ProjectPreference | None:
        user = self.context.get("request").user if self.context.get("request") else None
        if not user:
            return None
        cached = self.context.setdefault("project_preferences", {})
        if obj.id not in cached:
            cached[obj.id] = ProjectPreference.objects.filter(project=obj, user=user).first()
        return cached[obj.id]

    def get_lastOpenedAt(self, obj: Project) -> str | None:
        """Liefert den nutzerspezifischen letzten Aufruf."""
        preference = self._preference(obj)
        return (
            preference.last_opened_at.isoformat()
            if preference and preference.last_opened_at
            else None
        )

    def get_isPinned(self, obj: Project) -> bool:
        """Liefert den nutzerspezifischen Pin-Zustand."""
        preference = self._preference(obj)
        return bool(preference and preference.is_pinned)

    def get_dueState(self, obj: Project) -> str:
        """Ermittelt den im Frontend verwendeten Fälligkeitszustand."""
        remaining = (obj.due_at - timezone.localdate()).days
        if remaining < 0:
            return "ueberfaellig"
        if remaining <= 2:
            return "kritisch"
        if remaining <= 7:
            return "bald-faellig"
        if remaining <= 21:
            return "im-plan"
        return "geringe-restmenge"

    def get_dueSummary(self, obj: Project) -> str:
        """Formuliert die verbleibende Zeit nutzerfreundlich."""
        remaining = (obj.due_at - timezone.localdate()).days
        if remaining < 0:
            return f"Seit {abs(remaining)} Tagen überfällig"
        if remaining == 0:
            return "Heute fällig"
        if remaining == 1:
            return "Morgen fällig"
        return f"Noch {remaining} Tage"


class ProjectWriteSerializer(serializers.ModelSerializer[Project]):
    """Validiert Projektdaten und Teilnehmer-IDs getrennt vom Ausgabevertrag."""

    id = serializers.UUIDField(required=False)
    slugLabel = serializers.CharField(
        source="slug_label", min_length=2, max_length=24, required=False
    )
    ownerId = serializers.PrimaryKeyRelatedField(
        source="owner", queryset=User.objects.all(), required=False
    )
    managerIds = serializers.PrimaryKeyRelatedField(
        source="manager_users", queryset=User.objects.all(), many=True, required=False
    )
    collaboratorIds = serializers.PrimaryKeyRelatedField(
        source="collaborator_users", queryset=User.objects.all(), many=True, required=False
    )
    startedAt = serializers.DateField(source="started_at", required=False)
    dueAt = serializers.DateField(source="due_at")
    isPinned = serializers.BooleanField(source="is_pinned_input", required=False)
    allowsOnDemandTasks = serializers.BooleanField(source="allows_on_demand_tasks", required=False)

    class Meta:
        model = Project
        fields = (
            "id",
            "name",
            "slugLabel",
            "description",
            "ownerId",
            "managerIds",
            "collaboratorIds",
            "startedAt",
            "dueAt",
            "color",
            "icon",
            "isPinned",
            "allowsOnDemandTasks",
            "version",
        )
        extra_kwargs = {
            "version": {"required": False},
            "description": {"required": False},
            "color": {"required": False},
            "icon": {"required": False},
        }

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Prüft Datumsfolge und aktive Workspace-Mitgliedschaften."""
        workspace = self.context["workspace"]
        instance = self.instance
        start = attrs.get("started_at", getattr(instance, "started_at", timezone.localdate()))
        due = attrs.get("due_at", getattr(instance, "due_at", None))
        if due and due < start:
            raise serializers.ValidationError({"dueAt": "Das Projektende liegt vor dem Start."})
        users = []
        for key in ("owner", "manager_users", "collaborator_users"):
            value = attrs.get(key)
            if value is None:
                continue
            users.extend(value if isinstance(value, list) else [value])
        active_ids = set(
            WorkspaceMembership.objects.filter(
                workspace=workspace, user__in=users, is_active=True
            ).values_list("user_id", flat=True)
        )
        if any(user.id not in active_ids for user in users):
            raise serializers.ValidationError(
                "Projektrollen sind nur für aktive Workspace-Mitglieder erlaubt."
            )
        return attrs


class WorkspaceSerializer(serializers.ModelSerializer[Workspace]):
    """Gibt Workspace-Grunddaten und die aktuelle Rolle aus."""

    currentRole = serializers.SerializerMethodField()

    class Meta:
        model = Workspace
        fields = (
            "id",
            "name",
            "allow_invites",
            "currentRole",
            "version",
            "created_at",
            "updated_at",
        )

    def get_currentRole(self, obj: Workspace) -> str | None:
        """Liefert die Rolle des anfragenden Nutzers."""
        request = self.context.get("request")
        if not request:
            return None
        membership = obj.memberships.filter(user=request.user, is_active=True).first()
        return membership.role if membership else None


class AutomationRuleSerializer(serializers.ModelSerializer[AutomationRule]):
    """Entspricht dem WorkspaceAutomationRule-Interface."""

    boardId = serializers.UUIDField(source="board_id", read_only=True)
    isActive = serializers.BooleanField(source="is_active")
    sortOrder = serializers.IntegerField(source="sort_order")
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = AutomationRule
        fields = (
            "id",
            "boardId",
            "name",
            "trigger",
            "conditions",
            "actions",
            "isActive",
            "sortOrder",
            "createdAt",
            "updatedAt",
            "version",
        )

    def validate_conditions(self, value: dict[str, Any]) -> dict[str, Any]:
        """Erlaubt nur bekannte Bedingungsschlüssel und begrenzte Texte."""
        allowed = {"taskScope", "sourceColumnId", "searchTerm", "dueDateMode"}
        if set(value) - allowed:
            raise serializers.ValidationError("Die Bedingungen enthalten unbekannte Felder.")
        search_term = str(value.get("searchTerm", ""))
        if len(search_term) > 120:
            raise serializers.ValidationError("Der Suchbegriff ist zu lang.")
        reject_control_characters(search_term)
        return value

    def validate_actions(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Begrenzt Regeln auf validierte Task-Baum-Verschiebungen."""
        if not 1 <= len(value) <= 5:
            raise serializers.ValidationError("Eine Regel benötigt ein bis fünf Aktionen.")
        for action in value:
            if set(action) != {"type", "targetColumnId"} or action.get("type") != "move_task_tree":
                raise serializers.ValidationError("Die Aktion ist nicht unterstützt.")
        return value


class InvitationSerializer(serializers.ModelSerializer[WorkspaceInvitation]):
    """Gibt Einladungsmetadaten ohne Token-Hash aus."""

    fullName = serializers.CharField(source="full_name")
    projectId = serializers.UUIDField(source="project_id", allow_null=True, read_only=True)
    invitedById = serializers.UUIDField(source="invited_by_id", read_only=True)
    expiresAt = serializers.DateTimeField(source="expires_at", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = WorkspaceInvitation
        fields = (
            "id",
            "fullName",
            "email",
            "projectId",
            "invitedById",
            "status",
            "expiresAt",
            "createdAt",
        )


class JoinRequestSerializer(MemberLookupMixin, serializers.ModelSerializer[WorkspaceJoinRequest]):
    """Entspricht der Frontenddarstellung einer Beitrittsanfrage."""

    fullName = serializers.CharField(source="user.display_name", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    avatarColor = serializers.CharField(source="avatar_color")
    requestedAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = WorkspaceJoinRequest
        fields = ("id", "fullName", "email", "avatarColor", "requestedAt", "status")


class BoardColumnWriteSerializer(serializers.ModelSerializer[BoardColumn]):
    """Validiert bearbeitbare Spaltenfelder und die Versionsnummer."""

    sortMode = serializers.ChoiceField(
        source="sort_mode", choices=("", "title", "date"), required=False
    )

    class Meta:
        model = BoardColumn
        fields = ("title", "color", "sortMode", "version")
        extra_kwargs = {"version": {"required": False}}


class SubtaskWriteSerializer(serializers.Serializer[dict[str, Any]]):
    """Validiert das Erstellen und Ändern einer Unteraufgabe."""

    id = serializers.UUIDField(required=False)
    title = serializers.CharField(min_length=1, max_length=180, required=False)
    assigneeId = serializers.PrimaryKeyRelatedField(
        source="assignee",
        queryset=User.objects.all(),
        allow_null=True,
        required=False,
    )
    isDone = serializers.BooleanField(source="is_done", required=False)
    version = serializers.IntegerField(min_value=1, required=False)


class CommentWriteSerializer(serializers.Serializer[dict[str, Any]]):
    """Validiert Kommentartext und strukturierte Erwähnungen."""

    id = serializers.UUIDField(required=False)
    body = serializers.CharField(min_length=1, max_length=5000, trim_whitespace=True)
    mentionIds = serializers.PrimaryKeyRelatedField(
        source="mentions",
        queryset=User.objects.all(),
        many=True,
        required=False,
    )


class MoveTaskSerializer(serializers.Serializer[dict[str, Any]]):
    """Validiert eine positionsbasierte Task-Verschiebung."""

    targetColumnId = serializers.PrimaryKeyRelatedField(
        source="target_column", queryset=BoardColumn.objects.all()
    )
    targetPosition = serializers.IntegerField(min_value=0)
    version = serializers.IntegerField(min_value=1)


class InvitationCreateSerializer(serializers.Serializer[dict[str, Any]]):
    """Validiert eine Einladung für Workspace oder Projekt."""

    fullName = serializers.CharField(
        source="full_name", max_length=60, allow_blank=True, required=False
    )
    email = serializers.EmailField(max_length=254)
    projectId = serializers.PrimaryKeyRelatedField(
        source="project",
        queryset=Project.objects.all(),
        allow_null=True,
        required=False,
    )

    def validate_email(self, value: str) -> str:
        """Normalisiert die Zieladresse."""
        return value.strip().lower()


class InvitationAcceptSerializer(serializers.Serializer[dict[str, Any]]):
    """Begrenzt das Klartext-Token einer Einladung."""

    token = serializers.CharField(min_length=32, max_length=256)


class ColumnReorderSerializer(serializers.Serializer[dict[str, Any]]):
    """Validiert eine vollständige, duplikatfreie Spaltenreihenfolge."""

    columnIds = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=100)
    version = serializers.IntegerField(min_value=1)

    def validate_columnIds(self, value: list[Any]) -> list[Any]:
        """Verhindert doppelte Spalten-IDs."""
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Spalten dürfen nicht doppelt vorkommen.")
        return value


class VersionSerializer(serializers.Serializer[dict[str, Any]]):
    """Validiert eine einzelne optimistische Versionsnummer."""

    version = serializers.IntegerField(min_value=1)
