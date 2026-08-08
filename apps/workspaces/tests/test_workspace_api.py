# apps/workspaces/tests/test_workspace_api.py
"""Prüft Autorisierung, Versionierung und zentrale Workspace-Verträge."""

from datetime import timedelta

import pytest
from django.db.models import Max
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.workspaces.models import (
    Board,
    BoardColumn,
    ProjectParticipant,
    Task,
    Workspace,
    WorkspaceMembership,
)
from apps.workspaces.services import bootstrap_personal_workspace

pytestmark = pytest.mark.django_db

PASSWORD = "Fokus!Board-2026-sicher"


def create_user(email: str, display_name: str) -> User:
    """Erstellt einen gültigen Testnutzer samt persönlichem Workspace."""
    user = User.objects.create_user(
        email=email,
        password=PASSWORD,
        display_name=display_name,
        privacy_acknowledged_at=timezone.now(),
    )
    bootstrap_personal_workspace(user)
    return user


def auth_client(user: User) -> APIClient:
    """Authentifiziert einen DRF-Testclient direkt für Fachtests."""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def test_user_cannot_read_foreign_personal_board_or_task() -> None:
    """Verhindert IDOR-Zugriffe trotz bekannter UUIDs."""
    owner = create_user("owner@example.test", "Owner")
    stranger = create_user("stranger@example.test", "Stranger")
    board = Board.objects.get(owner=owner)
    column = board.columns.first()
    task = Task.objects.create(
        workspace=board.workspace,
        board=board,
        column=column,
        owner=owner,
        title="Vertraulicher Task",
    )

    client = auth_client(stranger)
    assert client.get(reverse("board-detail", args=[board.id])).status_code == 404
    assert client.get(reverse("task-detail", args=[task.id])).status_code == 404


def test_task_create_validates_membership_and_relations() -> None:
    """Akzeptiert Zuweisungen ausschließlich innerhalb des aktuellen Workspaces."""
    owner = create_user("owner@example.test", "Owner")
    external = create_user("external@example.test", "External")
    board = Board.objects.get(owner=owner)
    client = auth_client(owner)

    rejected = client.post(
        reverse("task-list"),
        {
            "boardId": str(board.id),
            "title": "Nicht erlaubte Zuweisung",
            "assigneeId": str(external.id),
        },
        format="json",
    )
    assert rejected.status_code == 400
    assert Task.objects.filter(title="Nicht erlaubte Zuweisung").exists() is False

    accepted = client.post(
        reverse("task-list"),
        {
            "boardId": str(board.id),
            "title": "Sauber validierter Task",
            "description": "Wird serverseitig gespeichert.",
            "priority": "hoch",
            "tags": ["Backend", "Security"],
        },
        format="json",
    )
    assert accepted.status_code == 201
    assert accepted.data["title"] == "Sauber validierter Task"
    assert accepted.data["version"] == 1


