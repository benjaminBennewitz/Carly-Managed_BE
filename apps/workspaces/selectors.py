# apps/workspaces/selectors.py
"""Kapselt wiederverwendbare, berechtigungsbewusste Datenbankabfragen."""

from django.db.models import Q, QuerySet

from apps.accounts.models import User
from apps.workspaces.choices import WorkspaceRole
from apps.workspaces.models import Board, Project, Task, Workspace, WorkspaceMembership


def memberships_for_user(user: User) -> QuerySet[WorkspaceMembership]:
    """Liefert ausschließlich aktive Mitgliedschaften eines Nutzers."""
    return WorkspaceMembership.objects.filter(user=user, is_active=True).select_related("workspace")


def workspaces_for_user(user: User) -> QuerySet[Workspace]:
    """Liefert alle Workspaces mit aktiver Mitgliedschaft."""
    return Workspace.objects.filter(memberships__user=user, memberships__is_active=True).distinct()


def projects_for_user(user: User) -> QuerySet[Project]:
    """Liefert globale Verwaltungs- oder explizit projektbezogene Zugriffe."""
    return (
        Project.objects.filter(
            Q(
                workspace__memberships__user=user,
                workspace__memberships__role__in=[WorkspaceRole.OWNER, WorkspaceRole.MANAGER],
            )
            | Q(owner=user)
            | Q(participants__user=user),
            workspace__memberships__user=user,
            workspace__memberships__is_active=True,
        )
        .select_related("workspace", "owner")
        .distinct()
    )


def boards_for_user(user: User) -> QuerySet[Board]:
    """Liefert persönliche Boards und zugängliche Projektboards."""
    project_ids = projects_for_user(user).values("id")
    return (
        Board.objects.filter(Q(owner=user) | Q(project_id__in=project_ids))
        .select_related("workspace", "project", "owner")
        .distinct()
    )


def tasks_for_user(user: User) -> QuerySet[Task]:
    """Liefert Tasks aus allen zugänglichen Boards."""
    return (
        Task.objects.filter(board__in=boards_for_user(user))
        .select_related(
            "workspace",
            "board",
            "column",
            "project",
            "owner",
            "assignee",
            "parent_task",
            "source_task",
            "source_subtask",
        )
        .prefetch_related(
            "collaborators",
            "subtasks__assignee",
            "comments__author",
            "comments__mentions",
            "attachments__uploaded_by",
            "history__actor",
        )
        .distinct()
    )
