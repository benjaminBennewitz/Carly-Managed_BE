# apps/workspaces/migrations/0005_global_personal_board.py
"""Trennt das persönliche Board dauerhaft von Team-Workspaces."""

from django.db import migrations, models


def _rewrite_column_reference(value, column_map):
    """Ersetzt bekannte Spalten-UUIDs rekursiv in JSON-Strukturen."""
    if isinstance(value, dict):
        return {key: _rewrite_column_reference(item, column_map) for key, item in value.items()}
    if isinstance(value, list):
        return [_rewrite_column_reference(item, column_map) for item in value]
    if isinstance(value, str):
        return column_map.get(value, value)
    return value


def backfill_assigned_project_members(apps, schema_editor) -> None:
    """Erhält Projektzugriff für bereits zugewiesene Personen."""
    Task = apps.get_model("workspaces", "Task")
    ProjectParticipant = apps.get_model("workspaces", "ProjectParticipant")

    tasks = (
        Task.objects.filter(project_id__isnull=False, source_task_id__isnull=True)
        .prefetch_related("collaborators", "subtasks")
        .select_related("project")
    )
    for task in tasks:
        user_ids = set(task.collaborators.values_list("id", flat=True))
        if task.assignee_id:
            user_ids.add(task.assignee_id)
        user_ids.update(
            task.subtasks.exclude(assignee_id__isnull=True).values_list("assignee_id", flat=True)
        )
        user_ids.discard(task.project.owner_id)
        for user_id in user_ids:
            ProjectParticipant.objects.get_or_create(
                project_id=task.project_id,
                user_id=user_id,
                defaults={"role": "collaborator"},
            )


def consolidate_personal_boards(apps, schema_editor) -> None:
    """Führt ältere persönliche Boards eines Nutzers in dessen Heimatboard zusammen."""
    Board = apps.get_model("workspaces", "Board")
    BoardColumn = apps.get_model("workspaces", "BoardColumn")
    Task = apps.get_model("workspaces", "Task")
    AutomationRule = apps.get_model("workspaces", "AutomationRule")

    owner_ids = (
        Board.objects.filter(kind="personal", owner_id__isnull=False)
        .values_list("owner_id", flat=True)
        .distinct()
    )
    for owner_id in owner_ids:
        boards = list(
            Board.objects.filter(kind="personal", owner_id=owner_id)
            .select_related("workspace")
            .order_by("created_at")
        )
        if len(boards) <= 1:
            continue

        canonical = next(
            (board for board in boards if board.workspace.owner_id == owner_id),
            boards[0],
        )
        canonical_columns = list(
            BoardColumn.objects.filter(board_id=canonical.id).order_by("position")
        )

        for duplicate in (board for board in boards if board.id != canonical.id):
            duplicate_columns = list(
                BoardColumn.objects.filter(board_id=duplicate.id).order_by("position")
            )
            column_map = {}

            for source in duplicate_columns:
                target = None
                if source.system_role:
                    target = next(
                        (
                            column
                            for column in canonical_columns
                            if column.system_role == source.system_role
                        ),
                        None,
                    )
                if target is None:
                    target = next(
                        (
                            column
                            for column in canonical_columns
                            if not column.system_role and column.title == source.title
                        ),
                        None,
                    )
                if target is None:
                    next_position = max(
                        (column.position for column in canonical_columns),
                        default=-1,
                    ) + 1
                    target = BoardColumn.objects.create(
                        board_id=canonical.id,
                        title=source.title,
                        color=source.color,
                        position=next_position,
                        sort_mode=source.sort_mode,
                        is_fixed_position=source.is_fixed_position,
                        is_dynamic=source.is_dynamic,
                        system_role="",
                    )
                    canonical_columns.append(target)
                column_map[str(source.id)] = str(target.id)

            for source in duplicate_columns:
                target_id = column_map[str(source.id)]
                existing_count = Task.objects.filter(
                    board_id=canonical.id,
                    column_id=target_id,
                    archived_at__isnull=True,
                ).count()
                tasks = list(
                    Task.objects.filter(board_id=duplicate.id, column_id=source.id).order_by(
                        "position", "created_at"
                    )
                )
                for offset, task in enumerate(tasks):
                    task.board_id = canonical.id
                    task.workspace_id = canonical.workspace_id
                    task.column_id = target_id
                    task.position = existing_count + offset
                    task.save(
                        update_fields=("board", "workspace", "column", "position", "updated_at")
                    )

            for task in Task.objects.filter(board_id=duplicate.id, column_id__isnull=True):
                task.board_id = canonical.id
                task.workspace_id = canonical.workspace_id
                task.save(update_fields=("board", "workspace", "updated_at"))

            for rule in AutomationRule.objects.filter(board_id=duplicate.id):
                rule.board_id = canonical.id
                rule.conditions = _rewrite_column_reference(rule.conditions, column_map)
                rule.actions = _rewrite_column_reference(rule.actions, column_map)
                rule.save(update_fields=("board", "conditions", "actions", "updated_at"))

            duplicate.delete()


def noop_reverse(apps, schema_editor) -> None:
    """Eine Zusammenführung persönlicher Boards wird nicht automatisch rückgängig gemacht."""


class Migration(migrations.Migration):
    """Führt globale persönliche Boards und Projekt-Sichtbarkeit ein."""

    dependencies = [
        ("workspaces", "0004_backfill_personal_intake_columns"),
    ]

    operations = [
        migrations.AddField(
            model_name="workspacemembership",
            name="is_project_guest",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="project",
            name="visibility",
            field=models.CharField(
                choices=[("restricted", "Eingeschränkt"), ("workspace", "Teamweit")],
                default="restricted",
                max_length=16,
            ),
        ),
        migrations.RunPython(backfill_assigned_project_members, noop_reverse),
        migrations.RunPython(consolidate_personal_boards, noop_reverse),
    ]
