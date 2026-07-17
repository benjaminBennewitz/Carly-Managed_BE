# apps/demo/serializers.py
"""Beschreibt stabile Antworten für Status und Reset der Demo-Daten."""

from rest_framework import serializers


class DemoStatusSerializer(serializers.Serializer[dict]):
    """Liefert ausschließlich die für den Einstellungsbutton nötigen Angaben."""

    enabled = serializers.BooleanField()
    canReset = serializers.BooleanField()
    workspaceName = serializers.CharField()


class DemoResetResultSerializer(serializers.Serializer[dict]):
    """Bestätigt den neu erzeugten Workspace und seine Datensatzmengen."""

    workspaceId = serializers.UUIDField()
    workspaceName = serializers.CharField()
    projects = serializers.IntegerField(min_value=0)
    tasks = serializers.IntegerField(min_value=0)
    members = serializers.IntegerField(min_value=0)
    notifications = serializers.IntegerField(min_value=0)
