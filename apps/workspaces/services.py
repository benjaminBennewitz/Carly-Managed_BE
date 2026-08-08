# apps/workspaces/services.py
"""Kapselt atomare Workspace-Änderungen und fachliche Seiteneffekte."""

import secrets
from calendar import monthrange
from datetime import date, timedelta
from typing import Any

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.common.exceptions import ConflictError, VersionConflictError
from apps.preferences.rewards import award_carly_reward_safely, reward_task_completion_safely
from apps.workspaces.choices import (
    AutomationTrigger,
    BoardKind,
    ColumnSystemRole,
    InvitationStatus,
    ProjectRole,
    ProjectStatus,
    RecurrenceScheduleType,
    WorkspaceRole,
)
from apps.workspaces.models import (
    AutomationRule,
    Board,
    BoardColumn,
    Project,
    ProjectParticipant,
    ProjectPreference,
    Subtask,
    Task,
    TaskHistoryEntry,
    TaskRecurrenceRule,
    Workspace,
    WorkspaceInvitation,
    WorkspaceMembership,
)

DEFAULT_COLUMNS = (
    ("Offen", "#6558d3"),
    ("In Arbeit", "#d68635"),
    ("Erledigt", "#4c9b70"),
)


def _broadcast_board(board_id: Any, event_type: str, payload: dict[str, Any]) -> None:
    """Sendet ein Ereignis erst nach erfolgreichem Datenbank-Commit."""
    from apps.realtime.events import broadcast_board_event

    transaction.on_commit(lambda: broadcast_board_event(board_id, event_type, payload))


def _next_position(model: type, **filters: Any) -> int:
    """Ermittelt atomar die nächste freie ganzzahlige Position."""
    maximum = model.objects.filter(**filters).aggregate(value=Max("position"))["value"]
    return 0 if maximum is None else maximum + 1


def assert_version(instance: Any, supplied_version: int | None) -> None:
    """Verhindert Änderungen auf Basis eines veralteten Frontendstands."""
    if supplied_version is None:
        raise ValidationError({"version": "Die aktuelle Versionsnummer ist erforderlich."})
    if instance.version != supplied_version:
        raise VersionConflictError(
            {
                "message": "Die Ressource wurde zwischenzeitlich geändert.",
                "currentVersion": instance.version,
            }
        )


def increment_version(instance: Any) -> None:
    """Erhöht die optimistische Versionsnummer vor dem Speichern."""
    instance.version += 1


def _dynamic_new_columns_enabled(user: User) -> bool:
    """Liefert die persönliche Einstellung für die dynamische Neu-Spalte."""
    from apps.preferences.models import UserSettings

    value = (
        UserSettings.objects.filter(user=user)
        .values_list("dynamic_new_columns", flat=True)
        .first()
    )
    return True if value is None else bool(value)


def _ensure_personal_intake_column(*, board: Board, user: User) -> BoardColumn:
    """Stellt die persönliche Eingangsspalte bereit und liefert ein gültiges Task-Ziel."""
    intake = board.columns.filter(system_role=ColumnSystemRole.NEW_ASSIGNED).first()
    if _dynamic_new_columns_enabled(user):
        if intake is None:
            existing_columns = list(board.columns.order_by("-position"))
            for column in existing_columns:
                column.position += 1
                column.save(update_fields=("position", "updated_at"))
            intake = BoardColumn.objects.create(
                board=board,
                title="Neu",
                color="#D5A646",
                position=0,
                is_fixed_position=True,
                is_dynamic=True,
                system_role=ColumnSystemRole.NEW_ASSIGNED,
            )
        return intake

    fallback = (
        board.columns.exclude(system_role=ColumnSystemRole.NEW_ASSIGNED)
        .order_by("position")
        .first()
    )
    if fallback is None and intake is not None:
        return intake
    if fallback is None:
        fallback = BoardColumn.objects.create(
            board=board,
            title=DEFAULT_COLUMNS[0][0],
            color=DEFAULT_COLUMNS[0][1],
            position=0,
        )
    return fallback


def ensure_personal_board_for_workspace(*, user: User, workspace: Workspace) -> Board:
    """Stellt pro Nutzer und Workspace genau ein persönliches Board bereit."""
    board, created = Board.objects.get_or_create(
        workspace=workspace,
        owner=user,
        kind=BoardKind.PERSONAL,
        defaults={"title": "Mein Board"},
    )
    if created:
        offset = 1 if _dynamic_new_columns_enabled(user) else 0
        BoardColumn.objects.bulk_create(
            [
                BoardColumn(board=board, title=title, color=color, position=position + offset)
                for position, (title, color) in enumerate(DEFAULT_COLUMNS)
            ]
        )
    _ensure_personal_intake_column(board=board, user=user)
    return board


@transaction.atomic
def bootstrap_personal_workspace(user: User) -> Workspace:
    """Erstellt genau einen persönlichen Start-Workspace samt Board."""
    existing = Workspace.objects.filter(owner=user).first()
    if existing:
        ensure_personal_board_for_workspace(user=user, workspace=existing)
        return existing
    workspace = Workspace.objects.create(name=f"{user.display_name}s Workspace", owner=user)
    WorkspaceMembership.objects.create(
        workspace=workspace,
        user=user,
        role=WorkspaceRole.OWNER,
        avatar_color="#6558d3",
    )
    ensure_personal_board_for_workspace(user=user, workspace=workspace)
    from apps.preferences.services import bootstrap_preferences

    bootstrap_preferences(user=user, workspace=workspace)
    return workspace


