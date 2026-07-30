# apps/preferences/migrations/0002_carly_economy.py
"""Erweitert Carly um Economy, Decay, Inventar und Reward-Ledger."""

import apps.preferences.models
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
import django.utils.timezone
import uuid


class Migration(migrations.Migration):
    """Führt die serverautoritiven Tamagotchi- und Reward-Felder ein."""

    dependencies = [
        ("preferences", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="carlystate",
            name="aura_until",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="carlystate",
            name="credits",
            field=models.PositiveIntegerField(default=40),
        ),
        migrations.AddField(
            model_name="carlystate",
            name="inventory",
            field=models.JSONField(default=apps.preferences.models.default_carly_inventory),
        ),
        migrations.AddField(
            model_name="carlystate",
            name="last_affection_decay_at",
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.AddField(
            model_name="carlystate",
            name="last_energy_decay_at",
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.AddField(
            model_name="carlystate",
            name="last_satiety_decay_at",
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.AddField(
            model_name="carlystate",
            name="moon_until",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="carlystate",
            name="reward_popups_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="carlystate",
            name="show_credit_rewards",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="carlystate",
            name="show_xp_rewards",
            field=models.BooleanField(default=True),
        ),
        migrations.CreateModel(
            name="CarlyRewardLog",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("event_type", models.CharField(max_length=40)),
                ("event_key", models.CharField(max_length=220)),
                ("source_type", models.CharField(blank=True, default="", max_length=40)),
                ("source_id", models.CharField(blank=True, default="", max_length=80)),
                ("xp", models.PositiveSmallIntegerField(default=0)),
                ("credits", models.PositiveIntegerField(default=0)),
                ("multiplier", models.DecimalField(decimal_places=2, default=1, max_digits=4)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="carly_rewards",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at",),
                "indexes": [
                    models.Index(fields=["user", "created_at"], name="carly_reward_user_time_idx"),
                    models.Index(
                        fields=["user", "event_type", "created_at"],
                        name="carly_reward_type_time_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("user", "event_key"),
                        name="carly_reward_event_unique",
                    )
                ],
            },
        ),
    ]
