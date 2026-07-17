# apps/workspaces/models.py
"""Definiert die persistente kollaborative Workspace-Domäne."""

import hashlib
import uuid
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.validators import MinLengthValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.common.models import TimeStampedModel, UUIDModel, VersionedModel
from apps.common.validators import (
    reject_control_characters,
    validate_hex_color,
    validate_material_icon,
    validate_upload,
)
from apps.workspaces.choices import (
    AutomationTrigger,
    BoardKind,
    ColumnSystemRole,
    InvitationStatus,
    JoinRequestStatus,
    ProjectRole,
    ProjectStatus,
    RecurrenceScheduleType,
    TaskPriority,
    WorkspaceRole,
)


def attachment_upload_path(instance: "TaskAttachment", filename: str) -> str:
    """Speichert Dateien unter nicht erratbaren Namen ohne Nutzereingaben im Pfad."""
    extension = Path(filename).suffix.lower()
    return f"task-attachments/{instance.task.workspace_id}/{uuid.uuid4().hex}{extension}"


class Workspace(UUIDModel, TimeStampedModel, VersionedModel):
    """Bündelt Mitglieder, Projekte und gemeinsame Einstellungen."""

    name = models.CharField(
        max_length=80, validators=[MinLengthValidator(2), reject_control_characters]
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_workspaces",
    )
    allow_invites = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(fields=("owner", "name"), name="workspace_owner_name_unique"),
        ]

    def __str__(self) -> str:
        """Liefert den Workspace-Namen für Administration und Logs."""
        return self.name


class WorkspaceMembership(UUIDModel, TimeStampedModel):
    """Verknüpft einen Nutzer mit genau einer Workspace-Rolle."""

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workspace_memberships",
    )
    role = models.CharField(
        max_length=16, choices=WorkspaceRole.choices, default=WorkspaceRole.MEMBER
    )
    avatar_color = models.CharField(
        max_length=7, default="#6558d3", validators=[validate_hex_color]
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("user__display_name",)
        constraints = [
            models.UniqueConstraint(
                fields=("workspace", "user"), name="workspace_membership_unique"
            ),
        ]
        indexes = [
            models.Index(fields=("workspace", "role"), name="workspace_member_role_idx"),
        ]

    def __str__(self) -> str:
        """Liefert Mitglied und Workspace für die Administration."""
        return f"{self.user} in {self.workspace}"


class Project(UUIDModel, TimeStampedModel, VersionedModel):
    """Repräsentiert ein zeitlich begrenztes gemeinsames Vorhaben."""

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="projects")
    name = models.CharField(
        max_length=120, validators=[MinLengthValidator(2), reject_control_characters]
    )
    route_key = models.SlugField(max_length=140)
    slug_label = models.CharField(
        max_length=24, validators=[MinLengthValidator(2), reject_control_characters]
    )
    description = models.TextField(
        max_length=2000, blank=True, validators=[reject_control_characters]
    )
    color = models.CharField(max_length=7, default="#6558d3", validators=[validate_hex_color])
    icon = models.CharField(
        max_length=50, default="folder_open", validators=[validate_material_icon]
    )
    status = models.CharField(
        max_length=16, choices=ProjectStatus.choices, default=ProjectStatus.ACTIVE
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_projects",
    )
    started_at = models.DateField(default=timezone.localdate)
    due_at = models.DateField()
    completed_at = models.DateTimeField(blank=True, null=True)
    archived_at = models.DateTimeField(blank=True, null=True)
    allows_on_demand_tasks = models.BooleanField(default=False)

    class Meta:
        ordering = ("-updated_at", "name")
        constraints = [
            models.UniqueConstraint(
                fields=("workspace", "route_key"), name="project_route_key_unique"
            ),
            models.CheckConstraint(
                condition=Q(due_at__gte=models.F("started_at")), name="project_due_after_start"
            ),
        ]
        indexes = [
            models.Index(fields=("workspace", "status"), name="project_workspace_status_idx"),
            models.Index(fields=("workspace", "due_at"), name="project_workspace_due_idx"),
        ]

    def __str__(self) -> str:
        """Liefert den Projektnamen."""
        return self.name