def test_frontend_task_payload_accepts_empty_review_hint() -> None:
    """Akzeptiert den vollständigen Create-Vertrag des Frontends für persönliche Tasks."""
    owner = create_user("owner-frontend-task@example.test", "Owner Task")
    board = Board.objects.get(owner=owner)
    intake = board.columns.get(system_role="new-assigned")

    response = auth_client(owner).post(
        reverse("task-list"),
        {
            "boardId": str(board.id),
            "columnId": str(intake.id),
            "title": "Frontend Task",
            "description": "",
            "assigneeId": str(owner.id),
            "collaboratorIds": [],
            "priority": "mittel",
            "dueDate": str(timezone.localdate() + timedelta(days=7)),
            "tags": [],
            "isSharedPool": False,
            "requiresReview": False,
            "reviewHint": None,
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.data["title"] == "Frontend Task"
    assert response.data["reviewHint"] == ""


def test_personal_task_creation_always_uses_intake_column() -> None:
    """Leitet neue persönliche Aufgaben unabhängig vom Request in die Neu-Spalte."""
    owner = create_user("owner-personal-intake@example.test", "Owner Intake")
    board = Board.objects.get(owner=owner)
    regular_column = board.columns.exclude(system_role="new-assigned").first()

    response = auth_client(owner).post(
        reverse("task-list"),
        {
            "boardId": str(board.id),
            "columnId": str(regular_column.id),
            "title": "Immer zuerst Neu",
            "assigneeId": str(owner.id),
        },
        format="json",
    )

    assert response.status_code == 201
    task = Task.objects.get(pk=response.data["id"])
    assert task.column.system_role == "new-assigned"


def test_project_assignment_is_mirrored_to_personal_new_column() -> None:
    """Spiegelt Projektzuweisungen in die persönliche Neu-Spalte des Empfängers."""
    owner = create_user("owner-assignment@example.test", "Owner Assignment")
    member = create_user("julia-assignment@example.test", "Julia Assignment")
    workspace = owner.owned_workspaces.get()
    WorkspaceMembership.objects.create(
        workspace=workspace, user=member, role="member", avatar_color="#6558d3"
    )
    created = auth_client(owner).post(
        reverse("project-list"),
        {
            "workspaceId": str(workspace.id),
            "name": "Geteiltes Projekt",
            "dueAt": str(timezone.localdate() + timedelta(days=30)),
        },
        format="json",
    )
    assert created.status_code == 201
    project = workspace.projects.get(pk=created.data["id"])

    task_response = auth_client(owner).post(
        reverse("task-list"),
        {
            "boardId": str(project.board.id),
            "columnId": str(project.board.columns.first().id),
            "title": "Julia übernimmt",
            "assigneeId": str(member.id),
            "reviewHint": None,
        },
        format="json",
    )

    assert task_response.status_code == 201
    assert ProjectParticipant.objects.filter(
        project=project, user=member, role="collaborator"
    ).exists()
    visible_projects = auth_client(member).get(reverse("project-list"))
    visible_project_data = (
        visible_projects.data["results"]
        if isinstance(visible_projects.data, dict)
        else visible_projects.data
    )
    assert any(item["id"] == str(project.id) for item in visible_project_data)

    source = Task.objects.get(pk=task_response.data["id"])
    mirror = Task.objects.get(source_task=source, source_subtask__isnull=True)
    assert mirror.board.owner == member
    assert mirror.board.workspace.owner == member
    assert Board.objects.filter(owner=member, kind="personal").count() == 1
    assert mirror.column.system_role == "new-assigned"
    assert mirror.assignee == member
    assert mirror.title == source.title


def test_stale_task_update_returns_conflict() -> None:
    """Verhindert Lost Updates über eine optimistische Versionsnummer."""
    owner = create_user("owner@example.test", "Owner")
    board = Board.objects.get(owner=owner)
    column = board.columns.first()
    task = Task.objects.create(
        workspace=board.workspace,
        board=board,
        column=column,
        owner=owner,
        title="Ausgangstitel",
    )
    client = auth_client(owner)

    first = client.patch(
        reverse("task-detail", args=[task.id]),
        {"title": "Erste Änderung", "version": 1},
        format="json",
    )
    assert first.status_code == 200
    assert first.data["version"] == 2

    stale = client.patch(
        reverse("task-detail", args=[task.id]),
        {"title": "Veraltete Änderung", "version": 1},
        format="json",
    )
    assert stale.status_code == 409
    assert stale.data["code"] == "version_conflict"
    task.refresh_from_db()
    assert task.title == "Erste Änderung"


def test_project_creation_builds_board_and_standard_columns() -> None:
    """Erstellt Projektaggregate innerhalb einer einzigen Fachoperation."""
    owner = create_user("owner@example.test", "Owner")
    workspace = owner.owned_workspaces.get()
    client = auth_client(owner)

    response = client.post(
        reverse("project-list"),
        {
            "workspaceId": str(workspace.id),
            "name": "Portfolio Launch",
            "slugLabel": "Portfolio",
            "description": "Neues Portfolio veröffentlichen.",
            "dueAt": str(timezone.localdate() + timedelta(days=30)),
            "color": "#6558d3",
            "icon": "rocket_launch",
        },
        format="json",
    )
    assert response.status_code == 201
    project = workspace.projects.get(name="Portfolio Launch")
    assert project.board.columns.count() == 3
    assert project.owner == owner


def test_project_update_grants_collaborator_visibility() -> None:
    """Speichert Projektteilnehmer und macht das Projekt für sie sichtbar."""
    owner = create_user("owner@example.test", "Owner")
    collaborator = create_user("julia@example.test", "Julia")
    workspace = owner.owned_workspaces.get()
    WorkspaceMembership.objects.create(
        workspace=workspace,
        user=collaborator,
        role="member",
        avatar_color="#6558d3",
    )
    owner_client = auth_client(owner)
    created = owner_client.post(
        reverse("project-list"),
        {
            "workspaceId": str(workspace.id),
            "name": "Gemeinsames Projekt",
            "slugLabel": "Gemeinsam",
            "dueAt": str(timezone.localdate() + timedelta(days=30)),
        },
        format="json",
    )
    assert created.status_code == 201

    updated = owner_client.patch(
        reverse("project-detail", args=[created.data["id"]]),
        {
            "managerIds": [],
            "collaboratorIds": [str(collaborator.id)],
            "version": created.data["version"],
        },
        format="json",
    )

    assert updated.status_code == 200
    assert [member["id"] for member in updated.data["collaborators"]] == [
        str(collaborator.id)
    ]

    visible = auth_client(collaborator).get(
        reverse("project-list"), {"workspaceId": str(workspace.id)}
    )
    assert visible.status_code == 200
    data = visible.data["results"] if isinstance(visible.data, dict) else visible.data
    assert [item["id"] for item in data] == [created.data["id"]]


def test_regular_member_can_create_own_project_but_does_not_gain_workspace_management() -> None:
    """Erlaubt eigene Projekte ohne daraus globale Workspace-Rechte abzuleiten."""
    owner = create_user("owner@example.test", "Owner")
    member = create_user("member@example.test", "Member")
    workspace = owner.owned_workspaces.get()
    WorkspaceMembership.objects.create(
        workspace=workspace,
        user=member,
        role="member",
        avatar_color="#6558d3",
    )
    client = auth_client(member)
    response = client.post(
        reverse("project-list"),
        {
            "workspaceId": str(workspace.id),
            "name": "Eigenes Projekt",
            "dueAt": str(timezone.localdate() + timedelta(days=10)),
            "ownerId": str(owner.id),
        },
        format="json",
    )
    assert response.status_code == 201
    assert response.data["owner"]["id"] == str(member.id)

    project_board = Board.objects.get(project_id=response.data["id"])
    task_response = client.post(
        reverse("task-list"),
        {
            "boardId": str(project_board.id),
            "columnId": str(project_board.columns.first().id),
            "title": "Eigene Aufgabe",
        },
        format="json",
    )
    assert task_response.status_code == 201
    assert task_response.data["owner"]["id"] == str(member.id)

    forbidden_invite = client.post(
        reverse("invitation-list"),
        {"workspaceId": str(workspace.id), "email": "third@example.test", "projectId": None},
        format="json",
    )
    assert forbidden_invite.status_code == 403


def test_private_attachment_requires_task_access(settings, tmp_path) -> None:
    """Streamt Uploads nicht über öffentliche Media-URLs an Fremde."""
    settings.MEDIA_ROOT = tmp_path
    owner = create_user("owner@example.test", "Owner")
    stranger = create_user("stranger@example.test", "Stranger")
    board = Board.objects.get(owner=owner)
    task = Task.objects.create(
        workspace=board.workspace,
        board=board,
        column=board.columns.first(),
        owner=owner,
        title="Task mit Datei",
    )
    owner_client = auth_client(owner)
    upload = SimpleUploadedFile(
        "notiz.pdf",
        b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF",
        content_type="application/pdf",
    )
    created = owner_client.post(
        reverse("task-attachments", args=[task.id]),
        {"files": [upload]},
        format="multipart",
    )
    assert created.status_code == 201
    attachment_id = created.data[0]["id"]

    stranger_client = auth_client(stranger)
    denied = stranger_client.get(reverse("attachment-download", args=[attachment_id]))
    assert denied.status_code == 404
    allowed = owner_client.get(reverse("attachment-download", args=[attachment_id]))
    assert allowed.status_code == 200
    assert allowed.headers["X-Content-Type-Options"] == "nosniff"


def test_subtask_assignment_creates_personal_mirror_for_member() -> None:
    """Spiegelt zugewiesene Projekt-Unteraufgaben in die persönliche Neu-Spalte."""
    owner = create_user("owner@example.test", "Owner")
    member = create_user("member@example.test", "Member")
    workspace = owner.owned_workspaces.get()
    WorkspaceMembership.objects.create(
        workspace=workspace,
        user=member,
        role="member",
        avatar_color="#6558d3",
    )
    project_response = auth_client(owner).post(
        reverse("project-list"),
        {
            "workspaceId": str(workspace.id),
            "name": "Unteraufgaben-Projekt",
            "dueAt": str(timezone.localdate() + timedelta(days=30)),
        },
        format="json",
    )
    assert project_response.status_code == 201
    project = workspace.projects.get(pk=project_response.data["id"])
    ProjectParticipant.objects.create(project=project, user=member, role="collaborator")
    task = Task.objects.create(
        workspace=workspace,
        board=project.board,
        column=project.board.columns.first(),
        project=project,
        owner=owner,
        title="Hauptaufgabe",
    )

    response = auth_client(owner).post(
        reverse("task-subtasks", args=[task.id]),
        {"title": "Teilaufgabe", "assigneeId": str(member.id)},
        format="json",
    )

    assert response.status_code == 201
    subtask = task.subtasks.get()
    mirror = Task.objects.get(source_subtask=subtask, assignee=member)
    assert mirror.board.owner == member
    assert mirror.board.workspace.owner == member
    assert Board.objects.filter(owner=member, kind="personal").count() == 1
    assert mirror.column.system_role == "new-assigned"


def test_workspace_manager_can_remove_regular_member() -> None:
    """Deaktiviert Mitgliedschaft und Projektzugriffe ohne Nutzerkonto zu löschen."""
    owner = create_user("owner-remove@example.test", "Owner")
    member = create_user("member-remove@example.test", "Member")
    workspace = owner.owned_workspaces.get()
    membership = WorkspaceMembership.objects.create(
        workspace=workspace,
        user=member,
        role="member",
        avatar_color="#6558d3",
    )

    response = auth_client(owner).delete(
        reverse("workspace-members", args=[workspace.id]),
        {"memberId": str(member.id)},
        format="json",
    )

    assert response.status_code == 204
    membership.refresh_from_db()
    assert membership.is_active is False
    assert User.objects.filter(pk=member.pk).exists() is True


def test_workspace_owner_cannot_remove_self() -> None:
    """Schützt den einzigen Workspace-Owner vor versehentlicher Selbstentfernung."""
    owner = create_user("owner-self@example.test", "Owner")
    workspace = owner.owned_workspaces.get()

    response = auth_client(owner).delete(
        reverse("workspace-members", args=[workspace.id]),
        {"memberId": str(owner.id)},
        format="json",
    )

    assert response.status_code == 409
    assert WorkspaceMembership.objects.get(workspace=workspace, user=owner).is_active is True


def test_registered_user_can_accept_in_app_invitation_without_email_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Erlaubt bestehenden Konten die Einladung direkt in der App statt per Mail-Link."""
    owner = create_user("owner-invite@example.test", "Owner Invite")
    invitee = create_user("invitee-invite@example.test", "Invitee")
    workspace = owner.owned_workspaces.get()
    owner_client = auth_client(owner)
    mail_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "apps.workspaces.services.send_mail",
        lambda **kwargs: mail_calls.append(kwargs),
    )

    created = owner_client.post(
        reverse("invitation-list"),
        {
            "workspaceId": str(workspace.id),
            "email": invitee.email,
            "projectId": None,
        },
        format="json",
    )
    assert created.status_code == 201
    assert created.data["fullName"] == invitee.display_name
    assert invitee.email_verified is False
    assert mail_calls == []

    received = auth_client(invitee).get(reverse("invitation-list"), {"scope": "received"})
    assert received.status_code == 200
    assert len(received.data["results"] if isinstance(received.data, dict) else received.data) == 1
    invitation_id = created.data["id"]

    accepted = auth_client(invitee).post(
        reverse("invitation-accept-received", args=[invitation_id]),
        {},
        format="json",
    )
    assert accepted.status_code == 200
    assert accepted.data["status"] == "accepted"
    assert WorkspaceMembership.objects.filter(
        workspace=workspace,
        user=invitee,
        is_active=True,
    ).exists()
    personal_board = Board.objects.get(owner=invitee, kind="personal")
    assert personal_board.workspace.owner == invitee
    assert Board.objects.filter(owner=invitee, kind="personal").count() == 1
    assert (
        Board.objects.filter(workspace=workspace, owner=invitee, kind="personal").exists()
        is False
    )
    personal_task = auth_client(invitee).post(
        reverse("task-list"),
        {
            "boardId": str(personal_board.id),
            "columnId": str(personal_board.columns.first().id),
            "title": "Eigene persönliche Aufgabe",
        },
        format="json",
    )
    assert personal_task.status_code == 201
    assert personal_task.data["owner"]["id"] == str(invitee.id)


def test_registered_user_can_reject_in_app_invitation() -> None:
    """Speichert eine Ablehnung sichtbar für die einladende Person."""
    owner = create_user("owner-reject@example.test", "Owner Reject")
    invitee = create_user("invitee-reject@example.test", "Reject Invitee")
    workspace = owner.owned_workspaces.get()
    created = auth_client(owner).post(
        reverse("invitation-list"),
        {
            "workspaceId": str(workspace.id),
            "fullName": invitee.display_name,
            "email": invitee.email,
            "projectId": None,
        },
        format="json",
    )

    rejected = auth_client(invitee).post(
        reverse("invitation-reject-received", args=[created.data["id"]]),
        {},
        format="json",
    )
    assert rejected.status_code == 200
    assert rejected.data["status"] == "rejected"

    sent = auth_client(owner).get(
        reverse("invitation-list"),
        {"scope": "sent", "workspaceId": str(workspace.id)},
    )
    data = sent.data["results"] if isinstance(sent.data, dict) else sent.data
    assert data[0]["status"] == "rejected"


def test_board_and_archived_task_lists_are_workspace_scoped() -> None:
    """Hält das globale persönliche Board aus fremden Team-Kontexten heraus."""
    owner = create_user("scope-owner@example.test", "Scope Owner")
    member = create_user("scope-member@example.test", "Scope Member")
    team_workspace = owner.owned_workspaces.get()
    personal_workspace = member.owned_workspaces.get()
    WorkspaceMembership.objects.create(
        workspace=team_workspace, user=member, role="member", avatar_color="#6558d3"
    )
    from apps.workspaces.services import ensure_personal_board_for_workspace

    team_board = ensure_personal_board_for_workspace(user=member, workspace=team_workspace)
    personal_board = Board.objects.get(workspace=personal_workspace, owner=member)
    assert team_board.id == personal_board.id
    assert Board.objects.filter(owner=member, kind="personal").count() == 1

    personal_task = Task.objects.create(
        workspace=personal_workspace,
        board=personal_board,
        column=personal_board.columns.first(),
        owner=member,
        title="Privater Archivtask",
        archived_at=timezone.now(),
    )

    client = auth_client(member)
    boards = client.get(reverse("board-list"), {"workspaceId": str(team_workspace.id)})
    assert boards.status_code == 200
    board_data = boards.data["results"] if isinstance(boards.data, dict) else boards.data
    assert str(personal_board.id) not in [item["id"] for item in board_data]

    archived = client.get(
        reverse("task-list"),
        {"workspaceId": str(team_workspace.id), "archived": "true"},
    )
    assert archived.status_code == 200
    archived_data = archived.data["results"] if isinstance(archived.data, dict) else archived.data
    assert str(personal_task.id) not in [item["id"] for item in archived_data]


def test_task_move_maps_frontend_target_position_to_service_argument() -> None:
    """Verhindert den 500er durch camelCase-Daten beim positionsgenauen Verschieben."""
    owner = create_user("owner-move@example.test", "Owner Move")
    board = Board.objects.get(owner=owner)
    source_column, target_column = list(board.columns.order_by("position")[:2])
    task = Task.objects.create(
        workspace=board.workspace,
        board=board,
        column=source_column,
        owner=owner,
        title="Verschiebbarer Task",
    )

    response = auth_client(owner).post(
        reverse("task-move", args=[task.id]),
        {
            "targetColumnId": str(target_column.id),
            "targetPosition": 0,
            "version": task.version,
        },
        format="json",
    )

    assert response.status_code == 200
    task.refresh_from_db()
    assert task.column_id == target_column.id


def test_workspace_visible_project_is_available_to_regular_team_members() -> None:
    """Erlaubt teamweite Projekte, ohne persönliche Boards des Teams freizugeben."""
    owner = create_user("owner-teamwide@example.test", "Owner Teamwide")
    member = create_user("member-teamwide@example.test", "Member Teamwide")
    workspace = owner.owned_workspaces.get()
    WorkspaceMembership.objects.create(
        workspace=workspace, user=member, role="member", avatar_color="#6558d3"
    )
    created = auth_client(owner).post(
        reverse("project-list"),
        {
            "workspaceId": str(workspace.id),
            "name": "Teamweites Projekt",
            "visibility": "workspace",
            "dueAt": str(timezone.localdate() + timedelta(days=30)),
        },
        format="json",
    )
    assert created.status_code == 201

    projects = auth_client(member).get(reverse("project-list"))
    assert projects.status_code == 200
    project_data = projects.data["results"] if isinstance(projects.data, dict) else projects.data
    project_item = next(item for item in project_data if item["id"] == created.data["id"] )
    assert project_item["visibility"] == "workspace"

    project = workspace.projects.get(pk=created.data["id"] )
    created_task = auth_client(member).post(
        reverse("task-list"),
        {
            "boardId": str(project.board.id),
            "title": "Teamweiter Task",
        },
        format="json",
    )
    assert created_task.status_code == 201

    owner_personal_board = Board.objects.get(owner=owner, kind="personal")
    assert auth_client(member).get(
        reverse("board-detail", args=[owner_personal_board.id])
    ).status_code == 404


def test_project_manager_can_invite_to_project_without_workspace_admin_role() -> None:
    """Trennt Projekteinladungen von globalen Workspace-Verwaltungsrechten."""
    owner = create_user("owner-project-invite@example.test", "Owner Project Invite")
    manager = create_user("manager-project-invite@example.test", "Manager Project Invite")
    invitee = create_user("invitee-project-invite@example.test", "Invitee Project Invite")
    workspace = owner.owned_workspaces.get()
    WorkspaceMembership.objects.create(
        workspace=workspace, user=manager, role="member", avatar_color="#6558d3"
    )
    project_response = auth_client(owner).post(
        reverse("project-list"),
        {
            "workspaceId": str(workspace.id),
            "name": "Projekt mit Manager",
            "dueAt": str(timezone.localdate() + timedelta(days=30)),
        },
        format="json",
    )
    assert project_response.status_code == 201
    project = workspace.projects.get(pk=project_response.data["id"] )
    ProjectParticipant.objects.create(project=project, user=manager, role="manager")

    manager_client = auth_client(manager)
    workspace_invite = manager_client.post(
        reverse("invitation-list"),
        {
            "workspaceId": str(workspace.id),
            "email": invitee.email,
            "projectId": None,
        },
        format="json",
    )
    assert workspace_invite.status_code == 403

    project_invite = manager_client.post(
        reverse("invitation-list"),
        {
            "workspaceId": str(workspace.id),
            "email": invitee.email,
            "projectId": str(project.id),
        },
        format="json",
    )
    assert project_invite.status_code == 201

    accepted = auth_client(invitee).post(
        reverse("invitation-accept-received", args=[project_invite.data["id"]]),
        {},
        format="json",
    )
    assert accepted.status_code == 200
    guest_membership = WorkspaceMembership.objects.get(
        workspace=workspace, user=invitee, is_active=True
    )
    assert guest_membership.is_project_guest is True
    assert ProjectParticipant.objects.filter(
        project=project, user=invitee, role="collaborator"
    ).exists()
    workspace_list = auth_client(invitee).get(reverse("workspace-list"))
    workspace_items = (
        workspace_list.data["results"]
        if isinstance(workspace_list.data, dict)
        else workspace_list.data
    )
    assert all(item["id"] != str(workspace.id) for item in workspace_items)
    member_list = auth_client(owner).get(reverse("workspace-members", args=[workspace.id]))
    assert all(item["id"] != str(invitee.id) for item in member_list.data)

    teamwide = auth_client(owner).post(
        reverse("project-list"),
        {
            "workspaceId": str(workspace.id),
            "name": "Anderes teamweites Projekt",
            "visibility": "workspace",
            "dueAt": str(timezone.localdate() + timedelta(days=30)),
        },
        format="json",
    )
    assert teamwide.status_code == 201
    visible_projects = auth_client(invitee).get(reverse("project-list"))
    visible_items = (
        visible_projects.data["results"]
        if isinstance(visible_projects.data, dict)
        else visible_projects.data
    )
    visible_ids = {item["id"] for item in visible_items}
    assert str(project.id) in visible_ids
    assert teamwide.data["id"] not in visible_ids

    team_invite = auth_client(owner).post(
        reverse("invitation-list"),
        {
            "workspaceId": str(workspace.id),
            "email": invitee.email,
            "projectId": None,
        },
        format="json",
    )
    assert team_invite.status_code == 201
    team_accept = auth_client(invitee).post(
        reverse("invitation-accept-received", args=[team_invite.data["id"]]),
        {},
        format="json",
    )
    assert team_accept.status_code == 200
    guest_membership.refresh_from_db()
    assert guest_membership.is_project_guest is False
    upgraded_projects = auth_client(invitee).get(reverse("project-list"))
    upgraded_items = (
        upgraded_projects.data["results"]
        if isinstance(upgraded_projects.data, dict)
        else upgraded_projects.data
    )
    assert teamwide.data["id"] in {item["id"] for item in upgraded_items}
    assert Board.objects.filter(owner=invitee, kind="personal").count() == 1
    assert Board.objects.get(owner=invitee, kind="personal").workspace.owner == invitee


def test_members_endpoint_uses_app_presence_from_inbox_socket_cache() -> None:
    """Zeigt Nutzer auch außerhalb eines Boards als online an."""
    from apps.realtime.presence import join_app_presence, leave_app_presence

    owner = create_user("owner-presence@example.test", "Owner Presence")
    member = create_user("member-presence@example.test", "Member Presence")
    workspace = owner.owned_workspaces.get()
    WorkspaceMembership.objects.create(
        workspace=workspace,
        user=member,
        role="member",
        avatar_color="#6558d3",
    )
    join_app_presence(member.id)
    try:
        response = auth_client(owner).get(reverse("workspace-members", args=[workspace.id]))
        assert response.status_code == 200
        payload = {item["id"]: item for item in response.data}
        assert payload[str(member.id)]["isOnline"] is True
    finally:
        leave_app_presence(member.id)


def test_personal_quick_task_can_be_handed_to_team_member() -> None:
    """Legt eine persönliche Schnellaufgabe direkt im privaten Intake des Empfängers ab."""
    owner = create_user("owner-handoff@example.test", "Owner Handoff")
    member = create_user("member-handoff@example.test", "Member Handoff")
    team = Workspace.objects.get(owner=owner)
    WorkspaceMembership.objects.create(
        workspace=team,
        user=member,
        role="member",
        avatar_color="#6558d3",
    )
    owner_board = Board.objects.get(owner=owner)

    response = auth_client(owner).post(
        reverse("task-list"),
        {
            "boardId": str(owner_board.id),
            "title": "Direkt an Julia",
            "assigneeId": str(member.id),
        },
        format="json",
    )

    assert response.status_code == 201
    task = Task.objects.get(pk=response.data["id"])
    assert task.assignee == member
    assert task.board.owner == member
    assert task.column.system_role == "new-assigned"
    assert Board.objects.filter(owner=member, kind="personal").count() == 1


def test_pool_task_claim_moves_canonical_task_to_personal_intake() -> None:
    """Entfernt eine übernommene Poolaufgabe aus dem Pool und legt sie nur privat ab."""
    owner = create_user("owner-pool-claim@example.test", "Owner Pool")
    team = Workspace.objects.get(owner=owner)
    project_response = auth_client(owner).post(
        reverse("project-list"),
        {
            "workspaceId": str(team.id),
            "name": "Pool Projekt",
            "dueAt": str(timezone.localdate() + timedelta(days=14)),
        },
        format="json",
    )
    project = team.projects.get(pk=project_response.data["id"])
    pool_response = auth_client(owner).post(
        reverse("task-list"),
        {
            "boardId": str(project.board.id),
            "title": "Pool Aufgabe",
            "assigneeId": None,
            "isSharedPool": True,
        },
        format="json",
    )
    task_id = pool_response.data["id"]

    claimed = auth_client(owner).post(
        reverse("task-claim", args=[task_id]),
        {"assigneeId": str(owner.id)},
        format="json",
    )

    assert claimed.status_code == 200
    task = Task.objects.get(pk=task_id)
    assert task.is_shared_pool is False
    assert task.project is None
    assert task.board.owner == owner
    assert task.column.system_role == "new-assigned"
    pool = auth_client(owner).get(reverse("task-list"), {"pool": "true"})
    assert all(item["id"] != str(task.id) for item in pool.data["results"])


def test_column_with_tasks_can_be_moved_and_deleted_atomically() -> None:
    """Bietet für belegte Spalten einen sicheren Move-and-delete-Vertrag."""
    owner = create_user("owner-column-delete@example.test", "Owner Column")
    board = Board.objects.get(owner=owner)
    target = board.columns.exclude(system_role="new-assigned").first()
    maximum_position = board.columns.aggregate(value=Max("position"))["value"]
    source = BoardColumn.objects.create(
        board=board,
        title="Temporär",
        color="#7752B3",
        position=0 if maximum_position is None else maximum_position + 1,
    )
    task = Task.objects.create(
        workspace=board.workspace,
        board=board,
        column=source,
        owner=owner,
        assignee=owner,
        title="Vor dem Löschen verschieben",
    )
    client = auth_client(owner)

    blocked = client.delete(
        f'{reverse("column-detail", args=[source.id])}?version={source.version}'
    )
    assert blocked.status_code == 409

    deleted = client.post(
        reverse("column-delete-with-move", args=[source.id]),
        {"targetColumnId": str(target.id), "version": source.version},
        format="json",
    )

    assert deleted.status_code == 204
    assert BoardColumn.objects.filter(pk=source.id).exists() is False
    task.refresh_from_db()
    assert task.column == target
    positions = list(
        board.columns.order_by("position").values_list("position", flat=True)
    )
    assert positions == list(range(len(positions)))


def test_team_owner_can_create_update_and_delete_additional_team() -> None:
    """Deckt den vollständigen Team-Lebenszyklus ohne neues persönliches Board ab."""
    owner = create_user("owner-team-crud@example.test", "Owner Teams")
    client = auth_client(owner)
    personal_board_id = Board.objects.get(owner=owner).id

    created = client.post(
        reverse("workspace-list"),
        {"name": "Design Crew", "allowInvites": False},
        format="json",
    )
    assert created.status_code == 201
    team_id = created.data["id"]
    assert created.data["allowInvites"] is False
    assert created.data["isPersonalHome"] is False
    assert Board.objects.get(owner=owner).id == personal_board_id

    updated = client.patch(
        reverse("workspace-detail", args=[team_id]),
        {
            "name": "Design Crew Plus",
            "allowInvites": True,
            "version": created.data["version"],
        },
        format="json",
    )
    assert updated.status_code == 200
    assert updated.data["name"] == "Design Crew Plus"
    assert updated.data["allowInvites"] is True

    deleted = client.delete(
        f'{reverse("workspace-detail", args=[team_id])}?version={updated.data["version"]}'
    )
    assert deleted.status_code == 204
    assert Workspace.objects.filter(pk=team_id).exists() is False


def test_disabled_team_invites_block_manager_but_not_project_manager_invites() -> None:
    """Trennt Team-Einladungsrecht von rein projektbezogenen Verwaltungsrechten."""
    owner = create_user("owner-invite-policy@example.test", "Owner Invite")
    manager = create_user("manager-invite-policy@example.test", "Manager Invite")
    invitee = create_user("invitee-policy@example.test", "Invitee Policy")
    team = Workspace.objects.get(owner=owner)
    team.allow_invites = False
    team.save(update_fields=("allow_invites", "updated_at"))
    WorkspaceMembership.objects.create(
        workspace=team,
        user=manager,
        role="manager",
        avatar_color="#6558d3",
    )
    project_response = auth_client(owner).post(
        reverse("project-list"),
        {
            "workspaceId": str(team.id),
            "name": "Manager Projekt",
            "dueAt": str(timezone.localdate() + timedelta(days=14)),
        },
        format="json",
    )
    project = team.projects.get(pk=project_response.data["id"])
    ProjectParticipant.objects.create(project=project, user=manager, role="manager")

    team_invite = auth_client(manager).post(
        reverse("invitation-list"),
        {"workspaceId": str(team.id), "email": invitee.email},
        format="json",
    )
    assert team_invite.status_code == 409

    project_invite = auth_client(manager).post(
        reverse("invitation-list"),
        {
            "workspaceId": str(team.id),
            "projectId": str(project.id),
            "email": invitee.email,
        },
        format="json",
    )
    assert project_invite.status_code == 201
