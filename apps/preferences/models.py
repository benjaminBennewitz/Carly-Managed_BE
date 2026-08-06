# apps/preferences/models.py
"""Definiert barrierearme Einstellungen und servergeprüften Carly-Fortschritt."""

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel, UUIDModel, VersionedModel
from apps.common.validators import reject_control_characters


class ColorVisionMode(models.TextChoices):
    """Definiert unterstützte Farbseh-Anpassungen."""

    STANDARD = "standard", "Standard"
    PROTANOPIA = "protanopia", "Protanopie"
    DEUTERANOPIA = "deuteranopia", "Deuteranopie"
    TRITANOPIA = "tritanopia", "Tritanopie"
    MONOCHROME = "monochrome", "Monochrom"


class AccessibilityFontSize(models.TextChoices):
    """Definiert die unterstützten Schriftgrößen."""

    NORMAL = "normal", "Normal"
    LARGE = "large", "Groß"
    XLARGE = "xlarge", "Sehr groß"


DEFAULT_ALARMS = {
    "assignment": True,
    "taskMove": True,
    "taskCompleted": True,
    "taskReopened": True,
    "taskChanged": True,
    "taskDeleted": True,
    "projectCreated": True,
    "projectChanged": True,
    "projectCompleted": True,
    "projectArchived": True,
    "projectDeleted": True,
    "members": True,
    "directMessages": True,
}


def default_alarms() -> dict[str, bool]:
    """Liefert eine unabhängige Kopie der Standardalarme."""
    return DEFAULT_ALARMS.copy()


