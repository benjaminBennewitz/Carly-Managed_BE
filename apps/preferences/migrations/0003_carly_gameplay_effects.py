# apps/preferences/migrations/0003_carly_gameplay_effects.py
"""Ergänzt zeitlich begrenzte Carly-Gameplay-Effekte."""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Speichert Mystik-Fokus und Sternenkeks-Bonus dauerhaft."""

    dependencies = [
        ("preferences", "0002_carly_economy"),
    ]

    operations = [
        migrations.AddField(
            model_name="carlystate",
            name="berry_focus_charges",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="carlystate",
            name="berry_focus_until",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="carlystate",
            name="cookie_until",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