def _unique_project_route_key(workspace: Workspace, name: str) -> str:
    """Erzeugt einen stabilen, innerhalb des Workspaces eindeutigen Route-Key."""
    base = slugify(name)[:120] or "projekt"
    candidate = base
    counter = 2
    while Project.objects.filter(workspace=workspace, route_key=candidate).exists():
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


@transaction.atomic
def create_project(
    *,
    workspace: Workspace,
    actor: User,
    validated_data: dict[str, Any],
) -> Project:
    """Erstellt Projekt, Teilnehmer, Board und Standardspalten atomar."""
    manager_users = validated_data.pop("manager_users", [])
    collaborator_users = validated_data.pop("collaborator_users", [])
    is_pinned = validated_data.pop("is_pinned_input", False)
    owner = validated_data.pop("owner", actor)
    validated_data.setdefault("started_at", timezone.localdate())
    validated_data.setdefault("slug_label", validated_data["name"][:24])
    project = Project.objects.create(
        workspace=workspace,
        owner=owner,
        route_key=_unique_project_route_key(workspace, validated_data["name"]),
        **validated_data,
    )
    participants = [
        ProjectParticipant(project=project, user=user, role=ProjectRole.MANAGER)
        for user in manager_users
        if user.id != owner.id
    ] + [
        ProjectParticipant(project=project, user=user, role=ProjectRole.COLLABORATOR)
        for user in collaborator_users
        if user.id != owner.id and user not in manager_users
    ]
    ProjectParticipant.objects.bulk_create(participants, ignore_conflicts=True)
    ProjectPreference.objects.create(project=project, user=actor, is_pinned=is_pinned)
    board = Board.objects.create(
        workspace=workspace,
        project=project,
        kind=BoardKind.PROJECT,
        title=project.name,
    )
    BoardColumn.objects.bulk_create(
        [
            BoardColumn(board=board, title=title, color=color, position=position)
            for position, (title, color) in enumerate(DEFAULT_COLUMNS)
        ]
    )
    _broadcast_board(board.id, "project.created", {"projectId": str(project.id)})
    award_carly_reward_safely(
        user=actor,
        event_type="project_created",
        event_key=f"project-created:{project.id}",
        source_type="project",
        source_id=str(project.id),
        message=f"„{project.name}“ ist angelegt. Ein guter Anfang.",
    )
    return project


