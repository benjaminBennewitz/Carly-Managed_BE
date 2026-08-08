# apps/workspaces/migrations/0006_global_personal_board_constraint.py
"""Erzwingt genau ein persönliches Board pro Nutzer."""

from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    """Trennt die Constraint-Änderung von der vorherigen Datenmigration."""

    dependencies = [
        ("workspaces", "0005_global_personal_board"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="board",
            name="personal_board_per_workspace_user",
        ),
        migrations.AddConstraint(
            model_name="board",
            constraint=models.UniqueConstraint(
                condition=Q(kind="personal"),
                fields=("owner",),
                name="personal_board_per_user",
            ),
        ),
    ]
