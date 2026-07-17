# apps/common/models.py
"""Stellt abstrakte UUID-, Zeit- und Versionsmodelle bereit."""

import uuid

from django.db import models


class UUIDModel(models.Model):
    """Verwendet nicht erratbare UUIDs als Primärschlüssel."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class TimeStampedModel(models.Model):
    """Speichert Erstellungs- und Änderungszeitpunkt konsistent in UTC."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class VersionedModel(models.Model):
    """Ermöglicht optimistische Sperren gegen unbemerkte Überschreibungen."""

    version = models.PositiveBigIntegerField(default=1)

    class Meta:
        abstract = True
