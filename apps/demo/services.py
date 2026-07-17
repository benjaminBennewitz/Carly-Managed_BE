# apps/demo/services.py
"""Erzeugt einen reproduzierbaren Carly-Managed-Demostand in PostgreSQL."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import time, timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.inbox.models import (
    ChatMessage,
    ChatMessageKind,
    Conversation,
    ConversationParticipant,
    NotificationKind,
    SystemNotification,
)
from apps.preferences.models import CarlyMood, CarlyState, UserSettings, default_alarms
from apps.workspaces.choices import (
    AutomationTrigger,
    BoardKind,
    ColumnSystemRole,
    ProjectRole,
    ProjectStatus,
    RecurrenceScheduleType,
    TaskPriority,
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
    TaskComment,
    TaskHistoryEntry,
    TaskRecurrenceRule,
    Workspace,
    WorkspaceJoinRequest,
    WorkspaceMembership,
)

DEMO_NAMESPACE = uuid.UUID("646c12cc-6d61-4d1d-8a5c-8bf27be6246b")


@dataclass(frozen=True, slots=True)
class DemoResetResult:
    """Bündelt die für API und Kommandozeile relevanten Reset-Zahlen."""

    workspace_id: uuid.UUID
    workspace_name: str
    projects: int
    tasks: int
    members: int
    notifications: int

    def as_dict(self) -> dict[str, Any]:
        """Überführt das Ergebnis in den camelCase-API-Vertrag."""
        return {
            "workspaceId": self.workspace_id,
            "workspaceName": self.workspace_name,
            "projects": self.projects,
            "tasks": self.tasks,
            "members": self.members,
            "notifications": self.notifications,
        }


def _stable_id(owner: User, key: str) -> uuid.UUID:
    """Erzeugt je Owner und fachlichem Schlüssel reproduzierbare UUIDs."""
    return uuid.uuid5(DEMO_NAMESPACE, f"{owner.email.lower()}::{key}")


def _demo_user(*, key: str, display_name: str, email: str) -> User:
    """Erstellt technische Demo-Mitglieder ohne verwendbares Login-Passwort."""
    user, _ = User.objects.get_or_create(
        email=email.lower(),
        defaults={
            "id": uuid.uuid5(DEMO_NAMESPACE, f"demo-user::{key}"),
            "display_name": display_name,
            "privacy_acknowledged_at": timezone.now(),
            "email_verified_at": timezone.now(),
            "is_active": True,
        },
    )
    changed_fields: list[str] = []
    if user.display_name != display_name:
        user.display_name = display_name
        changed_fields.append("display_name")
    if not user.email_verified_at:
        user.email_verified_at = timezone.now()
        changed_fields.append("email_verified_at")
    if not user.privacy_acknowledged_at:
        user.privacy_acknowledged_at = timezone.now()
        changed_fields.append("privacy_acknowledged_at")
    if not user.is_active:
        user.is_active = True
        changed_fields.append("is_active")
    if user.has_usable_password():
        user.set_unusable_password()
        changed_fields.append("password")
    if changed_fields:
        user.save(update_fields=(*changed_fields,))
    return user


def _create_project(
    *,
    owner: User,
    workspace: Workspace,
    key: str,
    name: str,
    slug_label: str,
    description: str,
    color: str,
    icon: str,
    due_days: int,
    allows_on_demand_tasks: bool,
    managers: list[User],
    collaborators: list[User],
    status: str = ProjectStatus.ACTIVE,
    pinned: bool = False,
) -> tuple[Project, Board, dict[str, BoardColumn]]:
    """Erstellt Projekt, Teilnahme, Board und ein ruhiges Kanban-Grundlayout."""
    today = timezone.localdate()
    project = Project.objects.create(
        id=_stable_id(owner, f"project::{key}"),
        workspace=workspace,
        name=name,
        route_key=key,
        slug_label=slug_label,
        description=description,
        color=color,
        icon=icon,
        status=status,
        owner=owner,
        started_at=today - timedelta(days=18),
        due_at=today + timedelta(days=due_days),
        allows_on_demand_tasks=allows_on_demand_tasks,
        completed_at=timezone.now() - timedelta(days=2)
        if status == ProjectStatus.COMPLETED
        else None,
        archived_at=timezone.now() - timedelta(days=1)
        if status == ProjectStatus.ARCHIVED
        else None,
    )
    ProjectParticipant.objects.bulk_create(
        [
            *[
                ProjectParticipant(project=project, user=user, role=ProjectRole.MANAGER)
                for user in managers
                if user.id != owner.id
            ],
            *[
                ProjectParticipant(project=project, user=user, role=ProjectRole.COLLABORATOR)
                for user in collaborators
                if user.id != owner.id and user not in managers
            ],
        ]
    )
    ProjectPreference.objects.create(
        project=project,
        user=owner,
        is_pinned=pinned,
        last_opened_at=timezone.now() - timedelta(hours=3 if pinned else 30),
    )
    board = Board.objects.create(
        id=_stable_id(owner, f"board::{key}"),
        workspace=workspace,
        project=project,
        kind=BoardKind.PROJECT,
        title=name,
    )
    definitions = [
        ("backlog", "Backlog", "#8A8093"),
        ("todo", "Offen", color),
        ("progress", "In Arbeit", "#D5A646"),
        ("review", "Review", "#4E82A8"),
        ("done", "Erledigt", "#4F9572"),
    ]
    columns: dict[str, BoardColumn] = {}
    for position, (column_key, title, column_color) in enumerate(definitions):
        columns[column_key] = BoardColumn.objects.create(
            id=_stable_id(owner, f"column::{key}::{column_key}"),
            board=board,
            title=title,
            color=column_color,
            position=position,
        )
    return project, board, columns


def _create_task(
    *,
    owner: User,
    workspace: Workspace,
    board: Board,
    project: Project | None,
    column: BoardColumn,
    key: str,
    title: str,
    description: str,
    assignee: User | None,
    collaborators: list[User] | None = None,
    priority: str = TaskPriority.MEDIUM,
    due_days: int | None = 5,
    tags: list[str] | None = None,
    is_done: bool = False,
    is_shared_pool: bool = False,
    requires_review: bool = False,
    review_hint: str = "",
    created_outside_column: bool = False,
) -> Task:
    """Erstellt eine Aufgabe samt initialem, nachvollziehbarem Verlaufseintrag."""
    today = timezone.localdate()
    due_date = today + timedelta(days=due_days) if due_days is not None else None
    start_date = min(today - timedelta(days=1), due_date) if due_date else today - timedelta(days=1)
    task = Task.objects.create(
        id=_stable_id(owner, f"task::{key}"),
        workspace=workspace,
        board=board,
        project=project,
        column=column,
        owner=owner,
        assignee=assignee,
        title=title,
        description=description,
        priority=priority,
        start_date=start_date,
        due_date=due_date,
        due_time=time(16, 0) if due_date else None,
        tags=tags or [],
        position=Task.objects.filter(column=column).count(),
        is_done=is_done,
        completed_at=timezone.now() - timedelta(hours=5) if is_done else None,
        is_shared_pool=is_shared_pool,
        requires_review=requires_review,
        review_hint=review_hint,
        created_outside_column=created_outside_column,
    )
    task.collaborators.set(collaborators or [])
    TaskHistoryEntry.objects.create(
        id=_stable_id(owner, f"history::{key}::created"),
        task=task,
        actor=owner,
        action="Aufgabe erstellt",
        icon="add_task",
    )
    return task


def _seed_preferences(owner: User) -> None:
    """Setzt persönliche Einstellungen und Carly auf den definierten Demo-Ausgangsstand."""
    UserSettings.objects.update_or_create(
        user=owner,
        defaults={
            "color_vision_mode": "standard",
            "neuro_mode": False,
            "reduce_motion": False,
            "reduce_hover": False,
            "magnifier": False,
            "font_size": "normal",
            "high_contrast": False,
            "dynamic_new_columns": True,
            "tooltips_enabled": True,
            "allow_invites": True,
            "hide_real_name": False,
            "real_name": owner.display_name,
            "nickname": "Ben",
            "alarms": default_alarms(),
            "pomodoro": True,
            "task_timer": True,
            "weather": False,
            "weather_location": "Mönchengladbach",
            "version": 1,
        },
    )
    CarlyState.objects.update_or_create(
        user=owner,
        defaults={
            "enabled": True,
            "show_globally": True,
            "messages_enabled": True,
            "task_reactions_enabled": True,
            "auto_sleep": True,
            "reduce_animations": False,
            "level": 4,
            "experience": 340,
            "affection": 78,
            "energy": 73,
            "satiety": 66,
            "streak": 6,
            "mood": CarlyMood.HAPPY,
            "is_sleeping": False,
            "last_message": "Carly freut sich auf den nächsten gemeinsamen Schritt.",
            "position_x": 0.84,
            "last_productive_day": timezone.localdate(),
            "version": 1,
        },
    )
    owner.carly_actions.all().delete()


@transaction.atomic
def reset_demo_workspace(*, owner: User) -> DemoResetResult:
    """Löscht nur den Demo-Workspace des Owners und erzeugt ihn atomar neu."""
    workspace_name = settings.DEMO_WORKSPACE_NAME
    Workspace.objects.filter(owner=owner, name=workspace_name).delete()
    SystemNotification.objects.filter(
        recipient=owner, workspace__isnull=True, title__startswith="Demo:"
    ).delete()

    mira = _demo_user(key="mira", display_name="Mira König", email="mira@carly.local")
    noah = _demo_user(key="noah", display_name="Noah Peters", email="noah@carly.local")
    lea = _demo_user(key="lea", display_name="Lea Sommer", email="lea@carly.local")
    jona = _demo_user(key="jona", display_name="Jona Weber", email="jona@carly.local")
    emilia = _demo_user(key="emilia", display_name="Emilia Roth", email="emilia@carly.local")

    workspace = Workspace.objects.create(
        id=_stable_id(owner, "workspace"),
        name=workspace_name,
        owner=owner,
        allow_invites=True,
    )
    memberships = [
        (owner, WorkspaceRole.OWNER, "#7752B3"),
        (mira, WorkspaceRole.MANAGER, "#C55F7A"),
        (noah, WorkspaceRole.MEMBER, "#4E82A8"),
        (lea, WorkspaceRole.MEMBER, "#4F9572"),
    ]
    WorkspaceMembership.objects.bulk_create(
        [
            WorkspaceMembership(
                id=_stable_id(owner, f"membership::{user.email}"),
                workspace=workspace,
                user=user,
                role=role,
                avatar_color=color,
                is_active=True,
            )
            for user, role, color in memberships
        ]
    )

    carly, carly_board, carly_columns = _create_project(
        owner=owner,
        workspace=workspace,
        key="carly-managed",
        name="Carly Managed",
        slug_label="CARLY",
        description=(
            "Kollaborative Business-App mit ruhigem Kanban-Workflow "
            "und optionaler Carly-Motivation."
        ),
        color="#7752B3",
        icon="auto_awesome",
        due_days=32,
        allows_on_demand_tasks=True,
        managers=[mira],
        collaborators=[noah, lea],
        pinned=True,
    )
    portfolio, portfolio_board, portfolio_columns = _create_project(
        owner=owner,
        workspace=workspace,
        key="portfolio-relaunch",
        name="Portfolio Relaunch",
        slug_label="PORTFOLIO",
        description="Cases, Bildsprache und technische Präsentation des Portfolios überarbeiten.",
        color="#4E82A8",
        icon="web",
        due_days=14,
        allows_on_demand_tasks=False,
        managers=[owner],
        collaborators=[lea],
    )
    studio, studio_board, studio_columns = _create_project(
        owner=owner,
        workspace=workspace,
        key="studio-operations",
        name="Studio Operations",
        slug_label="STUDIO",
        description="Wiederkehrende Abläufe, Angebote und interne Verbesserungen organisieren.",
        color="#D5A646",
        icon="business_center",
        due_days=45,
        allows_on_demand_tasks=True,
        managers=[mira],
        collaborators=[noah],
    )
    archived, archived_board, archived_columns = _create_project(
        owner=owner,
        workspace=workspace,
        key="client-workspace",
        name="Client Workspace",
        slug_label="CLIENT",
        description="Abgeschlossener Kundenbereich als Archivbeispiel.",
        color="#8A8093",
        icon="inventory_2",
        due_days=1,
        allows_on_demand_tasks=False,
        managers=[owner],
        collaborators=[mira],
        status=ProjectStatus.ARCHIVED,
    )

    personal_board = Board.objects.create(
        id=_stable_id(owner, "board::personal"),
        workspace=workspace,
        kind=BoardKind.PERSONAL,
        owner=owner,
        title="Mein Board",
    )
    personal_columns: dict[str, BoardColumn] = {}
    for position, (key, title, color, system_role, is_dynamic) in enumerate(
        [
            ("today", "Heute", "#7752B3", "", False),
            ("next", "Als Nächstes", "#4E82A8", "", False),
            ("new", "Neu zugewiesen", "#D5A646", ColumnSystemRole.NEW_ASSIGNED, True),
            ("done", "Erledigt", "#4F9572", "", False),
        ]
    ):
        personal_columns[key] = BoardColumn.objects.create(
            id=_stable_id(owner, f"column::personal::{key}"),
            board=personal_board,
            title=title,
            color=color,
            position=position,
            system_role=system_role,
            is_dynamic=is_dynamic,
            is_fixed_position=bool(system_role),
        )

    _create_task(
        owner=owner,
        workspace=workspace,
        board=carly_board,
        project=carly,
        column=carly_columns["backlog"],
        key="carly-board-invitations",
        title="Board-Einladungen absichern",
        description=(
            "Einladungsablauf, Ablaufzeit, Rollenprüfung und generische "
            "Fehlermeldungen finalisieren."
        ),
        assignee=mira,
        collaborators=[owner],
        priority=TaskPriority.HIGH,
        due_days=2,
        tags=["Backend", "Security"],
    )
    task_102 = _create_task(
        owner=owner,
        workspace=workspace,
        board=carly_board,
        project=carly,
        column=carly_columns["todo"],
        key="carly-task-detail",
        title="Task-Detailansicht strukturieren",
        description=(
            "Drawer für Beschreibung, Zuweisungen, Unteraufgaben, Kommentare und Anhänge glätten."
        ),
        assignee=owner,
        collaborators=[mira, lea],
        priority=TaskPriority.HIGH,
        due_days=1,
        tags=["Frontend", "UX"],
    )
    task_103 = _create_task(
        owner=owner,
        workspace=workspace,
        board=carly_board,
        project=carly,
        column=carly_columns["progress"],
        key="carly-websocket-events",
        title="WebSocket-Ereignisse integrieren",
        description="Präsenz, Live-Cursor und Bearbeitungshinweise mit dem REST-Zustand abstimmen.",
        assignee=noah,
        collaborators=[owner],
        priority=TaskPriority.HIGH,
        due_days=3,
        tags=["Realtime", "Django Channels"],
    )
    _create_task(
        owner=owner,
        workspace=workspace,
        board=carly_board,
        project=carly,
        column=carly_columns["review"],
        key="carly-auth-review",
        title="Auth-Formulare prüfen",
        description=(
            "Fehlerzustände, CSRF-Schutz und Tastaturbedienung gegen die produktive API prüfen."
        ),
        assignee=lea,
        collaborators=[owner],
        due_days=-1,
        tags=["Security", "QA"],
    )
    task_done = _create_task(
        owner=owner,
        workspace=workspace,
        board=carly_board,
        project=carly,
        column=carly_columns["done"],
        key="carly-design-tokens",
        title="Semantische Design-Tokens dokumentieren",
        description="Farben, Typografie, Abstände und Zustände vollständig dokumentieren.",
        assignee=lea,
        due_days=-2,
        tags=["Designsystem"],
        is_done=True,
    )
    _create_task(
        owner=owner,
        workspace=workspace,
        board=portfolio_board,
        project=portfolio,
        column=portfolio_columns["todo"],
        key="portfolio-storyline",
        title="Case-Study-Storyline festlegen",
        description=(
            "Ausgangslage, Prozess, technische Entscheidungen und Ergebnis klar strukturieren."
        ),
        assignee=owner,
        due_days=7,
        tags=["Content"],
    )
    _create_task(
        owner=owner,
        workspace=workspace,
        board=portfolio_board,
        project=portfolio,
        column=portfolio_columns["progress"],
        key="portfolio-assets",
        title="Projektbilder optimieren",
        description="Screenshots responsiv zuschneiden und als performante WebP-Dateien ausgeben.",
        assignee=lea,
        due_days=5,
        tags=["Assets", "Performance"],
    )
    _create_task(
        owner=owner,
        workspace=workspace,
        board=studio_board,
        project=studio,
        column=studio_columns["backlog"],
        key="studio-offers",
        title="Angebotsvorlagen vereinheitlichen",
        description="Textbausteine, Leistungspositionen und Freigaben für Angebote bündeln.",
        assignee=mira,
        due_days=10,
        tags=["Organisation"],
        is_shared_pool=True,
    )
    _create_task(
        owner=owner,
        workspace=workspace,
        board=studio_board,
        project=studio,
        column=studio_columns["todo"],
        key="studio-review",
        title="Unzugewiesene Pool-Aufgabe prüfen",
        description="Zuständigkeit und Termin vor Übernahme in den regulären Ablauf festlegen.",
        assignee=None,
        due_days=None,
        tags=["Pool"],
        is_shared_pool=True,
        requires_review=True,
        review_hint="Ohne verantwortliche Person erstellt. Bitte Zuweisung und Termin prüfen.",
        created_outside_column=True,
    )
    _create_task(
        owner=owner,
        workspace=workspace,
        board=archived_board,
        project=archived,
        column=archived_columns["done"],
        key="client-handover",
        title="Projektübergabe abschließen",
        description="Dokumentation, Zugangsdaten und Abschlussgespräch wurden übergeben.",
        assignee=owner,
        due_days=-5,
        tags=["Abschluss"],
        is_done=True,
    )
    _create_task(
        owner=owner,
        workspace=workspace,
        board=personal_board,
        project=None,
        column=personal_columns["today"],
        key="personal-board-review",
        title="Board-Ansicht prüfen",
        description="Responsive Spaltenbreiten, Fokuszustände und Drawer-Verhalten kontrollieren.",
        assignee=owner,
        due_days=0,
        tags=["Fokus"],
    )
    _create_task(
        owner=owner,
        workspace=workspace,
        board=personal_board,
        project=None,
        column=personal_columns["next"],
        key="personal-backend",
        title="Backend-Integration dokumentieren",
        description="Startreihenfolge, API-Verträge und Reset-Prozess nachvollziehbar festhalten.",
        assignee=owner,
        due_days=3,
        tags=["Backend"],
    )

    subtasks = [
        Subtask(
            id=_stable_id(owner, "subtask::detail::layout"),
            task=task_102,
            title="Spaltenlayout übertragen",
            assignee=mira,
            is_done=True,
            position=0,
        ),
        Subtask(
            id=_stable_id(owner, "subtask::detail::drawer"),
            task=task_102,
            title="Task-Drawer an API anbinden",
            assignee=lea,
            is_done=False,
            position=1,
        ),
        Subtask(
            id=_stable_id(owner, "subtask::detail::a11y"),
            task=task_102,
            title="Tastaturbedienung prüfen",
            assignee=owner,
            is_done=False,
            position=2,
        ),
    ]
    Subtask.objects.bulk_create(subtasks)
    TaskComment.objects.bulk_create(
        [
            TaskComment(
                id=_stable_id(owner, "comment::task-detail::mira"),
                task=task_102,
                author=mira,
                body=(
                    "Die horizontale Boardfläche sollte den verfügbaren "
                    "Viewport vollständig nutzen."
                ),
            ),
            TaskComment(
                id=_stable_id(owner, "comment::websocket::owner"),
                task=task_103,
                author=owner,
                body=(
                    "Persistente Änderungen bleiben REST; Präsenz und Cursor "
                    "laufen ausschließlich über WebSockets."
                ),
            ),
        ]
    )
    TaskHistoryEntry.objects.create(
        id=_stable_id(owner, "history::design-tokens::completed"),
        task=task_done,
        actor=lea,
        action="Aufgabe abgeschlossen",
        icon="task_alt",
    )
    TaskRecurrenceRule.objects.create(
        id=_stable_id(owner, "recurrence::studio-offers"),
        task=Task.objects.get(pk=_stable_id(owner, "task::studio-offers")),
        schedule_type=RecurrenceScheduleType.WEEKLY_DAYS,
        start_date=timezone.localdate(),
        interval_value=1,
        weekdays=["MO", "TH"],
        next_run_on=timezone.localdate() + timedelta(days=2),
        is_active=True,
    )
    AutomationRule.objects.create(
        id=_stable_id(owner, "automation::carly-completed"),
        board=carly_board,
        name="Erledigte Aufgaben verschieben",
        trigger=AutomationTrigger.TASK_COMPLETED,
        conditions={
            "taskScope": "any_task",
            "sourceColumnId": None,
            "searchTerm": "",
            "dueDateMode": "any",
        },
        actions=[{"type": "move_task_tree", "targetColumnId": str(carly_columns["done"].id)}],
        is_active=True,
        sort_order=0,
    )

    WorkspaceJoinRequest.objects.bulk_create(
        [
            WorkspaceJoinRequest(
                id=_stable_id(owner, "join-request::jona"),
                workspace=workspace,
                user=jona,
                avatar_color="#B9546A",
            ),
            WorkspaceJoinRequest(
                id=_stable_id(owner, "join-request::emilia"),
                workspace=workspace,
                user=emilia,
                avatar_color="#5B6FB8",
            ),
        ]
    )

    notifications = [
        SystemNotification(
            id=_stable_id(owner, "notification::completed"),
            recipient=owner,
            workspace=workspace,
            kind=NotificationKind.TASK,
            title="Aufgabe abgeschlossen",
            body="„Semantische Design-Tokens dokumentieren“ wurde abgeschlossen.",
            icon="task_alt",
            actor=lea,
            route=f"/projects/{carly.id}/board",
            query_params={"task": str(task_done.id)},
        ),
        SystemNotification(
            id=_stable_id(owner, "notification::assignment"),
            recipient=owner,
            workspace=workspace,
            kind=NotificationKind.TASK,
            title="Neue Zuweisung",
            body="Dir wurde die Aufgabe „Task-Detailansicht strukturieren“ zugewiesen.",
            icon="assignment_ind",
            actor=mira,
            route=f"/projects/{carly.id}/board",
            query_params={"task": str(task_102.id)},
        ),
        SystemNotification(
            id=_stable_id(owner, "notification::project"),
            recipient=owner,
            workspace=workspace,
            kind=NotificationKind.PROJECT,
            title="Projekt geändert",
            body="Laufzeit und Rollen von „Portfolio Relaunch“ wurden aktualisiert.",
            icon="edit_note",
            actor=mira,
            route=f"/projects/{portfolio.id}/board",
            query_params={},
            read_at=timezone.now() - timedelta(hours=3),
        ),
    ]
    SystemNotification.objects.bulk_create(notifications)

    conversation = Conversation.objects.create(
        id=_stable_id(owner, "conversation::release"),
        workspace=workspace,
        created_by=owner,
    )
    ConversationParticipant.objects.bulk_create(
        [
            ConversationParticipant(
                id=_stable_id(owner, f"conversation-participant::{user.email}"),
                conversation=conversation,
                user=user,
                last_read_at=timezone.now() if user == owner else None,
            )
            for user in [owner, mira, noah, lea]
        ]
    )
    ChatMessage.objects.bulk_create(
        [
            ChatMessage(
                id=_stable_id(owner, "message::release::1"),
                conversation=conversation,
                kind=ChatMessageKind.MESSAGE,
                sender=noah,
                subject="Release-Abstimmung",
                body="Können wir die letzte Accessibility-Runde morgen gemeinsam prüfen?",
            ),
            ChatMessage(
                id=_stable_id(owner, "message::release::2"),
                conversation=conversation,
                kind=ChatMessageKind.MESSAGE,
                sender=lea,
                body="Ja, ich übernehme Tastaturbedienung und Fokuszustände.",
            ),
        ]
    )

    _seed_preferences(owner)

    return DemoResetResult(
        workspace_id=workspace.id,
        workspace_name=workspace.name,
        projects=workspace.projects.count(),
        tasks=workspace.tasks.count(),
        members=workspace.memberships.filter(is_active=True).count(),
        notifications=workspace.system_notifications.count(),
    )