@transaction.atomic
def update_project(
    *,
    project: Project,
    actor: User,
    validated_data: dict[str, Any],
    supplied_version: int | None,
) -> Project:
    """Aktualisiert Projektfelder und Rollen unter Versionskontrolle."""
    locked = (
        Project.objects.select_for_update(of=("self",))
        .select_related("board")
        .get(pk=project.pk)
    )
    assert_version(locked, supplied_version)
    previous_recipient_ids = set(
        WorkspaceMembership.objects.filter(
            workspace=locked.workspace,
            is_active=True,
            role__in=[WorkspaceRole.OWNER, WorkspaceRole.MANAGER],
        ).values_list("user_id", flat=True)
    )
    previous_recipient_ids.add(locked.owner_id)
    previous_recipient_ids.update(
        locked.participants.values_list("user_id", flat=True)
    )
    manager_users = validated_data.pop("manager_users", None)
    collaborator_users = validated_data.pop("collaborator_users", None)
    is_pinned = validated_data.pop("is_pinned_input", None)
    meaningful_change = any(
        getattr(locked, field) != value for field, value in validated_data.items()
    )
    if manager_users is not None:
        current_manager_ids = set(
            locked.participants.filter(role=ProjectRole.MANAGER).values_list("user_id", flat=True)
        )
        desired_manager_ids = {user.id for user in manager_users if user.id != locked.owner_id}
        meaningful_change = meaningful_change or current_manager_ids != desired_manager_ids
    if collaborator_users is not None:
        current_collaborator_ids = set(
            locked.participants.filter(role=ProjectRole.COLLABORATOR).values_list(
                "user_id", flat=True
            )
        )
        desired_collaborator_ids = {
            user.id
            for user in collaborator_users
            if user.id != locked.owner_id
            and (manager_users is None or user.id not in {manager.id for manager in manager_users})
        }
        meaningful_change = meaningful_change or (
            current_collaborator_ids != desired_collaborator_ids
        )
    for field, value in validated_data.items():
        setattr(locked, field, value)
    if "name" in validated_data and locked.board.title != locked.name:
        locked.board.title = locked.name
        increment_version(locked.board)
        locked.board.save(update_fields=("title", "version", "updated_at"))
    increment_version(locked)
    locked.full_clean()
    locked.save()
    if manager_users is not None or collaborator_users is not None:
        existing = {participant.user_id: participant for participant in locked.participants.all()}
        desired: dict[Any, str] = {}
        if manager_users is not None:
            desired.update(
                {
                    user.id: ProjectRole.MANAGER
                    for user in manager_users
                    if user.id != locked.owner_id
                }
            )
        else:
            desired.update(
                {
                    user_id: participant.role
                    for user_id, participant in existing.items()
                    if participant.role == ProjectRole.MANAGER
                }
            )
        if collaborator_users is not None:
            desired.update(
                {
                    user.id: ProjectRole.COLLABORATOR
                    for user in collaborator_users
                    if user.id != locked.owner_id and user.id not in desired
                }
            )
        else:
            desired.update(
                {
                    user_id: participant.role
                    for user_id, participant in existing.items()
                    if participant.role == ProjectRole.COLLABORATOR and user_id not in desired
                }
            )
        locked.participants.exclude(user_id__in=desired).delete()
        for user_id, role in desired.items():
            ProjectParticipant.objects.update_or_create(
                project=locked, user_id=user_id, defaults={"role": role}
            )
    if is_pinned is not None:
        ProjectPreference.objects.update_or_create(
            project=locked, user=actor, defaults={"is_pinned": is_pinned}
        )
    current_recipient_ids = set(
        WorkspaceMembership.objects.filter(
            workspace=locked.workspace,
            is_active=True,
            role__in=[WorkspaceRole.OWNER, WorkspaceRole.MANAGER],
        ).values_list("user_id", flat=True)
    )
    current_recipient_ids.add(locked.owner_id)
    current_recipient_ids.update(
        locked.participants.values_list("user_id", flat=True)
    )
    recipient_ids = previous_recipient_ids | current_recipient_ids
    _broadcast_board(
        locked.board.id, "project.updated", {"projectId": str(locked.id), "version": locked.version}
    )
    if recipient_ids:
        from apps.realtime.events import broadcast_inbox_event

        transaction.on_commit(
            lambda: broadcast_inbox_event(
                recipient_ids,
                "workspace.project.updated",
                {
                    "workspaceId": str(locked.workspace_id),
                    "projectId": str(locked.id),
                    "version": locked.version,
                },
            )
        )
    if meaningful_change:
        bucket = int(timezone.now().timestamp() // 300)
        award_carly_reward_safely(
            user=actor,
            event_type="project_updated",
            event_key=f"project-updated:{locked.id}:{bucket}",
            source_type="project",
            source_id=str(locked.id),
        )
    return locked


@transaction.atomic
def set_project_status(
    *, project: Project, actor: User, status_value: str, supplied_version: int
) -> Project:
    """Ändert Abschluss oder Archivierung eines Projekts konsistent."""
    locked = (
        Project.objects.select_for_update(of=("self",))
        .select_related("board")
        .get(pk=project.pk)
    )
    assert_version(locked, supplied_version)
    now = timezone.now()
    previous_status = locked.status
    locked.status = status_value
    if status_value == ProjectStatus.COMPLETED:
        locked.completed_at = now
        locked.archived_at = None
    elif status_value == ProjectStatus.ARCHIVED:
        locked.archived_at = now
    elif status_value == ProjectStatus.ACTIVE:
        locked.completed_at = None
        locked.archived_at = None
    increment_version(locked)
    locked.save(update_fields=("status", "completed_at", "archived_at", "version", "updated_at"))
    _broadcast_board(
        locked.board.id,
        "project.status_changed",
        {"projectId": str(locked.id), "status": locked.status, "version": locked.version},
    )
    if status_value == ProjectStatus.COMPLETED and previous_status != ProjectStatus.COMPLETED:
        award_carly_reward_safely(
            user=actor,
            event_type="project_completed",
            event_key=f"project-completed:{locked.id}",
            source_type="project",
            source_id=str(locked.id),
            message=f"„{locked.name}“ ist abgeschlossen. Das war echte Arbeit.",
        )
    return locked


def _assignment_mirrors(task: Task):
    """Liefert persönliche Spiegelungen einer vollständig zugewiesenen Projektaufgabe."""
    return Task.objects.filter(
        source_task=task,
        source_subtask__isnull=True,
        board__kind=BoardKind.PERSONAL,
    )


def _sync_assignment_mirror(task: Task) -> None:
    """Synchronisiert eine Projektzuweisung mit dem persönlichen Eingang des Empfängers."""
    mirrors = _assignment_mirrors(task)
    if task.board.kind != BoardKind.PROJECT or task.source_task_id or task.source_subtask_id:
        mirrors.delete()
        return

    assignee = task.assignee
    if assignee is None:
        for mirror in mirrors:
            board_id = mirror.board_id
            mirror_id = str(mirror.id)
            mirror.delete()
            _broadcast_board(board_id, "task.deleted", {"taskId": mirror_id})
        return

    personal_board = ensure_personal_board_for_workspace(user=assignee, workspace=task.workspace)
    intake_column = _ensure_personal_intake_column(board=personal_board, user=assignee)
    mirror = mirrors.filter(board=personal_board).first()

    for obsolete in mirrors.exclude(board=personal_board):
        board_id = obsolete.board_id
        mirror_id = str(obsolete.id)
        obsolete.delete()
        _broadcast_board(board_id, "task.deleted", {"taskId": mirror_id})

    if mirror is None:
        mirror = Task.objects.create(
            workspace=task.workspace,
            board=personal_board,
            column=intake_column,
            project=task.project,
            source_task=task,
            owner=task.owner,
            assignee=assignee,
            title=task.title,
            description=task.description,
            priority=task.priority,
            start_date=task.start_date,
            due_date=task.due_date,
            due_time=task.due_time,
            tags=list(task.tags),
            position=_next_position(Task, column=intake_column, archived_at__isnull=True),
            is_done=task.is_done,
            completed_at=task.completed_at,
            requires_review=False,
            review_hint="Zuweisung aus einem geteilten Projekt.",
        )
        _broadcast_board(
            personal_board.id,
            "task.created",
            {
                "taskId": str(mirror.id),
                "columnId": str(intake_column.id),
                "version": mirror.version,
            },
        )
        return

    mirror.project = task.project
    mirror.owner = task.owner
    mirror.assignee = assignee
    mirror.title = task.title
    mirror.description = task.description
    mirror.priority = task.priority
    mirror.start_date = task.start_date
    mirror.due_date = task.due_date
    mirror.due_time = task.due_time
    mirror.tags = list(task.tags)
    mirror.is_done = task.is_done
    mirror.completed_at = task.completed_at
    mirror.archived_at = task.archived_at
    increment_version(mirror)
    mirror.save(
        update_fields=(
            "project",
            "owner",
            "assignee",
            "title",
            "description",
            "priority",
            "start_date",
            "due_date",
            "due_time",
            "tags",
            "is_done",
            "completed_at",
            "archived_at",
            "version",
            "updated_at",
        )
    )
    _broadcast_board(
        personal_board.id, "task.updated", {"taskId": str(mirror.id), "version": mirror.version}
    )


@transaction.atomic
def create_task(
    *,
    board: Board,
    actor: User,
    validated_data: dict[str, Any],
) -> Task:
    """Erstellt einen Task, ordnet ihn ein und führt passende Regeln aus."""
    collaborators = validated_data.pop("collaborators", [])
    if board.kind == BoardKind.PERSONAL:
        validated_data["assignee"] = board.owner
        validated_data["column"] = _ensure_personal_intake_column(
            board=board, user=board.owner
        )
    elif validated_data.get("column") is None:
        validated_data["column"] = board.columns.order_by("position").first()
    column = validated_data["column"]
    position = _next_position(Task, column=column, archived_at__isnull=True)
    task = Task.objects.create(
        workspace=board.workspace,
        board=board,
        project=board.project,
        owner=actor,
        position=position,
        **validated_data,
    )
    task.collaborators.set(collaborators)
    _sync_assignment_mirror(task)
    add_history(task=task, actor=actor, action="Task erstellt", icon="add_task")
    execute_automation_rules(task=task, trigger=AutomationTrigger.TASK_CREATED, actor=actor)
    _broadcast_board(
        board.id,
        "task.created",
        {"taskId": str(task.id), "columnId": str(task.column_id), "version": task.version},
    )
    award_carly_reward_safely(
        user=actor,
        event_type="task_created",
        event_key=f"task-created:{task.id}",
        source_type="task",
        source_id=str(task.id),
    )
    return task


@transaction.atomic
def update_task(
    *,
    task: Task,
    actor: User,
    validated_data: dict[str, Any],
    supplied_version: int | None,
) -> Task:
    """Aktualisiert einen Task und behandelt Zuweisungsregeln atomar."""
    locked = Task.objects.select_for_update().get(pk=task.pk)
    assert_version(locked, supplied_version)
    old_assignee_id = locked.assignee_id
    collaborators = validated_data.pop("collaborators", None)
    target_column = validated_data.pop("column", None)
    meaningful_change = any(
        getattr(locked, field) != value for field, value in validated_data.items()
    )
    if collaborators is not None:
        current_collaborators = set(locked.collaborators.values_list("id", flat=True))
        desired_collaborators = {user.id for user in collaborators}
        meaningful_change = meaningful_change or current_collaborators != desired_collaborators
    if target_column is not None and target_column.id != locked.column_id:
        meaningful_change = True
    for field, value in validated_data.items():
        setattr(locked, field, value)
    if target_column is not None and target_column.id != locked.column_id:
        locked.column = target_column
        locked.position = _next_position(Task, column=target_column, archived_at__isnull=True)
    increment_version(locked)
    locked.full_clean()
    locked.save()
    if collaborators is not None:
        locked.collaborators.set(collaborators)
    _sync_assignment_mirror(locked)
    add_history(task=locked, actor=actor, action="Task aktualisiert", icon="edit_note")
    if old_assignee_id != locked.assignee_id:
        execute_automation_rules(task=locked, trigger=AutomationTrigger.TASK_ASSIGNED, actor=actor)
    if target_column is not None:
        execute_automation_rules(task=locked, trigger=AutomationTrigger.COLUMN_ENTERED, actor=actor)
    _broadcast_board(
        locked.board_id, "task.updated", {"taskId": str(locked.id), "version": locked.version}
    )
    if meaningful_change:
        bucket = int(timezone.now().timestamp() // 300)
        award_carly_reward_safely(
            user=actor,
            event_type="task_updated",
            event_key=f"task-updated:{locked.id}:{bucket}",
            source_type="task",
            source_id=str(locked.id),
        )
    return locked


@transaction.atomic
def move_task(
    *,
    task: Task,
    actor: User,
    target_column: BoardColumn,
    target_position: int,
    supplied_version: int,
) -> Task:
    """Verschiebt einen Task mit Reihenfolgenkorrektur und Konfliktprüfung."""
    locked = Task.objects.select_for_update().get(pk=task.pk)
    assert_version(locked, supplied_version)
    if target_column.board_id != locked.board_id:
        raise ValidationError({"targetColumnId": "Die Zielspalte gehört nicht zu diesem Board."})
    source_column_id = locked.column_id
    siblings = list(
        Task.objects.select_for_update()
        .filter(column=target_column, archived_at__isnull=True)
        .exclude(pk=locked.pk)
        .order_by("position", "created_at")
    )
    insert_at = max(0, min(target_position, len(siblings)))
    siblings.insert(insert_at, locked)
    for position, sibling in enumerate(siblings):
        sibling.position = position
        if sibling.pk == locked.pk:
            sibling.column = target_column
            increment_version(sibling)
    Task.objects.bulk_update(siblings, ("position", "column", "version", "updated_at"))
    if source_column_id and source_column_id != target_column.id:
        source_tasks = list(
            Task.objects.select_for_update()
            .filter(column_id=source_column_id, archived_at__isnull=True)
            .exclude(pk=locked.pk)
            .order_by("position", "created_at")
        )
        for position, source_task in enumerate(source_tasks):
            source_task.position = position
        Task.objects.bulk_update(source_tasks, ("position", "updated_at"))
    add_history(
        task=locked,
        actor=actor,
        action=f"In „{target_column.title}“ verschoben",
        icon="drive_file_move",
    )
    execute_automation_rules(task=locked, trigger=AutomationTrigger.COLUMN_ENTERED, actor=actor)
    _broadcast_board(
        locked.board_id,
        "task.moved",
        {
            "taskId": str(locked.id),
            "columnId": str(target_column.id),
            "position": insert_at,
            "version": locked.version,
        },
    )
    bucket = int(timezone.now().timestamp() // 600)
    award_carly_reward_safely(
        user=actor,
        event_type="task_moved",
        event_key=f"task-moved:{locked.id}:{bucket}",
        source_type="task",
        source_id=str(locked.id),
    )
    return locked


@transaction.atomic
def set_task_completed(*, task: Task, actor: User, completed: bool, supplied_version: int) -> Task:
    """Schließt oder öffnet einen Task und synchronisiert Spiegelungen."""
    locked = Task.objects.select_for_update().get(pk=task.pk)
    assert_version(locked, supplied_version)
    was_completed = locked.is_done
    locked.is_done = completed
    locked.completed_at = timezone.now() if completed else None
    increment_version(locked)
    locked.save(update_fields=("is_done", "completed_at", "version", "updated_at"))
    reward_task = locked
    if locked.source_task_id and locked.source_subtask_id is None:
        source = Task.objects.select_for_update().filter(pk=locked.source_task_id).first()
        if source is not None:
            source.is_done = completed
            source.completed_at = locked.completed_at
            increment_version(source)
            source.save(update_fields=("is_done", "completed_at", "version", "updated_at"))
            _sync_assignment_mirror(source)
            _broadcast_board(
                source.board_id,
                "task.completed" if completed else "task.reopened",
                {"taskId": str(source.id), "version": source.version},
            )
            reward_task = source
            locked.refresh_from_db()
    else:
        _sync_assignment_mirror(locked)
    action = "Task abgeschlossen" if completed else "Task wieder geöffnet"
    add_history(
        task=locked, actor=actor, action=action, icon="task_alt" if completed else "refresh"
    )
    if locked.source_subtask_id:
        Subtask.objects.filter(pk=locked.source_subtask_id).update(
            is_done=completed, updated_at=timezone.now()
        )
    trigger = AutomationTrigger.TASK_COMPLETED if completed else AutomationTrigger.TASK_REOPENED
    execute_automation_rules(task=locked, trigger=trigger, actor=actor)
    _broadcast_board(
        locked.board_id,
        "task.completed" if completed else "task.reopened",
        {"taskId": str(locked.id), "version": locked.version},
    )
    if completed and not was_completed:
        if locked.source_subtask_id:
            award_carly_reward_safely(
                user=actor,
                event_type="subtask_completed",
                event_key=f"subtask-completed:{locked.source_subtask_id}",
                source_type="subtask",
                source_id=str(locked.source_subtask_id),
            )
        else:
            reward_task_completion_safely(user=actor, task=reward_task)
    return locked


@transaction.atomic
def archive_task(*, task: Task, actor: User, supplied_version: int, archived: bool = True) -> Task:
    """Archiviert oder stellt einen Task wieder her."""
    locked = Task.objects.select_for_update().get(pk=task.pk)
    assert_version(locked, supplied_version)
    locked.archived_at = timezone.now() if archived else None
    increment_version(locked)
    locked.save(update_fields=("archived_at", "version", "updated_at"))
    _sync_assignment_mirror(locked)
    add_history(
        task=locked,
        actor=actor,
        action="Task archiviert" if archived else "Task wiederhergestellt",
        icon="archive" if archived else "unarchive",
    )
    _broadcast_board(
        locked.board_id,
        "task.archived" if archived else "task.restored",
        {"taskId": str(locked.id), "version": locked.version},
    )
    return locked


def add_history(
    *, task: Task, actor: User, action: str, icon: str, metadata: dict[str, Any] | None = None
) -> TaskHistoryEntry:
    """Erzeugt einen unveränderlichen fachlichen Verlaufseintrag."""
    return TaskHistoryEntry.objects.create(
        task=task, actor=actor, action=action, icon=icon, metadata=metadata or {}
    )


def _sync_subtask_mirror(subtask: Subtask) -> None:
    """Synchronisiert eine zugewiesene Projekt-Unteraufgabe mit dem persönlichen Eingang."""
    task = subtask.task
    mirror = Task.objects.filter(source_subtask=subtask).first()
    assignee = subtask.assignee

    if task.board.kind != BoardKind.PROJECT or assignee is None:
        if mirror is not None:
            board_id = mirror.board_id
            mirror_id = str(mirror.id)
            mirror.delete()
            _broadcast_board(board_id, "task.deleted", {"taskId": mirror_id})
        return

    personal_board = ensure_personal_board_for_workspace(user=assignee, workspace=task.workspace)
    intake_column = _ensure_personal_intake_column(board=personal_board, user=assignee)

    if mirror is None:
        mirror = Task.objects.create(
            workspace=task.workspace,
            board=personal_board,
            column=intake_column,
            project=task.project,
            parent_task=task,
            source_task=task,
            source_subtask=subtask,
            owner=task.owner,
            assignee=assignee,
            title=subtask.title,
            description=f"Unteraufgabe aus „{task.title}“",
            priority=task.priority,
            due_date=task.due_date,
            position=_next_position(Task, column=intake_column, archived_at__isnull=True),
            is_done=subtask.is_done,
            completed_at=timezone.now() if subtask.is_done else None,
        )
        _broadcast_board(
            personal_board.id,
            "task.created",
            {
                "taskId": str(mirror.id),
                "columnId": str(intake_column.id),
                "version": mirror.version,
            },
        )
        return

    old_board_id = mirror.board_id
    board_changed = mirror.board_id != personal_board.id
    mirror.workspace = task.workspace
    mirror.board = personal_board
    if board_changed:
        mirror.column = intake_column
        mirror.position = _next_position(Task, column=intake_column, archived_at__isnull=True)
    mirror.project = task.project
    mirror.parent_task = task
    mirror.source_task = task
    mirror.owner = task.owner
    mirror.assignee = assignee
    mirror.title = subtask.title
    mirror.description = f"Unteraufgabe aus „{task.title}“"
    mirror.priority = task.priority
    mirror.due_date = task.due_date
    mirror.is_done = subtask.is_done
    mirror.completed_at = timezone.now() if subtask.is_done else None
    increment_version(mirror)
    mirror.save()
    if board_changed:
        _broadcast_board(old_board_id, "task.deleted", {"taskId": str(mirror.id)})
        _broadcast_board(
            personal_board.id,
            "task.created",
            {
                "taskId": str(mirror.id),
                "columnId": str(mirror.column_id),
                "version": mirror.version,
            },
        )
    else:
        _broadcast_board(
            personal_board.id,
            "task.updated",
            {"taskId": str(mirror.id), "version": mirror.version},
        )


@transaction.atomic
def create_subtask(
    *,
    task: Task,
    actor: User,
    title: str,
    assignee: User | None,
    subtask_id: Any | None = None,
) -> Subtask:
    """Erstellt eine Unteraufgabe und optional eine persönliche Spiegelaufgabe."""
    position = _next_position(Subtask, task=task)
    create_kwargs: dict[str, Any] = {
        "task": task,
        "title": title,
        "assignee": assignee,
        "position": position,
    }
    if subtask_id is not None:
        create_kwargs["id"] = subtask_id
    subtask = Subtask.objects.create(**create_kwargs)
    add_history(
        task=task, actor=actor, action=f"Unteraufgabe „{title}“ erstellt", icon="playlist_add"
    )
    _sync_subtask_mirror(subtask)
    _broadcast_board(
        task.board_id, "subtask.created", {"taskId": str(task.id), "subtaskId": str(subtask.id)}
    )
    return subtask


@transaction.atomic
def update_subtask(
    *,
    subtask: Subtask,
    actor: User,
    supplied_version: int,
    title: str | None = None,
    assignee: User | None | object = ...,
    is_done: bool | None = None,
) -> Subtask:
    """Aktualisiert Unteraufgabe und vorhandene persönliche Spiegelung."""
    locked = Subtask.objects.select_for_update().select_related("task").get(pk=subtask.pk)
    assert_version(locked, supplied_version)
    was_done = locked.is_done
    if title is not None:
        locked.title = title
    if assignee is not ...:
        locked.assignee = assignee
    if is_done is not None:
        locked.is_done = is_done
    increment_version(locked)
    locked.full_clean()
    locked.save()
    _sync_subtask_mirror(locked)
    add_history(
        task=locked.task,
        actor=actor,
        action=f"Unteraufgabe „{locked.title}“ aktualisiert",
        icon="checklist",
    )
    _broadcast_board(
        locked.task.board_id,
        "subtask.updated",
        {"taskId": str(locked.task_id), "subtaskId": str(locked.id), "version": locked.version},
    )
    if locked.is_done and not was_done:
        award_carly_reward_safely(
            user=actor,
            event_type="subtask_completed",
            event_key=f"subtask-completed:{locked.id}",
            source_type="subtask",
            source_id=str(locked.id),
        )
    return locked


def _matches_automation(rule: AutomationRule, task: Task) -> bool:
    """Prüft die unterstützten Regelbedingungen defensiv."""
    conditions = rule.conditions or {}
    source_column_id = conditions.get("sourceColumnId")
    if source_column_id and str(task.column_id) != str(source_column_id):
        return False
    search_term = str(conditions.get("searchTerm", "")).strip().casefold()
    if search_term and search_term not in f"{task.title} {task.description}".casefold():
        return False
    due_mode = conditions.get("dueDateMode", "any")
    today = timezone.localdate()
    if due_mode == "today" and task.due_date != today:
        return False
    if due_mode == "due_soon" and (
        task.due_date is None or not today <= task.due_date <= today + timedelta(days=7)
    ):
        return False
    if due_mode == "overdue" and (task.due_date is None or task.due_date >= today):
        return False
    if due_mode == "without_date" and task.due_date is not None:
        return False
    if conditions.get("taskScope") == "main_task" and task.parent_task_id is not None:
        return False
    return True


def execute_automation_rules(*, task: Task, trigger: str, actor: User) -> None:
    """Führt begrenzte Verschieberegeln ohne rekursive Endlosschleifen aus."""
    rules = AutomationRule.objects.filter(
        board=task.board, trigger=trigger, is_active=True
    ).order_by("sort_order")
    for rule in rules:
        if not _matches_automation(rule, task):
            continue
        for action in rule.actions[:5]:
            if action.get("type") != "move_task_tree":
                continue
            target = BoardColumn.objects.filter(
                board=task.board, pk=action.get("targetColumnId")
            ).first()
            if target is None or target.id == task.column_id:
                continue
            task.column = target
            task.position = _next_position(Task, column=target, archived_at__isnull=True)
            increment_version(task)
            task.save(update_fields=("column", "position", "version", "updated_at"))
            add_history(
                task=task,
                actor=actor,
                action=f"Automation „{rule.name}“ ausgeführt",
                icon="automation",
            )
            _broadcast_board(
                task.board_id,
                "automation.executed",
                {
                    "ruleId": str(rule.id),
                    "taskId": str(task.id),
                    "columnId": str(target.id),
                    "version": task.version,
                },
            )
            return


def calculate_next_run(rule: TaskRecurrenceRule, from_date: date | None = None) -> date:
    """Berechnet den nächsten Lauf für Tages-, Wochen- oder Monatsregeln."""
    cursor = max(from_date or timezone.localdate(), rule.start_date)
    if rule.schedule_type == RecurrenceScheduleType.INTERVAL_DAYS:
        if cursor <= rule.start_date:
            return rule.start_date
        elapsed = (cursor - rule.start_date).days
        remainder = elapsed % rule.interval_value
        return (
            cursor if remainder == 0 else cursor + timedelta(days=rule.interval_value - remainder)
        )
    if rule.schedule_type == RecurrenceScheduleType.WEEKLY_DAYS:
        weekday_map = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
        allowed = {weekday_map[value] for value in rule.weekdays if value in weekday_map}
        for offset in range(0, 14):
            candidate = cursor + timedelta(days=offset)
            if candidate >= rule.start_date and candidate.weekday() in allowed:
                return candidate
        return cursor + timedelta(days=7)
    day = rule.day_of_month or 1
    year, month = cursor.year, cursor.month
    candidate = date(year, month, min(day, monthrange(year, month)[1]))
    if candidate < cursor:
        month = 1 if month == 12 else month + 1
        year = year + 1 if cursor.month == 12 else year
        candidate = date(year, month, min(day, monthrange(year, month)[1]))
    return max(candidate, rule.start_date)


@transaction.atomic
def save_recurrence_rule(
    *, task: Task, validated_data: dict[str, Any], supplied_version: int | None
) -> TaskRecurrenceRule:
    """Erstellt oder ändert eine Wiederholung unter Versionskontrolle."""
    rule = TaskRecurrenceRule.objects.select_for_update().filter(task=task).first()
    if rule:
        assert_version(rule, supplied_version)
        for field, value in validated_data.items():
            setattr(rule, field, value)
        increment_version(rule)
    else:
        rule = TaskRecurrenceRule(task=task, **validated_data)
    rule.full_clean()
    rule.next_run_on = calculate_next_run(rule)
    rule.save()
    _broadcast_board(
        task.board_id,
        "recurrence.updated",
        {"taskId": str(task.id), "ruleId": str(rule.id), "version": rule.version},
    )
    return rule


@transaction.atomic
def create_invitation(
    *,
    workspace: Workspace,
    project: Project | None,
    actor: User,
    email: str,
    full_name: str = "",
) -> tuple[WorkspaceInvitation, str]:
    """Erzeugt eine Einladung und informiert bestehende Konten zusätzlich in-app."""
    if not workspace.allow_invites:
        raise ConflictError("Einladungen sind für diesen Workspace deaktiviert.")
    normalized_email = email.strip().lower()
    now = timezone.now()
    if WorkspaceMembership.objects.filter(
        workspace=workspace,
        user__email__iexact=normalized_email,
        is_active=True,
    ).exists():
        raise ConflictError("Diese Person ist bereits Mitglied des Workspaces.")

    WorkspaceInvitation.objects.filter(
        workspace=workspace,
        email__iexact=normalized_email,
        status=InvitationStatus.PENDING,
        expires_at__lte=now,
    ).update(status=InvitationStatus.EXPIRED, updated_at=now)
    if WorkspaceInvitation.objects.filter(
        workspace=workspace,
        email__iexact=normalized_email,
        status=InvitationStatus.PENDING,
        expires_at__gt=now,
    ).exists():
        raise ConflictError("Für diese E-Mail-Adresse besteht bereits eine offene Einladung.")

    existing_user = User.objects.filter(email__iexact=normalized_email, is_active=True).first()
    raw_token = secrets.token_urlsafe(48)
    invitation = WorkspaceInvitation.objects.create(
        workspace=workspace,
        project=project,
        invited_by=actor,
        email=normalized_email,
        full_name=existing_user.display_name if existing_user else full_name.strip(),
        token_hash=WorkspaceInvitation.hash_token(raw_token),
        expires_at=WorkspaceInvitation.default_expiry(),
    )
    if existing_user:
        from apps.inbox.services import create_notification
        from apps.realtime.events import broadcast_inbox_event

        target = f" im Projekt {project.name}" if project else ""
        create_notification(
            recipient=existing_user,
            workspace=workspace,
            actor=actor,
            kind="member",
            title=f"Einladung zu {workspace.name}",
            body=f"{actor.display_name} hat dich{target} zur Zusammenarbeit eingeladen.",
            icon="group_add",
            route="/members",
        )
        transaction.on_commit(
            lambda: broadcast_inbox_event(
                [existing_user.id],
                "workspace.invitation.created",
                {"invitationId": str(invitation.id), "workspaceId": str(workspace.id)},
            )
        )

    if existing_user is None:
        url = f"{settings.FRONTEND_URL}/invite#token={raw_token}"
        send_mail(
            subject=f"Einladung zu {workspace.name}",
            message=(
                "Du wurdest zu Carly Managed eingeladen. Erstelle ein Konto mit dieser "
                f"E-Mail-Adresse und öffne anschließend diesen Link:\n\n{url}\n\n"
                "Der Link ist sieben Tage gültig."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[normalized_email],
            fail_silently=False,
        )
    return invitation, raw_token


def _validate_invitation_for_user(
    invitation: WorkspaceInvitation | None, user: User
) -> WorkspaceInvitation:
    """Prüft Status, Ablauf und E-Mail-Zuordnung einer Einladung."""
    if (
        invitation is None
        or invitation.status != InvitationStatus.PENDING
        or invitation.expires_at <= timezone.now()
    ):
        raise ValidationError(
            "Die Einladung ist ungültig oder abgelaufen.", code="invalid_invitation"
        )
    if invitation.email.casefold() != user.email.casefold():
        raise ValidationError(
            "Die Einladung gehört zu einer anderen E-Mail-Adresse.",
            code="invitation_email_mismatch",
        )
    return invitation


def _complete_invitation_acceptance(
    *, invitation: WorkspaceInvitation, user: User
) -> WorkspaceInvitation:
    """Vergibt Workspace-/Projektzugriff und markiert die Einladung als angenommen."""
    WorkspaceMembership.objects.update_or_create(
        workspace=invitation.workspace,
        user=user,
        defaults={"role": WorkspaceRole.MEMBER, "is_active": True},
    )
    ensure_personal_board_for_workspace(user=user, workspace=invitation.workspace)
    if invitation.project:
        ProjectParticipant.objects.update_or_create(
            project=invitation.project,
            user=user,
            defaults={"role": ProjectRole.COLLABORATOR},
        )
    invitation.status = InvitationStatus.ACCEPTED
    invitation.accepted_by = user
    invitation.accepted_at = timezone.now()
    invitation.full_name = user.display_name
    invitation.save(
        update_fields=("status", "accepted_by", "accepted_at", "full_name", "updated_at")
    )

    from apps.inbox.services import create_notification
    from apps.realtime.events import broadcast_inbox_event

    create_notification(
        recipient=invitation.invited_by,
        workspace=invitation.workspace,
        actor=user,
        kind="member",
        title="Einladung angenommen",
        body=f"{user.display_name} ist {invitation.workspace.name} beigetreten.",
        icon="how_to_reg",
        route="/members",
    )
    workspace_member_ids = list(
        WorkspaceMembership.objects.filter(
            workspace=invitation.workspace, is_active=True
        ).values_list("user_id", flat=True)
    )
    transaction.on_commit(
        lambda: broadcast_inbox_event(
            [invitation.invited_by_id, user.id],
            "workspace.invitation.updated",
            {
                "invitationId": str(invitation.id),
                "workspaceId": str(invitation.workspace_id),
                "status": InvitationStatus.ACCEPTED,
            },
        )
    )
    transaction.on_commit(
        lambda: broadcast_inbox_event(
            workspace_member_ids,
            "workspace.membership.updated",
            {
                "workspaceId": str(invitation.workspace_id),
                "userId": str(user.id),
            },
        )
    )
    return invitation


@transaction.atomic
def accept_invitation(*, raw_token: str, user: User) -> WorkspaceInvitation:
    """Verbraucht eine Token-Einladung genau einmal und vergibt minimale Rechte."""
    token_hash = WorkspaceInvitation.hash_token(raw_token)
    invitation = (
        WorkspaceInvitation.objects.select_for_update(of=("self",))
        .select_related("workspace", "project", "invited_by")
        .filter(token_hash=token_hash)
        .first()
    )
    return _complete_invitation_acceptance(
        invitation=_validate_invitation_for_user(invitation, user),
        user=user,
    )


@transaction.atomic
def accept_invitation_by_id(*, invitation_id: Any, user: User) -> WorkspaceInvitation:
    """Nimmt eine dem angemeldeten Konto zugeordnete In-App-Einladung an."""
    invitation = (
        WorkspaceInvitation.objects.select_for_update(of=("self",))
        .select_related("workspace", "project", "invited_by")
        .filter(pk=invitation_id)
        .first()
    )
    return _complete_invitation_acceptance(
        invitation=_validate_invitation_for_user(invitation, user),
        user=user,
    )


@transaction.atomic
def reject_invitation_by_id(*, invitation_id: Any, user: User) -> WorkspaceInvitation:
    """Lehnt eine offene In-App-Einladung ab, ohne den Eintrag zu löschen."""
    invitation = (
        WorkspaceInvitation.objects.select_for_update(of=("self",))
        .select_related("workspace", "project", "invited_by")
        .filter(pk=invitation_id)
        .first()
    )
    invitation = _validate_invitation_for_user(invitation, user)
    invitation.status = InvitationStatus.REJECTED
    invitation.save(update_fields=("status", "updated_at"))

    from apps.inbox.services import create_notification
    from apps.realtime.events import broadcast_inbox_event

    create_notification(
        recipient=invitation.invited_by,
        workspace=invitation.workspace,
        actor=user,
        kind="member",
        title="Einladung abgelehnt",
        body=f"{user.display_name} hat die Einladung zu {invitation.workspace.name} abgelehnt.",
        icon="person_cancel",
        route="/members",
    )
    transaction.on_commit(
        lambda: broadcast_inbox_event(
            [invitation.invited_by_id, user.id],
            "workspace.invitation.updated",
            {
                "invitationId": str(invitation.id),
                "workspaceId": str(invitation.workspace_id),
                "status": InvitationStatus.REJECTED,
            },
        )
    )
    return invitation
