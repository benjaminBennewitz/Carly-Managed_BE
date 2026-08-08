# apps/workspaces/migrations/0004_backfill_personal_intake_columns.py
"""Ergänzt die persönliche Neu-Spalte für bestehende Boards."""

from django.db import migrations


def create_personal_intake_columns(apps, schema_editor) -> None:
    """Erzeugt eine feste Eingangsspalte für aktivierte dynamische Neu-Spalten."""
    Board = apps.get_model("workspaces", "Board")
    BoardColumn = apps.get_model("workspaces", "BoardColumn")
    UserSettings = apps.get_model("preferences", "UserSettings")

    for board in Board.objects.filter(kind="personal").iterator():
        if BoardColumn.objects.filter(board=board, system_role="new-assigned").exists():
            continue
        enabled = (
            UserSettings.objects.filter(user_id=board.owner_id)
            .values_list("dynamic_new_columns", flat=True)
            .first()
        )
        if enabled is False:
            continue

        for column in BoardColumn.objects.filter(board=board).order_by("-position"):
            column.position += 1
            column.save(update_fields=("position", "updated_at"))

        BoardColumn.objects.create(
            board=board,
            title="Neu",
            color="#D5A646",
            position=0,
            is_fixed_position=True,
            is_dynamic=True,
            system_role="new-assigned",
        )


class Migration(migrations.Migration):
    """Hängt die persönliche Eingangsspalte an den aktuellen Workspace-Stand an."""

    dependencies = [
        ("preferences", "0001_initial"),
        ("workspaces", "0003_backfill_personal_boards"),
    ]

    operations = [
        migrations.RunPython(create_personal_intake_columns, migrations.RunPython.noop),
    ]
