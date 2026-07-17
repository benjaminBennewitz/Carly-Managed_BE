# apps/workspaces/choices.py
"""Bündelt stabile Auswahlwerte für Datenbank und API."""

from django.db import models


class WorkspaceRole(models.TextChoices):
    """Definiert die globalen Rollen innerhalb eines Workspaces."""

    OWNER = "owner", "Owner"
    MANAGER = "manager", "Manager"
    MEMBER = "member", "Mitglied"


class ProjectRole(models.TextChoices):
    """Definiert projektbezogene Verwaltungs- und Mitarbeitungsrechte."""

    MANAGER = "manager", "Manager"
    COLLABORATOR = "collaborator", "Mitwirkend"


class ProjectStatus(models.TextChoices):
    """Beschreibt den Lebenszyklus eines Projekts."""

    ACTIVE = "active", "Aktiv"
    COMPLETED = "completed", "Abgeschlossen"
    ARCHIVED = "archived", "Archiviert"


class BoardKind(models.TextChoices):
    """Unterscheidet persönliche und projektbezogene Boards."""

    PERSONAL = "personal", "Persönlich"
    PROJECT = "project", "Projekt"


class ColumnSystemRole(models.TextChoices):
    """Kennzeichnet dynamische oder fachlich reservierte Spalten."""

    NEW_ASSIGNED = "new-assigned", "Neu zugewiesen"
    POOL_REVIEW = "pool-review", "Pool-Prüfung"


class TaskPriority(models.TextChoices):
    """Spiegelt die im Angular-Frontend verwendeten Prioritäten."""

    HIGH = "hoch", "Hoch"
    MEDIUM = "mittel", "Mittel"
    LOW = "niedrig", "Niedrig"


class InvitationStatus(models.TextChoices):
    """Beschreibt den Status einer Workspace- oder Projekteinladung."""

    PENDING = "pending", "Offen"
    ACCEPTED = "accepted", "Angenommen"
    REVOKED = "revoked", "Widerrufen"
    EXPIRED = "expired", "Abgelaufen"


class JoinRequestStatus(models.TextChoices):
    """Beschreibt den Status einer Beitrittsanfrage."""

    PENDING = "pending", "Offen"
    APPROVED = "approved", "Genehmigt"
    REJECTED = "rejected", "Abgelehnt"


class RecurrenceScheduleType(models.TextChoices):
    """Definiert die unterstützten Wiederholungsmodelle."""

    WEEKLY_DAYS = "weekly_days", "Wochentage"
    INTERVAL_DAYS = "interval_days", "Tagesintervall"
    MONTHLY_DAY = "monthly_day", "Monatstag"


class AutomationTrigger(models.TextChoices):
    """Definiert serverseitig ausführbare Task-Ereignisse."""

    TASK_COMPLETED = "task.completed", "Task abgeschlossen"
    TASK_REOPENED = "task.reopened", "Task wieder geöffnet"
    TASK_CREATED = "task.created", "Task erstellt"
    TASK_ASSIGNED = "task.assigned", "Task zugewiesen"
    COLUMN_ENTERED = "column.entered", "Spalte betreten"
