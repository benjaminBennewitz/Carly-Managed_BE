# apps/workspaces/migrations/0008_task_pool_constraints.py
"""Normalisiert bestehende Poolaufgaben nach Anlage des Ursprungfelds."""

from django.db import migrations, models


def normalize_assigned_pool_tasks(apps, schema_editor) -> None:
    """Verschiebt fälschlich zugewiesene Poolaufgaben in den persönlichen Intake."""
    Board = apps.get_model("workspaces", "Board")
    BoardColumn = apps.get_model("workspaces", "BoardColumn")
    Task = apps.get_model("workspaces", "Task")

    Task.objects.filter(is_shared_pool=True).update(column_id=None)
    tasks = Task.objects.filter(is_shared_pool=True, assignee_id__isnull=False)
    for task in tasks.iterator():
        personal_board = Board.objects.filter(
            kind="personal",
            owner_id=task.assignee_id,
        ).first()
        if personal_board is None:
            task.is_shared_pool = False
            task.save(update_fields=("is_shared_pool", "updated_at"))
            continue

        intake = BoardColumn.objects.filter(
            board=personal_board,
            system_role="new-assigned",
        ).first()
        if intake is None:
            intake = (
                BoardColumn.objects.filter(board=personal_board)
                .order_by("position")
                .first()
            )
        if intake is None:
            task.is_shared_pool = False
            task.save(update_fields=("is_shared_pool", "updated_at"))
            continue

        maximum = Task.objects.filter(
            column=intake,
            archived_at__isnull=True,
        ).aggregate(value=models.Max("position"))["value"]
        task.pool_source_project_id = task.project_id
        task.workspace_id = personal_board.workspace_id
        task.board_id = personal_board.id
        task.project_id = None
        task.column_id = intake.id
        task.position = 0 if maximum is None else maximum + 1
        task.is_shared_pool = False
        task.save(
            update_fields=(
                "pool_source_project",
                "workspace",
                "board",
                "project",
                "column",
                "position",
                "is_shared_pool",
                "updated_at",
            )
        )


class Migration(migrations.Migration):
    """Bereinigt Pooldaten in einer eigenen PostgreSQL-Transaktion."""

    dependencies = [("workspaces", "0007_task_pool_source_project")]

    operations = [
        migrations.RunPython(
            normalize_assigned_pool_tasks,
            migrations.RunPython.noop,
        ),
    ]
