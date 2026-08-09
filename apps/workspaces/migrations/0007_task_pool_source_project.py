# apps/workspaces/migrations/0007_task_pool_source_project.py
"""Ergänzt ausschließlich den Projektursprung übernommener Poolaufgaben."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Legt das FK-Feld in einer eigenen PostgreSQL-Transaktion an."""

    dependencies = [("workspaces", "0006_global_personal_board_constraint")]

    operations = [
        migrations.AddField(
            model_name="task",
            name="pool_source_project",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="claimed_pool_tasks",
                to="workspaces.project",
            ),
        ),
    ]
