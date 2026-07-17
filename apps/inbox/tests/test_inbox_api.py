# apps/inbox/tests/test_inbox_api.py
"""Prüft geschützte Benachrichtigungen und Konversationen."""

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.inbox.models import SystemNotification
from apps.workspaces.models import WorkspaceMembership
from apps.workspaces.services import bootstrap_personal_workspace

pytestmark = pytest.mark.django_db


def create_user(email: str, name: str) -> User:
    """Erstellt einen vollständigen Nutzerkontext."""
    user = User.objects.create_user(
        email=email,
        password="Fokus!Board-2026-sicher",
        display_name=name,
        privacy_acknowledged_at=timezone.now(),
    )
    bootstrap_personal_workspace(user)
    return user


def client_for(user: User) -> APIClient:
    """Authentifiziert einen API-Client."""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def test_notifications_are_strictly_recipient_scoped() -> None:
    """Verhindert das Lesen oder Markieren fremder Benachrichtigungen."""
    first = create_user("first@example.test", "First")
    second = create_user("second@example.test", "Second")
    notification = SystemNotification.objects.create(
        recipient=first,
        kind="system",
        title="Privat",
        body="Nur für First",
        icon="notifications",
    )
    second_client = client_for(second)
    assert (
        second_client.get(reverse("notification-detail", args=[notification.id])).status_code == 404
    )
    assert (
        second_client.post(reverse("notification-mark-read", args=[notification.id])).status_code
        == 404
    )


def test_conversation_requires_common_workspace_membership() -> None:
    """Erlaubt Gespräche nur zwischen aktiven Mitgliedern desselben Workspaces."""
    owner = create_user("owner@example.test", "Owner")
    member = create_user("member@example.test", "Member")
    external = create_user("external@example.test", "External")
    workspace = owner.owned_workspaces.get()
    WorkspaceMembership.objects.create(
        workspace=workspace,
        user=member,
        role="member",
        avatar_color="#6558d3",
    )
    client = client_for(owner)

    rejected = client.post(
        reverse("conversation-list"),
        {
            "workspaceId": str(workspace.id),
            "participantIds": [str(external.id)],
            "subject": "Nicht erlaubt",
            "body": "Diese Person ist extern.",
        },
        format="json",
    )
    assert rejected.status_code == 400

    accepted = client.post(
        reverse("conversation-list"),
        {
            "workspaceId": str(workspace.id),
            "participantIds": [str(member.id)],
            "subject": "Projektabstimmung",
            "body": "Lass uns den nächsten Schritt klären.",
        },
        format="json",
    )
    assert accepted.status_code == 201
    assert len(accepted.data["participants"]) == 2
    conversation_id = accepted.data["id"]
    assert (
        client_for(member).get(reverse("conversation-detail", args=[conversation_id])).status_code
        == 200
    )
    assert (
        client_for(external).get(reverse("conversation-detail", args=[conversation_id])).status_code
        == 404
    )