class UserSettings(UUIDModel, TimeStampedModel, VersionedModel):
    """Speichert persönliche Darstellung, Verhalten und optionale Werkzeuge."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="app_settings",
    )
    color_vision_mode = models.CharField(
        max_length=20,
        choices=ColorVisionMode.choices,
        default=ColorVisionMode.STANDARD,
    )
    neuro_mode = models.BooleanField(default=False)
    reduce_motion = models.BooleanField(default=False)
    reduce_hover = models.BooleanField(default=False)
    magnifier = models.BooleanField(default=False)
    font_size = models.CharField(
        max_length=12,
        choices=AccessibilityFontSize.choices,
        default=AccessibilityFontSize.NORMAL,
    )
    high_contrast = models.BooleanField(default=False)
    dynamic_new_columns = models.BooleanField(default=True)
    tooltips_enabled = models.BooleanField(default=True)
    allow_invites = models.BooleanField(default=True)
    hide_real_name = models.BooleanField(default=False)
    real_name = models.CharField(
        max_length=60, blank=True, default="", validators=[reject_control_characters]
    )
    nickname = models.CharField(
        max_length=60, blank=True, default="", validators=[reject_control_characters]
    )
    alarms = models.JSONField(default=default_alarms)
    pomodoro = models.BooleanField(default=False)
    task_timer = models.BooleanField(default=False)
    weather = models.BooleanField(default=False)
    weather_location = models.CharField(
        max_length=120, blank=True, default="", validators=[reject_control_characters]
    )

    def __str__(self) -> str:
        """Liefert das zugehörige Konto."""
        return f"Einstellungen: {self.user}"


def default_carly_inventory() -> dict[str, int]:
    """Liefert ein unabhängiges Startinventar für Carly."""
    return {"fish": 1, "berry": 0, "cookie": 0, "potion": 0}


class CarlyMood(models.TextChoices):
    """Spiegelt die im Frontend verwendeten Carly-Stimmungen."""

    HAPPY = "glücklich", "Glücklich"
    CURIOUS = "neugierig", "Neugierig"
    TIRED = "müde", "Müde"
    HUNGRY = "hungrig", "Hungrig"


class CarlyState(UUIDModel, TimeStampedModel, VersionedModel):
    """Speichert optionale Carly-Einstellungen und begrenzten Fortschritt."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="carly_state",
    )
    enabled = models.BooleanField(default=True)
    show_globally = models.BooleanField(default=True)
    messages_enabled = models.BooleanField(default=True)
    task_reactions_enabled = models.BooleanField(default=True)
    auto_sleep = models.BooleanField(default=True)
    reduce_animations = models.BooleanField(default=False)
    reward_popups_enabled = models.BooleanField(default=True)
    show_xp_rewards = models.BooleanField(default=True)
    show_credit_rewards = models.BooleanField(default=True)
    level = models.PositiveIntegerField(default=1)
    experience = models.PositiveIntegerField(default=0)
    credits = models.PositiveIntegerField(default=40)
    inventory = models.JSONField(default=default_carly_inventory)
    affection = models.PositiveSmallIntegerField(default=50)
    energy = models.PositiveSmallIntegerField(default=80)
    satiety = models.PositiveSmallIntegerField(default=70)
    streak = models.PositiveIntegerField(default=0)
    mood = models.CharField(max_length=16, choices=CarlyMood.choices, default=CarlyMood.CURIOUS)
    is_sleeping = models.BooleanField(default=False)
    last_message = models.CharField(
        max_length=300, default="Carly ist bereit.", validators=[reject_control_characters]
    )
    position_x = models.FloatField(default=0.85)
    last_productive_day = models.DateField(blank=True, null=True)
    last_affection_decay_at = models.DateTimeField(default=timezone.now)
    last_energy_decay_at = models.DateTimeField(default=timezone.now)
    last_satiety_decay_at = models.DateTimeField(default=timezone.now)
    aura_until = models.DateTimeField(blank=True, null=True)
    moon_until = models.DateTimeField(blank=True, null=True)
    berry_focus_until = models.DateTimeField(blank=True, null=True)
    berry_focus_charges = models.PositiveSmallIntegerField(default=0)
    cookie_until = models.DateTimeField(blank=True, null=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(affection__lte=100), name="carly_affection_max"
            ),
            models.CheckConstraint(condition=models.Q(energy__lte=100), name="carly_energy_max"),
            models.CheckConstraint(condition=models.Q(satiety__lte=100), name="carly_satiety_max"),
            models.CheckConstraint(
                condition=models.Q(position_x__gte=0.0) & models.Q(position_x__lte=1.0),
                name="carly_position_range",
            ),
        ]

    def __str__(self) -> str:
        """Liefert die zugehörige Carly-Instanz."""
        return f"Carly von {self.user}"


class CarlyActionLog(UUIDModel, TimeStampedModel):
    """Begrenzt Interaktionen serverseitig nach Aktion und Tag."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="carly_actions",
    )
    action = models.CharField(max_length=32)
    points = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("user", "action", "created_at"), name="carly_action_limit_idx")
        ]


class CarlyRewardLog(UUIDModel, TimeStampedModel):
    """Protokolliert serverseitig berechnete XP- und Credit-Belohnungen idempotent."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="carly_rewards",
    )
    event_type = models.CharField(max_length=40)
    event_key = models.CharField(max_length=220)
    source_type = models.CharField(max_length=40, blank=True, default="")
    source_id = models.CharField(max_length=80, blank=True, default="")
    xp = models.PositiveSmallIntegerField(default=0)
    credits = models.PositiveIntegerField(default=0)
    multiplier = models.DecimalField(max_digits=4, decimal_places=2, default=1)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("user", "event_key"),
                name="carly_reward_event_unique",
            ),
        ]
        indexes = [
            models.Index(fields=("user", "created_at"), name="carly_reward_user_time_idx"),
            models.Index(
                fields=("user", "event_type", "created_at"),
                name="carly_reward_type_time_idx",
            ),
        ]

    def __str__(self) -> str:
        """Liefert eine kompakte Beschreibung für Administration und Debugging."""
        return f"{self.user}: {self.event_type} (+{self.xp} XP, +{self.credits} Credits)"