class ProjectParticipant(UUIDModel, TimeStampedModel):
    """Gewährt einem Workspace-Mitglied Zugriff auf ein Projekt."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="participants")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="project_participations",
    )
    role = models.CharField(max_length=16, choices=ProjectRole.choices)

    class Meta:
        ordering = ("role", "user__display_name")
        constraints = [
            models.UniqueConstraint(fields=("project", "user"), name="project_participant_unique"),
        ]


class ProjectPreference(UUIDModel, TimeStampedModel):
    """Speichert nutzerspezifische Projektanzeigezustände."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="preferences")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="project_preferences",
    )
    is_pinned = models.BooleanField(default=False)
    last_opened_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("project", "user"), name="project_preference_unique"),
        ]


class Board(UUIDModel, TimeStampedModel, VersionedModel):
    """Enthält Spalten für ein persönliches oder projektbezogenes Board."""

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="boards")
    kind = models.CharField(max_length=16, choices=BoardKind.choices)
    project = models.OneToOneField(
        Project,
        on_delete=models.CASCADE,
        related_name="board",
        blank=True,
        null=True,
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="personal_boards",
        blank=True,
        null=True,
    )
    title = models.CharField(max_length=120, validators=[reject_control_characters])

    class Meta:
        ordering = ("created_at",)
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(kind=BoardKind.PERSONAL, owner__isnull=False, project__isnull=True)
                    | Q(kind=BoardKind.PROJECT, owner__isnull=True, project__isnull=False)
                ),
                name="board_kind_target_consistent",
            ),
            models.UniqueConstraint(
                fields=("workspace", "owner"),
                condition=Q(kind=BoardKind.PERSONAL),
                name="personal_board_per_workspace_user",
            ),
        ]

    def __str__(self) -> str:
        """Liefert den Board-Titel."""
        return self.title


class BoardColumn(UUIDModel, TimeStampedModel, VersionedModel):
    """Ordnet Aufgaben innerhalb eines Boards visuell und fachlich."""

    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="columns")
    title = models.CharField(
        max_length=80, validators=[MinLengthValidator(1), reject_control_characters]
    )
    color = models.CharField(max_length=7, default="#6558d3", validators=[validate_hex_color])
    position = models.PositiveIntegerField(default=0)
    sort_mode = models.CharField(max_length=16, blank=True, default="")
    is_fixed_position = models.BooleanField(default=False)
    is_dynamic = models.BooleanField(default=False)
    system_role = models.CharField(
        max_length=24,
        choices=ColumnSystemRole.choices,
        blank=True,
        default="",
    )

    class Meta:
        ordering = ("position", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("board", "position"), name="board_column_position_unique"
            ),
            models.UniqueConstraint(
                fields=("board", "system_role"),
                condition=~Q(system_role=""),
                name="board_column_system_role_unique",
            ),
        ]

    def __str__(self) -> str:
        """Liefert Board und Spaltentitel."""
        return f"{self.board}: {self.title}"


