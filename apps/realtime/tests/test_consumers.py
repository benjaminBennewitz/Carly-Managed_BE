# apps/realtime/tests/test_consumers.py
"""Prüft Authentifizierung, Validierung und Board-Ereignisse per WebSocket."""

from typing import Any

import pytest
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone

from apps.accounts.models import User
from apps.realtime.rate_limit import TokenBucket
from apps.realtime.routing import websocket_urlpatterns
from apps.workspaces.models import Board
from apps.workspaces.services import bootstrap_personal_workspace

pytestmark = pytest.mark.django_db(transaction=True)


def create_user_context(email: str = "socket@example.test") -> tuple[User, Board]:
    """Erstellt einen Nutzer mit zugänglichem persönlichen Board."""
    user = User.objects.create_user(
        email=email,
        password="Fokus!Board-2026-sicher",
        display_name="Socket Test",
        privacy_acknowledged_at=timezone.now(),
    )
    bootstrap_personal_workspace(user)
    return user, Board.objects.get(owner=user)


@pytest.mark.asyncio
async def test_board_socket_rejects_anonymous_user() -> None:
    """Akzeptiert keine anonyme Verbindung zu einem Board-Kanal."""
    communicator = WebsocketCommunicator(
        URLRouter(websocket_urlpatterns),
        "/ws/v1/boards/00000000-0000-0000-0000-000000000000/",
    )
    communicator.scope["user"] = AnonymousUser()

    connected, close_code = await communicator.connect()

    assert connected is False
    assert close_code == 4401


@pytest.mark.asyncio
async def test_inbox_socket_only_accepts_heartbeat() -> None:
    """Bestätigt Heartbeats, ohne beliebige Client-Ereignisse zu verteilen."""
    user, _ = await _create_user_context_async("inbox@example.test")
    communicator = WebsocketCommunicator(
        URLRouter(websocket_urlpatterns),
        "/ws/v1/inbox/",
    )
    communicator.scope["user"] = user

    connected, _ = await communicator.connect()
    assert connected is True

    await communicator.send_json_to({"type": "heartbeat"})
    assert await communicator.receive_json_from() == {"type": "heartbeat.ack"}

    await communicator.send_json_to({"type": "client.write", "body": "nicht erlaubt"})
    assert await communicator.receive_nothing(timeout=0.05)
    await communicator.disconnect()


@pytest.mark.asyncio
async def test_board_socket_validates_and_broadcasts_events() -> None:
    """Überträgt nur normierte Cursorwerte und bekannte Ereignistypen."""
    user, board = await _create_user_context_async()
    communicator = WebsocketCommunicator(
        URLRouter(websocket_urlpatterns),
        f"/ws/v1/boards/{board.id}/",
    )
    communicator.scope["user"] = user

    connected, _ = await communicator.connect()
    assert connected is True
    joined = await communicator.receive_json_from()
    assert joined["type"] == "presence.joined"
    assert joined["payload"]["user"]["id"] == str(user.id)

    await communicator.send_json_to({"type": "cursor.move", "x": 0.25, "y": 0.75})
    cursor = await communicator.receive_json_from()
    assert cursor == {
        "type": "cursor.moved",
        "payload": {"userId": str(user.id), "x": 0.25, "y": 0.75},
    }

    await communicator.send_json_to({"type": "cursor.move", "x": 2, "y": 0})
    assert await communicator.receive_nothing(timeout=0.05)

    await communicator.send_json_to({"type": "unbekannt"})
    error = await communicator.receive_json_from()
    assert error["code"] == "unsupported_event"
    await communicator.disconnect()


def test_token_bucket_rejects_requests_after_capacity_is_exhausted(monkeypatch: Any) -> None:
    """Begrenzt Ereignisse deterministisch, bis neue Token verfügbar sind."""
    moments = iter((100.0, 100.0, 100.0, 100.0, 101.0))
    monkeypatch.setattr("apps.realtime.rate_limit.time.monotonic", lambda: next(moments))
    bucket = TokenBucket(capacity=2, refill_per_second=1)

    assert bucket.consume() is True
    assert bucket.consume() is True
    assert bucket.consume() is False
    assert bucket.consume() is True


async def _create_user_context_async(email: str = "socket@example.test") -> tuple[User, Board]:
    """Führt die synchrone Testdatenanlage aus einem Async-Test sicher aus."""
    from channels.db import database_sync_to_async

    return await database_sync_to_async(create_user_context)(email)
