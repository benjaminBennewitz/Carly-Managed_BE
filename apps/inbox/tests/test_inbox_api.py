# apps/inbox/tests/test_inbox_api.py
"""Prüft geschützte Benachrichtigungen und Konversationen."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.inbox.models import SystemNotification
from apps.workspaces.models import Project, ProjectParticipant, WorkspaceMembership
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


def test_inbox_lists_can_be_limited_to_active_workspace() -> None:
    """Trennt Benachrichtigungen und Gespräche bei mehreren Workspaces vollständig."""
    owner = create_user("owner-scope@example.test", "Owner Scope")
    member = create_user("member-scope@example.test", "Member Scope")
    first_workspace = owner.owned_workspaces.get()
    second_workspace = member.owned_workspaces.get()
    WorkspaceMembership.objects.create(
        workspace=first_workspace, user=member, role="member", avatar_color="#6558d3"
    )
    SystemNotification.objects.create(
        recipient=member,
        workspace=first_workspace,
        kind="system",
        title="Team",
        body="Team",
        icon="group",
    )
    SystemNotification.objects.create(
        recipient=member,
        workspace=second_workspace,
        kind="system",
        title="Privat",
        body="Privat",
        icon="person",
    )

    response = client_for(member).get(
        reverse("notification-list"), {"workspaceId": str(first_workspace.id)}
    )
    assert response.status_code == 200
    data = response.data["results"] if isinstance(response.data, dict) else response.data
    assert [item["title"] for item in data] == ["Team"]


def test_project_guest_chat_stays_inside_shared_project_context() -> None:
    """Erlaubt Projektgästen Chats nur mit Personen aus demselben Projekt."""
    owner = create_user("owner-guest-chat@example.test", "Owner Guest Chat")
    guest = create_user("guest-chat@example.test", "Guest Chat")
    team_member = create_user("member-chat@example.test", "Member Chat")
    workspace = owner.owned_workspaces.get()
    WorkspaceMembership.objects.create(
        workspace=workspace,
        user=guest,
        role="member",
        avatar_color="#6558d3",
        is_project_guest=True,
    )
    WorkspaceMembership.objects.create(
        workspace=workspace,
        user=team_member,
        role="member",
        avatar_color="#6558d3",
    )
    project_response = client_for(owner).post(
        reverse("project-list"),
        {
            "workspaceId": str(workspace.id),
            "name": "Gastprojekt",
            "dueAt": str(timezone.localdate() + timedelta(days=30)),
        },
        format="json",
    )
    assert project_response.status_code == 201
    project = Project.objects.get(pk=project_response.data["id"])
    ProjectParticipant.objects.create(project=project, user=guest, role="collaborator")

    guest_client = client_for(guest)
    accepted = guest_client.post(
        reverse("conversation-list"),
        {
            "workspaceId": str(workspace.id),
            "participantIds": [str(owner.id)],
            "subject": "Projektabstimmung",
            "body": "Nur unser gemeinsames Projekt.",
        },
        format="json",
    )
    assert accepted.status_code == 201

    rejected = guest_client.post(
        reverse("conversation-list"),
        {
            "workspaceId": str(workspace.id),
            "participantIds": [str(team_member.id)],
            "subject": "Fremder Teamkontext",
            "body": "Dieser Chat darf nicht entstehen.",
        },
        format="json",
    )
    assert rejected.status_code == 400
