# apps/workspaces/migrations/0002_alter_workspaceinvitation_status.py
"""Ergänzt den expliziten Status für abgelehnte Workspace-Einladungen."""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Aktualisiert ausschließlich die Choice-Metadaten des Statusfelds."""

    dependencies = [
        ("workspaces", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="workspaceinvitation",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Offen"),
                    ("accepted", "Angenommen"),
                    ("rejected", "Abgelehnt"),
                    ("revoked", "Widerrufen"),
                    ("expired", "Abgelaufen"),
                ],
                default="pending",
                max_length=16,
            ),
        ),
    ]
