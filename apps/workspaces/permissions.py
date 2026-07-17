# apps/workspaces/permissions.py
"""Prüft Rollen und Objektzugriffe unabhängig von Clientangaben."""

from rest_framework.exceptions import PermissionDenied

from apps.accounts.models import User
from apps.workspaces.choices import ProjectRole, WorkspaceRole
from apps.workspaces.models import Board, Project, Workspace, WorkspaceMembership


def get_membership(*, user: User, workspace: Workspace) -> WorkspaceMembership:
    """Liefert eine aktive Mitgliedschaft oder verweigert den Zugriff."""
    membership = WorkspaceMembership.objects.filter(
        workspace=workspace,
        user=user,
        is_active=True,
    ).first()
    if membership is None:
        raise PermissionDenied("Du hast keinen Zugriff auf diesen Workspace.")
    return membership


def require_workspace_manager(*, user: User, workspace: Workspace) -> WorkspaceMembership:
    """Erfordert Owner- oder Managerrechte im Workspace."""
    membership = get_membership(user=user, workspace=workspace)
    if membership.role not in {WorkspaceRole.OWNER, WorkspaceRole.MANAGER}:
        raise PermissionDenied("Für diese Aktion sind Verwaltungsrechte erforderlich.")
    return membership


def can_manage_project(*, user: User, project: Project) -> bool:
    """Prüft globale oder projektbezogene Verwaltungsrechte."""
    membership = get_membership(user=user, workspace=project.workspace)
    if (
        membership.role in {WorkspaceRole.OWNER, WorkspaceRole.MANAGER}
        or project.owner_id == user.id
    ):
        return True
    return project.participants.filter(user=user, role=ProjectRole.MANAGER).exists()


def require_project_manager(*, user: User, project: Project) -> None:
    """Verweigert strukturelle Projektänderungen ohne Managerrecht."""
    if not can_manage_project(user=user, project=project):
        raise PermissionDenied("Für diese Aktion sind Projektverwaltungsrechte erforderlich.")


def require_board_editor(*, user: User, board: Board) -> None:
    """Erlaubt persönliche Eigentümer und Projektteilnehmende als Task-Editoren."""
    if board.owner_id:
        if board.owner_id != user.id:
            raise PermissionDenied("Du darfst dieses persönliche Board nicht bearbeiten.")
        return
    if board.project is None:
        raise PermissionDenied("Das Board besitzt kein gültiges Projekt.")
    get_membership(user=user, workspace=board.workspace)
    if not (
        can_manage_project(user=user, project=board.project)
        or board.project.participants.filter(user=user).exists()
    ):
        raise PermissionDenied("Du darfst dieses Projektboard nicht bearbeiten.")
