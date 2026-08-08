# apps/workspaces/migrations/0003_backfill_personal_boards.py
"""Ergänzt persönliche Boards für bereits bestehende Workspace-Mitgliedschaften."""

from django.db import migrations


DEFAULT_COLUMNS = (
    ("Offen", "#6558d3"),
    ("In Arbeit", "#d68635"),
    ("Erledigt", "#4c9b70"),
)


def create_missing_personal_boards(apps, schema_editor) -> None:
    """Erstellt pro aktiver Mitgliedschaft genau ein persönliches Workspace-Board."""
    WorkspaceMembership = apps.get_model("workspaces", "WorkspaceMembership")
    Board = apps.get_model("workspaces", "Board")
    BoardColumn = apps.get_model("workspaces", "BoardColumn")

    memberships = WorkspaceMembership.objects.filter(is_active=True).values_list(
        "workspace_id", "user_id"
    )
    for workspace_id, user_id in memberships.iterator():
        board, created = Board.objects.get_or_create(
            workspace_id=workspace_id,
            owner_id=user_id,
            kind="personal",
            defaults={"title": "Mein Board"},
        )
        if not created:
            continue
        BoardColumn.objects.bulk_create(
            [
                BoardColumn(
                    board_id=board.id,
                    title=title,
                    color=color,
                    position=position,
                )
                for position, (title, color) in enumerate(DEFAULT_COLUMNS)
            ]
        )


class Migration(migrations.Migration):
    """Führt ausschließlich den bestehenden Datenbestand auf den neuen Standard."""

    dependencies = [("workspaces", "0002_alter_workspaceinvitation_status")]

    operations = [
        migrations.RunPython(create_missing_personal_boards, migrations.RunPython.noop),
    ]