class Task(UUIDModel, TimeStampedModel, VersionedModel):
    """Repräsentiert eine versionierte Aufgabe mit optionaler Zuweisung."""

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="tasks")
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="tasks")
    column = models.ForeignKey(
        BoardColumn,
        on_delete=models.SET_NULL,
        related_name="tasks",
        blank=True,
        null=True,
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="tasks",
        blank=True,
        null=True,
    )
    parent_task = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        related_name="child_tasks",
        blank=True,
        null=True,
    )
    source_task = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        related_name="mirrored_tasks",
        blank=True,
        null=True,
    )
    source_subtask = models.OneToOneField(
        "Subtask",
        on_delete=models.SET_NULL,
        related_name="mirror_task",
        blank=True,
        null=True,
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_tasks",
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="assigned_tasks",
        blank=True,
        null=True,
    )
    collaborators = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="collaborative_tasks",
        blank=True,
    )
    title = models.CharField(
        max_length=180, validators=[MinLengthValidator(1), reject_control_characters]
    )
    description = models.TextField(
        max_length=10_000, blank=True, validators=[reject_control_characters]
    )
    priority = models.CharField(
        max_length=12, choices=TaskPriority.choices, default=TaskPriority.MEDIUM
    )
    start_date = models.DateField(blank=True, null=True)
    due_date = models.DateField(blank=True, null=True)
    due_time = models.TimeField(blank=True, null=True)
    tags = models.JSONField(default=list, blank=True)
    position = models.PositiveIntegerField(default=0)
    is_done = models.BooleanField(default=False)
    completed_at = models.DateTimeField(blank=True, null=True)
    is_shared_pool = models.BooleanField(default=False)
    requires_review = models.BooleanField(default=False)
    review_hint = models.CharField(
        max_length=300, blank=True, default="", validators=[reject_control_characters]
    )
    created_outside_column = models.BooleanField(default=False)
    archived_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ("position", "created_at")
        indexes = [
            models.Index(fields=("board", "column", "position"), name="task_board_column_pos_idx"),
            models.Index(
                fields=("workspace", "assignee", "is_done"), name="task_assignee_done_idx"
            ),
            models.Index(fields=("project", "due_date"), name="task_project_due_idx"),
            models.Index(fields=("workspace", "archived_at"), name="task_archive_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(due_date__isnull=True)
                | Q(start_date__isnull=True)
                | Q(due_date__gte=models.F("start_date")),
                name="task_due_after_start",
            ),
        ]

    def __str__(self) -> str:
        """Liefert den Task-Titel."""
        return self.title

    def clean(self) -> None:
        """Prüft relationale Konsistenz und begrenzt Tags."""
        super().clean()
        if self.column_id and self.column.board_id != self.board_id:
            from django.core.exceptions import ValidationError

            raise ValidationError({"column": "Die Spalte gehört nicht zu diesem Board."})
        if self.project_id and self.board.project_id != self.project_id:
            from django.core.exceptions import ValidationError

            raise ValidationError({"project": "Projekt und Board stimmen nicht überein."})
        if not isinstance(self.tags, list) or len(self.tags) > 20:
            from django.core.exceptions import ValidationError

            raise ValidationError({"tags": "Es sind maximal 20 Labels erlaubt."})
        normalized_tags: list[str] = []
        for tag in self.tags:
            if not isinstance(tag, str) or not tag.strip() or len(tag.strip()) > 40:
                from django.core.exceptions import ValidationError

                raise ValidationError({"tags": "Labels müssen 1 bis 40 Zeichen lang sein."})
            reject_control_characters(tag)
            normalized_tags.append(tag.strip())
        self.tags = normalized_tags


class Subtask(UUIDModel, TimeStampedModel, VersionedModel):
    """Speichert eine einzeln zuweisbare Unteraufgabe."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="subtasks")
    title = models.CharField(
        max_length=180, validators=[MinLengthValidator(1), reject_control_characters]
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="assigned_subtasks",
        blank=True,
        null=True,
    )
    is_done = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("position", "created_at")
        indexes = [models.Index(fields=("task", "position"), name="subtask_task_pos_idx")]

    def __str__(self) -> str:
        """Liefert den Titel der Unteraufgabe."""
        return self.title


class TaskComment(UUIDModel, TimeStampedModel, VersionedModel):
    """Speichert einen Kommentar und strukturierte Erwähnungen."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="task_comments",
    )
    body = models.TextField(
        max_length=5000, validators=[MinLengthValidator(1), reject_control_characters]
    )
    mentions = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="mentioned_comments",
        blank=True,
    )
    deleted_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ("created_at",)

    def __str__(self) -> str:
        """Liefert eine gekürzte Kommentardarstellung."""
        return self.body[:60]


