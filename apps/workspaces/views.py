# apps/workspaces/views.py
"""Stellt berechtigungsgeprüfte REST-Endpunkte der Workspace-Domäne bereit."""

from typing import Any

from django.db import transaction
from django.db.models import Q
from django.http import FileResponse
from django.utils import timezone
from django.utils.http import content_disposition_header
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.common.exceptions import ConflictError
from apps.common.throttles import SearchRateThrottle, UploadRateThrottle
from apps.common.validators import validate_upload
from apps.workspaces.choices import ProjectStatus, WorkspaceRole
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
    TaskRecurrenceRule,
    Workspace,
    WorkspaceInvitation,
    WorkspaceJoinRequest,
    WorkspaceMembership,
)
from apps.workspaces.permissions import (
    get_membership,
    require_board_editor,
    require_project_manager,
    require_workspace_manager,
)
from apps.workspaces.selectors import (
    boards_for_user,
    projects_for_user,
    tasks_for_user,
    workspaces_for_user,
)
from apps.workspaces.serializers import (
    AttachmentSerializer,
    AutomationRuleSerializer,
    BoardColumnSerializer,
    BoardColumnWriteSerializer,
    BoardSerializer,
    ColumnReorderSerializer,
    CommentSerializer,
    CommentWriteSerializer,
    InvitationAcceptSerializer,
    InvitationCreateSerializer,
    InvitationSerializer,
    JoinRequestSerializer,
    MoveTaskSerializer,
    ProjectSerializer,
    ProjectWriteSerializer,
    RecurrenceRuleSerializer,
    SubtaskSerializer,
    SubtaskWriteSerializer,
    TaskSerializer,
    TaskWriteSerializer,
    VersionSerializer,
    WorkspaceMemberSerializer,
    WorkspaceSerializer,
)
from apps.workspaces.services import (
    accept_invitation,
    archive_task,
    assert_version,
    create_invitation,
    create_project,
    create_subtask,
    create_task,
    increment_version,
    move_task,
    save_recurrence_rule,
    set_project_status,
    set_task_completed,
    update_project,
    update_subtask,
    update_task,
)


def _serializer_context(view: Any) -> dict[str, Any]:
    """Liefert einen konsistenten Request-Kontext für verschachtelte URLs."""
    return {"request": view.request, "view": view}


class WorkspaceViewSet(viewsets.ReadOnlyModelViewSet[Workspace]):
    """Liest zugängliche Workspaces und verwaltet deren Mitglieder."""

    queryset = Workspace.objects.none()
    serializer_class = WorkspaceSerializer
    pagination_class = None

    def get_queryset(self):
        """Begrenzt die Liste auf aktive Mitgliedschaften."""
        return workspaces_for_user(self.request.user).prefetch_related("memberships__user")

    @action(detail=True, methods=["get", "patch"], url_path="members")
    def members(self, request: Any, pk: str | None = None) -> Response:
        """Listet Mitglieder oder ändert Rolle und Avatarfarbe eines Mitglieds."""
        workspace = self.get_object()
        if request.method == "GET":
            memberships = workspace.memberships.filter(is_active=True).select_related("user")
            return Response(
                WorkspaceMemberSerializer(
                    memberships, many=True, context=_serializer_context(self)
                ).data
            )
        require_workspace_manager(user=request.user, workspace=workspace)
        member_id = request.data.get("memberId")
        membership = (
            workspace.memberships.filter(user_id=member_id, is_active=True)
            .select_related("user")
            .first()
        )
        if membership is None:
            raise NotFound("Mitglied nicht gefunden.")
        role = request.data.get("role", membership.role)
        avatar_color = request.data.get("avatarColor", membership.avatar_color)
        if membership.role == WorkspaceRole.OWNER and role != WorkspaceRole.OWNER:
            raise ConflictError(
                "Die Owner-Rolle kann nicht über diesen Endpunkt übertragen werden."
            )
        if role not in WorkspaceRole.values:
            raise ValidationError({"role": "Ungültige Workspace-Rolle."})
        membership.role = role
        membership.avatar_color = avatar_color
        membership.full_clean()
        membership.save(update_fields=("role", "avatar_color", "updated_at"))
        return Response(
            WorkspaceMemberSerializer(membership, context=_serializer_context(self)).data
        )


