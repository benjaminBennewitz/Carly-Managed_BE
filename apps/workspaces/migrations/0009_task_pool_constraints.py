# apps/workspaces/migrations/0009_task_pool_constraints.py
"""Sichert konsistente Poolaufgaben nach abgeschlossener Datenbereinigung."""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Legt Pool-Constraints erst nach dem Commit der Datenmigration an."""

    dependencies = [("workspaces", "0008_task_pool_constraints")]

    operations = [
        migrations.AddConstraint(
            model_name="task",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(is_shared_pool=False)
                    | models.Q(assignee__isnull=True)
                ),
                name="task_pool_requires_unassigned",
            ),
        ),
        migrations.AddConstraint(
            model_name="task",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(is_shared_pool=False)
                    | models.Q(column__isnull=True)
                ),
                name="task_pool_requires_no_column",
            ),
        ),
    ]