class TaskAttachment(UUIDModel, TimeStampedModel):
    """Speichert eine private, berechtigungsgeprüfte Task-Datei."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to=attachment_upload_path, validators=[validate_upload])
    original_name = models.CharField(max_length=255, validators=[reject_control_characters])
    mime_type = models.CharField(max_length=150)
    size_bytes = models.PositiveBigIntegerField()
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="task_attachments",
    )

    class Meta:
        ordering = ("created_at",)

    def __str__(self) -> str:
        """Liefert ausschließlich den ursprünglichen Dateinamen."""
        return self.original_name


class TaskHistoryEntry(UUIDModel, TimeStampedModel):
    """Dokumentiert fachliche Task-Änderungen manipulationsarm."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="history")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="task_history_entries",
    )
    action = models.CharField(max_length=300, validators=[reject_control_characters])
    icon = models.CharField(max_length=50, validators=[validate_material_icon])
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-created_at",)


class TaskRecurrenceRule(UUIDModel, TimeStampedModel, VersionedModel):
    """Plant serverseitig neue Instanzen einer Vorlage."""

    task = models.OneToOneField(Task, on_delete=models.CASCADE, related_name="recurrence_rule")
    schedule_type = models.CharField(max_length=20, choices=RecurrenceScheduleType.choices)
    start_date = models.DateField()
    interval_value = models.PositiveSmallIntegerField(default=1)
    weekdays = models.JSONField(default=list, blank=True)
    day_of_month = models.PositiveSmallIntegerField(blank=True, null=True)
    next_run_on = models.DateField(blank=True, null=True)
    last_run_at = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [models.Index(fields=("is_active", "next_run_on"), name="recurrence_due_idx")]
        constraints = [
            models.CheckConstraint(
                condition=Q(interval_value__gte=1) & Q(interval_value__lte=365),
                name="recurrence_interval_range",
            ),
            models.CheckConstraint(
                condition=Q(day_of_month__isnull=True)
                | (Q(day_of_month__gte=1) & Q(day_of_month__lte=31)),
                name="recurrence_month_day_range",
            ),
        ]


class AutomationRule(UUIDModel, TimeStampedModel, VersionedModel):
    """Speichert einen validierten Trigger mit Bedingungen und Aktionen."""

    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="automation_rules")
    name = models.CharField(
        max_length=120, validators=[MinLengthValidator(2), reject_control_characters]
    )
    trigger = models.CharField(max_length=32, choices=AutomationTrigger.choices)
    conditions = models.JSONField(default=dict)
    actions = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "created_at")
        indexes = [
            models.Index(fields=("board", "trigger", "is_active"), name="automation_trigger_idx")
        ]


class WorkspaceInvitation(UUIDModel, TimeStampedModel):
    """Gewährt über ein gehashtes Token Zugriff auf Workspace oder Projekt."""

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="invitations")
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="invitations",
        blank=True,
        null=True,
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sent_workspace_invitations",
    )
    email = models.EmailField(max_length=254)
    full_name = models.CharField(max_length=60, blank=True, validators=[reject_control_characters])
    token_hash = models.CharField(max_length=64, unique=True)
    status = models.CharField(
        max_length=16, choices=InvitationStatus.choices, default=InvitationStatus.PENDING
    )
    expires_at = models.DateTimeField()
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="accepted_workspace_invitations",
        blank=True,
        null=True,
    )
    accepted_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("workspace", "status"), name="invitation_status_idx")]

    @staticmethod
    def hash_token(raw_token: str) -> str:
        """Speichert niemals das versendete Klartext-Token."""
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    @staticmethod
    def default_expiry() -> timezone.datetime:
        """Begrenzt Einladungen standardmäßig auf sieben Tage."""
        return timezone.now() + timedelta(days=7)


class WorkspaceJoinRequest(UUIDModel, TimeStampedModel):
    """Ermöglicht einen moderierten Beitritt ohne direkte Einladung."""

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="join_requests")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workspace_join_requests",
    )
    avatar_color = models.CharField(
        max_length=7, default="#6558d3", validators=[validate_hex_color]
    )
    status = models.CharField(
        max_length=16, choices=JoinRequestStatus.choices, default=JoinRequestStatus.PENDING
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="decided_workspace_join_requests",
        blank=True,
        null=True,
    )
    decided_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("workspace", "user"),
                condition=Q(status=JoinRequestStatus.PENDING),
                name="pending_join_request_unique",
            )
        ]