class ProjectViewSet(viewsets.ModelViewSet[Project]):
    """Verwaltet Projekte samt Rollen und Lebenszyklus."""

    queryset = Project.objects.none()
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        """Lädt nur Projekte mit aktuellem Zugriff und benötigte Relationen."""
        queryset = projects_for_user(self.request.user).prefetch_related("participants__user")
        workspace_id = self.request.query_params.get("workspaceId")
        status_value = self.request.query_params.get("status")
        if workspace_id:
            queryset = queryset.filter(workspace_id=workspace_id)
        if status_value:
            queryset = queryset.filter(status=status_value)
        return queryset

    def get_serializer_class(self):
        """Trennt Schreibvalidierung vom umfangreichen Ausgabevertrag."""
        return (
            ProjectWriteSerializer
            if self.action in {"create", "partial_update", "update"}
            else ProjectSerializer
        )

    def create(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """Erstellt ein Projekt nur mit Workspace-Verwaltungsrechten."""
        workspace_id = request.data.get("workspaceId")
        workspace = workspaces_for_user(request.user).filter(pk=workspace_id).first()
        if workspace is None:
            raise NotFound("Workspace nicht gefunden.")
        require_workspace_manager(user=request.user, workspace=workspace)
        serializer = ProjectWriteSerializer(
            data=request.data, context={**_serializer_context(self), "workspace": workspace}
        )
        serializer.is_valid(raise_exception=True)
        project = create_project(
            workspace=workspace, actor=request.user, validated_data=dict(serializer.validated_data)
        )
        return Response(
            ProjectSerializer(project, context=_serializer_context(self)).data,
            status=status.HTTP_201_CREATED,
        )

    def partial_update(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """Aktualisiert ein Projekt mit optimistischer Sperre."""
        project = self.get_object()
        require_project_manager(user=request.user, project=project)
        serializer = ProjectWriteSerializer(
            project,
            data=request.data,
            partial=True,
            context={**_serializer_context(self), "workspace": project.workspace},
        )
        serializer.is_valid(raise_exception=True)
        supplied_version = serializer.validated_data.pop("version", None)
        updated = update_project(
            project=project,
            actor=request.user,
            validated_data=dict(serializer.validated_data),
            supplied_version=supplied_version,
        )
        return Response(ProjectSerializer(updated, context=_serializer_context(self)).data)

    def destroy(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """Löscht ein Projekt nur nach expliziter aktueller Versionsangabe."""
        project = self.get_object()
        require_project_manager(user=request.user, project=project)
        serializer = VersionSerializer(data={"version": request.query_params.get("version")})
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            locked = Project.objects.select_for_update().get(pk=project.pk)
            assert_version(locked, serializer.validated_data["version"])
            locked.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _status_action(self, request: Any, value: str) -> Response:
        project = self.get_object()
        require_project_manager(user=request.user, project=project)
        serializer = VersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = set_project_status(
            project=project,
            actor=request.user,
            status_value=value,
            supplied_version=serializer.validated_data["version"],
        )
        return Response(ProjectSerializer(updated, context=_serializer_context(self)).data)

    @action(detail=True, methods=["post"])
    def complete(self, request: Any, pk: str | None = None) -> Response:
        """Schließt ein Projekt ab."""
        return self._status_action(request, ProjectStatus.COMPLETED)

    @action(detail=True, methods=["post"])
    def archive(self, request: Any, pk: str | None = None) -> Response:
        """Archiviert ein Projekt."""
        return self._status_action(request, ProjectStatus.ARCHIVED)

    @action(detail=True, methods=["post"])
    def restore(self, request: Any, pk: str | None = None) -> Response:
        """Stellt ein Projekt als aktiv wieder her."""
        return self._status_action(request, ProjectStatus.ACTIVE)

    @action(detail=True, methods=["post"])
    def pin(self, request: Any, pk: str | None = None) -> Response:
        """Speichert den Pin-Zustand nutzerspezifisch."""
        project = self.get_object()
        value = bool(request.data.get("isPinned", True))
        ProjectPreference.objects.update_or_create(
            project=project, user=request.user, defaults={"is_pinned": value}
        )
        return Response(ProjectSerializer(project, context=_serializer_context(self)).data)

    @action(detail=True, methods=["post"], url_path="mark-opened")
    def mark_opened(self, request: Any, pk: str | None = None) -> Response:
        """Aktualisiert den letzten nutzerspezifischen Projektaufruf."""
        project = self.get_object()
        ProjectPreference.objects.update_or_create(
            project=project, user=request.user, defaults={"last_opened_at": timezone.now()}
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class BoardViewSet(viewsets.ReadOnlyModelViewSet[Board]):
    """Liefert zugängliche Boards als vollständige Snapshots."""

    queryset = Board.objects.none()
    serializer_class = BoardSerializer
    pagination_class = None

    def get_queryset(self):
        """Optimiert den Snapshot durch gezieltes Prefetching."""
        return boards_for_user(self.request.user).prefetch_related(
            "columns__tasks__collaborators",
            "columns__tasks__subtasks__assignee",
            "columns__tasks__comments__author",
            "columns__tasks__comments__mentions",
            "columns__tasks__attachments__uploaded_by",
            "columns__tasks__history__actor",
            "columns__tasks__recurrence_rule",
        )

    @action(detail=True, methods=["post"], url_path="columns")
    def create_column(self, request: Any, pk: str | None = None) -> Response:
        """Erstellt eine neue Boardspalte am Ende."""
        board = self.get_object()
        require_board_editor(user=request.user, board=board)
        if board.project:
            require_project_manager(user=request.user, project=board.project)
        serializer = BoardColumnWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            locked_board = Board.objects.select_for_update().get(pk=board.pk)
            assert_version(locked_board, request.data.get("boardVersion"))
            position = locked_board.columns.count()
            column = BoardColumn.objects.create(
                board=locked_board, position=position, **serializer.validated_data
            )
            increment_version(locked_board)
            locked_board.save(update_fields=("version", "updated_at"))
        return Response(
            BoardColumnSerializer(column, context=_serializer_context(self)).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="reorder-columns")
    def reorder_columns(self, request: Any, pk: str | None = None) -> Response:
        """Speichert eine vollständige Spaltenreihenfolge atomar."""
        board = self.get_object()
        require_board_editor(user=request.user, board=board)
        if board.project:
            require_project_manager(user=request.user, project=board.project)
        serializer = ColumnReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data["columnIds"]
        with transaction.atomic():
            locked_board = Board.objects.select_for_update().get(pk=board.pk)
            assert_version(locked_board, serializer.validated_data["version"])
            columns = list(BoardColumn.objects.select_for_update().filter(board=locked_board))
            if {column.id for column in columns} != set(ids):
                raise ValidationError(
                    {"columnIds": "Die Liste muss sämtliche Boardspalten enthalten."}
                )
            mapping = {column.id: column for column in columns}
            for position, column_id in enumerate(ids):
                mapping[column_id].position = position
            BoardColumn.objects.bulk_update(columns, ("position", "updated_at"))
            increment_version(locked_board)
            locked_board.save(update_fields=("version", "updated_at"))
        refreshed = self.get_queryset().get(pk=board.pk)
        return Response(BoardSerializer(refreshed, context=_serializer_context(self)).data)


class BoardColumnViewSet(
    mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet[BoardColumn]
):
    """Ändert oder löscht einzelne Boardspalten."""

    queryset = BoardColumn.objects.none()
    serializer_class = BoardColumnWriteSerializer

    def get_queryset(self):
        """Begrenzt Spalten über zugängliche Boards."""
        return BoardColumn.objects.filter(
            board__in=boards_for_user(self.request.user)
        ).select_related("board", "board__project")

    def partial_update(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """Aktualisiert eine Spalte unter Versionskontrolle."""
        column = self.get_object()
        require_board_editor(user=request.user, board=column.board)
        if column.board.project:
            require_project_manager(user=request.user, project=column.board.project)
        serializer = self.get_serializer(column, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        supplied_version = serializer.validated_data.pop("version", None)
        with transaction.atomic():
            locked = BoardColumn.objects.select_for_update().get(pk=column.pk)
            assert_version(locked, supplied_version)
            for field, value in serializer.validated_data.items():
                setattr(locked, field, value)
            increment_version(locked)
            locked.full_clean()
            locked.save()
        return Response(BoardColumnSerializer(locked, context=_serializer_context(self)).data)

    def destroy(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """Löscht eine leere, nicht reservierte Spalte."""
        column = self.get_object()
        require_board_editor(user=request.user, board=column.board)
        if column.board.project:
            require_project_manager(user=request.user, project=column.board.project)
        if column.is_fixed_position or column.system_role:
            raise ConflictError("Diese Systemspalte darf nicht gelöscht werden.")
        if column.tasks.filter(archived_at__isnull=True).exists():
            raise ConflictError("Verschiebe zuerst alle aktiven Tasks aus dieser Spalte.")
        serializer = VersionSerializer(data={"version": request.query_params.get("version")})
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            locked = BoardColumn.objects.select_for_update().get(pk=column.pk)
            assert_version(locked, serializer.validated_data["version"])
            board = Board.objects.select_for_update().get(pk=locked.board_id)
            locked.delete()
            remaining = list(board.columns.order_by("position"))
            for position, item in enumerate(remaining):
                item.position = position
            BoardColumn.objects.bulk_update(remaining, ("position", "updated_at"))
            increment_version(board)
            board.save(update_fields=("version", "updated_at"))
        return Response(status=status.HTTP_204_NO_CONTENT)


class TaskViewSet(viewsets.ModelViewSet[Task]):
    """Verwaltet Tasks, Unteraufgaben, Kommentare, Dateien und Wiederholungen."""

    queryset = Task.objects.none()
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    search_fields = ("title", "description", "tags")
    ordering_fields = ("created_at", "updated_at", "due_date", "title", "priority", "position")

    def get_queryset(self):
        """Filtert Tasks nach Board, Projekt, Pool, Archiv und Zuweisung."""
        queryset = tasks_for_user(self.request.user)
        board_id = self.request.query_params.get("boardId")
        project_id = self.request.query_params.get("projectId")
        if board_id:
            queryset = queryset.filter(board_id=board_id)
        if project_id:
            queryset = queryset.filter(project_id=project_id)
        if self.request.query_params.get("pool") == "true":
            queryset = queryset.filter(is_shared_pool=True, archived_at__isnull=True)
        if self.request.query_params.get("archived") == "true":
            queryset = queryset.filter(archived_at__isnull=False)
        elif self.action == "list":
            queryset = queryset.filter(archived_at__isnull=True)
        if self.request.query_params.get("assignedToMe") == "true":
            queryset = queryset.filter(
                Q(assignee=self.request.user) | Q(collaborators=self.request.user)
            ).distinct()
        return queryset

    def get_serializer_class(self):
        """Verwendet für Änderungen einen schmalen Eingabevertrag."""
        return (
            TaskWriteSerializer
            if self.action in {"create", "partial_update", "update"}
            else TaskSerializer
        )

    def create(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """Erstellt einen Task innerhalb eines zugänglichen Boards."""
        board = boards_for_user(request.user).filter(pk=request.data.get("boardId")).first()
        if board is None:
            raise NotFound("Board nicht gefunden.")
        require_board_editor(user=request.user, board=board)
        serializer = TaskWriteSerializer(
            data=request.data, context={**_serializer_context(self), "board": board}
        )
        serializer.is_valid(raise_exception=True)
        serializer.validated_data.pop("version", None)
        task = create_task(
            board=board, actor=request.user, validated_data=dict(serializer.validated_data)
        )
        task = self.get_queryset().get(pk=task.pk)
        return Response(
            TaskSerializer(task, context=_serializer_context(self)).data,
            status=status.HTTP_201_CREATED,
        )

    def partial_update(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """Aktualisiert einen Task mit Konflikterkennung."""
        task = self.get_object()
        require_board_editor(user=request.user, board=task.board)
        serializer = TaskWriteSerializer(
            task,
            data=request.data,
            partial=True,
            context={**_serializer_context(self), "board": task.board},
        )
        serializer.is_valid(raise_exception=True)
        supplied_version = serializer.validated_data.pop("version", None)
        updated = update_task(
            task=task,
            actor=request.user,
            validated_data=dict(serializer.validated_data),
            supplied_version=supplied_version,
        )
        updated = self.get_queryset().get(pk=updated.pk)
        return Response(TaskSerializer(updated, context=_serializer_context(self)).data)

    def destroy(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """Löscht einen Task erst nach aktueller Versionsprüfung dauerhaft."""
        task = self.get_object()
        require_board_editor(user=request.user, board=task.board)
        serializer = VersionSerializer(data={"version": request.query_params.get("version")})
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            locked = Task.objects.select_for_update().get(pk=task.pk)
            assert_version(locked, serializer.validated_data["version"])
            locked.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _completion_action(self, request: Any, completed: bool) -> Response:
        task = self.get_object()
        require_board_editor(user=request.user, board=task.board)
        serializer = VersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = set_task_completed(
            task=task,
            actor=request.user,
            completed=completed,
            supplied_version=serializer.validated_data["version"],
        )
        updated = self.get_queryset().get(pk=updated.pk)
        return Response(TaskSerializer(updated, context=_serializer_context(self)).data)

    @action(detail=True, methods=["post"])
    def complete(self, request: Any, pk: str | None = None) -> Response:
        """Schließt einen Task ab."""
        return self._completion_action(request, True)

    @action(detail=True, methods=["post"])
    def reopen(self, request: Any, pk: str | None = None) -> Response:
        """Öffnet einen Task erneut."""
        return self._completion_action(request, False)

    @action(detail=True, methods=["post"])
    def move(self, request: Any, pk: str | None = None) -> Response:
        """Verschiebt einen Task in eine Zielspalte und Position."""
        task = self.get_object()
        require_board_editor(user=request.user, board=task.board)
        serializer = MoveTaskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = move_task(task=task, actor=request.user, **serializer.validated_data)
        updated = self.get_queryset().get(pk=updated.pk)
        return Response(TaskSerializer(updated, context=_serializer_context(self)).data)

    def _archive_action(self, request: Any, archived: bool) -> Response:
        task = self.get_object()
        require_board_editor(user=request.user, board=task.board)
        serializer = VersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = archive_task(
            task=task,
            actor=request.user,
            supplied_version=serializer.validated_data["version"],
            archived=archived,
        )
        return Response(TaskSerializer(updated, context=_serializer_context(self)).data)

    @action(detail=True, methods=["post"])
    def archive(self, request: Any, pk: str | None = None) -> Response:
        """Archiviert einen Task."""
        return self._archive_action(request, True)

    @action(detail=True, methods=["post"])
    def restore(self, request: Any, pk: str | None = None) -> Response:
        """Stellt einen Task wieder her."""
        return self._archive_action(request, False)

    @action(
        detail=True,
        methods=["post", "patch", "delete"],
        url_path=r"subtasks(?:/(?P<subtask_id>[^/.]+))?",
    )
    def subtasks(
        self, request: Any, pk: str | None = None, subtask_id: str | None = None
    ) -> Response:
        """Erstellt, ändert oder löscht eine Unteraufgabe."""
        task = self.get_object()
        require_board_editor(user=request.user, board=task.board)
        if request.method == "POST":
            serializer = SubtaskWriteSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            if "title" not in serializer.validated_data:
                raise ValidationError({"title": "Ein Titel ist erforderlich."})
            assignee = serializer.validated_data.get("assignee")
            if (
                assignee
                and not WorkspaceMembership.objects.filter(
                    workspace=task.workspace, user=assignee, is_active=True
                ).exists()
            ):
                raise ValidationError(
                    {"assigneeId": "Die Person ist kein aktives Workspace-Mitglied."}
                )
            subtask = create_subtask(
                task=task,
                actor=request.user,
                title=serializer.validated_data["title"],
                assignee=assignee,
            )
            return Response(
                SubtaskSerializer(subtask, context=_serializer_context(self)).data,
                status=status.HTTP_201_CREATED,
            )
        subtask = task.subtasks.filter(pk=subtask_id).select_related("task", "assignee").first()
        if subtask is None:
            raise NotFound("Unteraufgabe nicht gefunden.")
        if request.method == "DELETE":
            serializer = VersionSerializer(data={"version": request.query_params.get("version")})
            serializer.is_valid(raise_exception=True)
            with transaction.atomic():
                locked = Subtask.objects.select_for_update().get(pk=subtask.pk)
                assert_version(locked, serializer.validated_data["version"])
                locked.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        serializer = SubtaskWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        assignee_value: User | None | object = serializer.validated_data.get("assignee", ...)
        if (
            assignee_value is not ...
            and assignee_value
            and not WorkspaceMembership.objects.filter(
                workspace=task.workspace, user=assignee_value, is_active=True
            ).exists()
        ):
            raise ValidationError({"assigneeId": "Die Person ist kein aktives Workspace-Mitglied."})
        updated = update_subtask(
            subtask=subtask,
            actor=request.user,
            supplied_version=serializer.validated_data.get("version"),
            title=serializer.validated_data.get("title"),
            assignee=assignee_value,
            is_done=serializer.validated_data.get("is_done"),
        )
        return Response(SubtaskSerializer(updated, context=_serializer_context(self)).data)

    @action(
        detail=True, methods=["post", "delete"], url_path=r"comments(?:/(?P<comment_id>[^/.]+))?"
    )
    def comments(
        self, request: Any, pk: str | None = None, comment_id: str | None = None
    ) -> Response:
        """Erstellt einen Kommentar oder löscht den eigenen Kommentar weich."""
        task = self.get_object()
        require_board_editor(user=request.user, board=task.board)
        if request.method == "POST":
            serializer = CommentWriteSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            mentions = serializer.validated_data.get("mentions", [])
            active_ids = set(
                WorkspaceMembership.objects.filter(
                    workspace=task.workspace, user__in=mentions, is_active=True
                ).values_list("user_id", flat=True)
            )
            if any(user.id not in active_ids for user in mentions):
                raise ValidationError(
                    {"mentionIds": "Erwähnte Personen müssen Workspace-Mitglieder sein."}
                )
            comment = TaskComment.objects.create(
                task=task, author=request.user, body=serializer.validated_data["body"]
            )
            comment.mentions.set(mentions)
            return Response(
                CommentSerializer(comment, context=_serializer_context(self)).data,
                status=status.HTTP_201_CREATED,
            )
        comment = task.comments.filter(pk=comment_id, deleted_at__isnull=True).first()
        if comment is None:
            raise NotFound("Kommentar nicht gefunden.")
        membership = get_membership(user=request.user, workspace=task.workspace)
        if comment.author_id != request.user.id and membership.role not in {
            WorkspaceRole.OWNER,
            WorkspaceRole.MANAGER,
        }:
            raise PermissionDenied("Du darfst diesen Kommentar nicht löschen.")
        comment.deleted_at = timezone.now()
        comment.version += 1
        comment.save(update_fields=("deleted_at", "version", "updated_at"))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(
        detail=True,
        methods=["post"],
        parser_classes=[MultiPartParser],
        throttle_classes=[UploadRateThrottle],
    )
    def attachments(self, request: Any, pk: str | None = None) -> Response:
        """Speichert einen oder mehrere geprüfte private Anhänge."""
        task = self.get_object()
        require_board_editor(user=request.user, board=task.board)
        files = request.FILES.getlist("files")
        if not files or len(files) > 10:
            raise ValidationError({"files": "Lade ein bis zehn Dateien gleichzeitig hoch."})
        created = []
        for upload in files:
            validate_upload(upload)
            attachment = TaskAttachment.objects.create(
                task=task,
                file=upload,
                original_name=upload.name[:255],
                mime_type=upload.content_type[:150],
                size_bytes=upload.size,
                uploaded_by=request.user,
            )
            created.append(attachment)
        return Response(
            AttachmentSerializer(created, many=True, context=_serializer_context(self)).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get", "put", "delete"])
    def recurrence(self, request: Any, pk: str | None = None) -> Response:
        """Liest, speichert oder entfernt die Wiederholung eines Tasks."""
        task = self.get_object()
        require_board_editor(user=request.user, board=task.board)
        rule = TaskRecurrenceRule.objects.filter(task=task).first()
        if request.method == "GET":
            if rule is None:
                raise NotFound("Keine Wiederholungsregel vorhanden.")
            return Response(RecurrenceRuleSerializer(rule, context=_serializer_context(self)).data)
        if request.method == "DELETE":
            if rule is None:
                return Response(status=status.HTTP_204_NO_CONTENT)
            serializer = VersionSerializer(data={"version": request.query_params.get("version")})
            serializer.is_valid(raise_exception=True)
            with transaction.atomic():
                locked = TaskRecurrenceRule.objects.select_for_update().get(pk=rule.pk)
                assert_version(locked, serializer.validated_data["version"])
                locked.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        serializer = RecurrenceRuleSerializer(
            rule, data=request.data, partial=rule is not None, context=_serializer_context(self)
        )
        serializer.is_valid(raise_exception=True)
        supplied_version = serializer.validated_data.pop("version", None)
        saved = save_recurrence_rule(
            task=task,
            validated_data=dict(serializer.validated_data),
            supplied_version=supplied_version,
        )
        return Response(RecurrenceRuleSerializer(saved, context=_serializer_context(self)).data)


class AttachmentDownloadView(APIView):
    """Liefert private Dateien erst nach erneutem Task-Zugriffstest."""

    @extend_schema(responses={200: OpenApiTypes.BINARY})
    def get(self, request: Any, attachment_id: str) -> FileResponse:
        """Streamt die Datei mit sicherem Content-Disposition-Header."""
        attachment = (
            TaskAttachment.objects.select_related("task", "task__board")
            .filter(pk=attachment_id, task__in=tasks_for_user(request.user))
            .first()
        )
        if attachment is None:
            raise NotFound("Anhang nicht gefunden.")
        response = FileResponse(attachment.file.open("rb"), content_type=attachment.mime_type)
        response.headers["Content-Disposition"] = content_disposition_header(
            True, attachment.original_name
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response


class AutomationRuleViewSet(viewsets.ModelViewSet[AutomationRule]):
    """Verwaltet begrenzte serverseitige Board-Automationen."""

    queryset = AutomationRule.objects.none()
    serializer_class = AutomationRuleSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        """Filtert Regeln über zugängliche Boards."""
        queryset = AutomationRule.objects.filter(board__in=boards_for_user(self.request.user))
        board_id = self.request.query_params.get("boardId")
        return queryset.filter(board_id=board_id) if board_id else queryset

    def perform_create(self, serializer: AutomationRuleSerializer) -> None:
        """Erstellt Regeln nur mit Projektverwaltungsrechten."""
        board = (
            boards_for_user(self.request.user).filter(pk=self.request.data.get("boardId")).first()
        )
        if board is None:
            raise NotFound("Board nicht gefunden.")
        require_board_editor(user=self.request.user, board=board)
        if board.project:
            require_project_manager(user=self.request.user, project=board.project)
        serializer.save(board=board)

    def partial_update(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """Aktualisiert eine Regel mit Versionsprüfung."""
        rule = self.get_object()
        if rule.board.project:
            require_project_manager(user=request.user, project=rule.board.project)
        serializer = self.get_serializer(rule, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        supplied_version = serializer.validated_data.pop("version", None)
        with transaction.atomic():
            locked = AutomationRule.objects.select_for_update().get(pk=rule.pk)
            assert_version(locked, supplied_version)
            for field, value in serializer.validated_data.items():
                setattr(locked, field, value)
            increment_version(locked)
            locked.save()
        return Response(self.get_serializer(locked).data)

    def destroy(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """Löscht eine Regel nach Versionsprüfung."""
        rule = self.get_object()
        if rule.board.project:
            require_project_manager(user=request.user, project=rule.board.project)
        serializer = VersionSerializer(data={"version": request.query_params.get("version")})
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            locked = AutomationRule.objects.select_for_update().get(pk=rule.pk)
            assert_version(locked, serializer.validated_data["version"])
            locked.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class InvitationViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet[WorkspaceInvitation],
):
    """Verwaltet Einladungen ohne Klartext-Token-Persistenz."""

    queryset = WorkspaceInvitation.objects.none()

    def get_queryset(self):
        """Liefert Einladungen aus administrierbaren Workspaces."""
        managed_workspace_ids = WorkspaceMembership.objects.filter(
            user=self.request.user,
            role__in=[WorkspaceRole.OWNER, WorkspaceRole.MANAGER],
            is_active=True,
        ).values("workspace_id")
        queryset = WorkspaceInvitation.objects.filter(
            workspace_id__in=managed_workspace_ids
        ).select_related("workspace", "project", "invited_by")
        workspace_id = self.request.query_params.get("workspaceId")
        return queryset.filter(workspace_id=workspace_id) if workspace_id else queryset

    def get_serializer_class(self):
        """Trennt Einladungsdaten von der Ausgabe."""
        return InvitationCreateSerializer if self.action == "create" else InvitationSerializer

    def create(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """Erstellt und versendet eine Einladung."""
        workspace = (
            workspaces_for_user(request.user).filter(pk=request.data.get("workspaceId")).first()
        )
        if workspace is None:
            raise NotFound("Workspace nicht gefunden.")
        require_workspace_manager(user=request.user, workspace=workspace)
        serializer = InvitationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        project = serializer.validated_data.get("project")
        if project and project.workspace_id != workspace.id:
            raise ValidationError({"projectId": "Das Projekt gehört nicht zu diesem Workspace."})
        invitation, _ = create_invitation(
            workspace=workspace, actor=request.user, **serializer.validated_data
        )
        return Response(InvitationSerializer(invitation).data, status=status.HTTP_201_CREATED)

    def destroy(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """Widerruft eine offene Einladung statt sie spurlos zu löschen."""
        invitation = self.get_object()
        invitation.status = "revoked"
        invitation.save(update_fields=("status", "updated_at"))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["post"], permission_classes=[permissions.IsAuthenticated])
    def accept(self, request: Any) -> Response:
        """Nimmt eine Einladung für die angemeldete E-Mail-Adresse an."""
        serializer = InvitationAcceptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invitation = accept_invitation(
            raw_token=serializer.validated_data["token"], user=request.user
        )
        return Response(InvitationSerializer(invitation).data)


class JoinRequestViewSet(viewsets.ReadOnlyModelViewSet[WorkspaceJoinRequest]):
    """Listet und moderiert Workspace-Beitrittsanfragen."""

    queryset = WorkspaceJoinRequest.objects.none()
    serializer_class = JoinRequestSerializer

    def get_queryset(self):
        """Liefert nur Anfragen aus verwalteten Workspaces."""
        managed = WorkspaceMembership.objects.filter(
            user=self.request.user,
            role__in=[WorkspaceRole.OWNER, WorkspaceRole.MANAGER],
            is_active=True,
        ).values("workspace_id")
        return WorkspaceJoinRequest.objects.filter(workspace_id__in=managed).select_related(
            "workspace", "user"
        )

    def _decide(self, request: Any, approved: bool) -> Response:
        join_request = self.get_object()
        require_workspace_manager(user=request.user, workspace=join_request.workspace)
        if join_request.status != "pending":
            raise ConflictError("Die Beitrittsanfrage wurde bereits bearbeitet.")
        join_request.status = "approved" if approved else "rejected"
        join_request.decided_by = request.user
        join_request.decided_at = timezone.now()
        join_request.save(update_fields=("status", "decided_by", "decided_at", "updated_at"))
        if approved:
            WorkspaceMembership.objects.update_or_create(
                workspace=join_request.workspace,
                user=join_request.user,
                defaults={
                    "role": WorkspaceRole.MEMBER,
                    "is_active": True,
                    "avatar_color": join_request.avatar_color,
                },
            )
        return Response(JoinRequestSerializer(join_request, context=_serializer_context(self)).data)

    @action(detail=True, methods=["post"])
    def approve(self, request: Any, pk: str | None = None) -> Response:
        """Genehmigt eine Beitrittsanfrage."""
        return self._decide(request, True)

    @action(detail=True, methods=["post"])
    def reject(self, request: Any, pk: str | None = None) -> Response:
        """Lehnt eine Beitrittsanfrage ab."""
        return self._decide(request, False)


class DashboardView(APIView):
    """Aggregiert dynamische persönliche Dashboard-Kennzahlen."""

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Any) -> Response:
        """Liefert kompakte Task-, Projekt- und Fälligkeitswerte."""
        tasks = tasks_for_user(request.user).filter(archived_at__isnull=True)
        today = timezone.localdate()
        projects = projects_for_user(request.user)
        payload = {
            "openTasks": tasks.filter(is_done=False).count(),
            "completedTasks": tasks.filter(is_done=True).count(),
            "overdueTasks": tasks.filter(is_done=False, due_date__lt=today).count(),
            "dueToday": tasks.filter(is_done=False, due_date=today).count(),
            "assignedToMe": tasks.filter(assignee=request.user, is_done=False).count(),
            "activeProjects": projects.filter(status=ProjectStatus.ACTIVE).count(),
            "completedProjects": projects.filter(status=ProjectStatus.COMPLETED).count(),
            "poolTasks": tasks.filter(is_shared_pool=True, is_done=False).count(),
        }
        return Response(payload)


class GlobalSearchView(APIView):
    """Durchsucht zugängliche Projekte, Tasks und Mitglieder serverseitig."""

    throttle_classes = [SearchRateThrottle]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Any) -> Response:
        """Liefert begrenzte, gruppierte Suchtreffer ohne Fremddatenleck."""
        query = " ".join(request.query_params.get("q", "").strip().split())[:120]
        if len(query) < 2:
            return Response([])
        project_hits = projects_for_user(request.user).filter(
            Q(name__icontains=query) | Q(description__icontains=query)
        )[:10]
        task_hits = tasks_for_user(request.user).filter(
            Q(title__icontains=query) | Q(description__icontains=query) | Q(tags__icontains=query)
        )[:20]
        workspace_ids = workspaces_for_user(request.user).values("id")
        member_hits = (
            WorkspaceMembership.objects.filter(workspace_id__in=workspace_ids, is_active=True)
            .filter(Q(user__display_name__icontains=query) | Q(user__email__icontains=query))
            .select_related("user", "workspace")[:10]
        )
        groups = []
        if project_hits:
            groups.append(
                {
                    "id": "projects",
                    "label": "Projekte",
                    "icon": "folder_open",
                    "results": [
                        {
                            "id": f"project-{item.id}",
                            "groupId": "projects",
                            "groupLabel": "Projekte",
                            "groupIcon": "folder_open",
                            "title": item.name,
                            "subtitle": item.description,
                            "icon": item.icon,
                            "route": ["/projects", str(item.id), "board"],
                            "type": "project",
                            "score": 100,
                        }
                        for item in project_hits
                    ],
                }
            )
        if task_hits:
            groups.append(
                {
                    "id": "tasks",
                    "label": "Aufgaben",
                    "icon": "task_alt",
                    "results": [
                        {
                            "id": f"task-{item.id}",
                            "groupId": "tasks",
                            "groupLabel": "Aufgaben",
                            "groupIcon": "task_alt",
                            "title": item.title,
                            "subtitle": item.project.name if item.project else "Mein Board",
                            "icon": "task_alt" if item.is_done else "check_box_outline_blank",
                            "route": ["/projects", str(item.project_id), "board"]
                            if item.project_id
                            else ["/board"],
                            "queryParams": {"task": str(item.id)},
                            "type": "archive" if item.archived_at else "task",
                            "score": 90,
                        }
                        for item in task_hits
                    ],
                }
            )
        if member_hits:
            groups.append(
                {
                    "id": "members",
                    "label": "Mitglieder",
                    "icon": "group",
                    "results": [
                        {
                            "id": f"member-{item.user_id}",
                            "groupId": "members",
                            "groupLabel": "Mitglieder",
                            "groupIcon": "group",
                            "title": item.user.display_name,
                            "subtitle": item.user.email,
                            "icon": "person",
                            "route": ["/members"],
                            "type": "member",
                            "score": 80,
                        }
                        for item in member_hits
                    ],
                }
            )
        return Response(groups)
