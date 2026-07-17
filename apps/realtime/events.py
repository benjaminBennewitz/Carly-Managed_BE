# apps/realtime/events.py
"""Sendet serverseitige Fachereignisse an WebSocket-Gruppen."""

from collections.abc import Iterable
from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def board_group_name(board_id: Any) -> str:
    """Erzeugt einen zulässigen Channels-Gruppennamen."""
    return f"board_{str(board_id).replace('-', '')}"


def inbox_group_name(user_id: Any) -> str:
    """Erzeugt einen persönlichen Inbox-Gruppennamen."""
    return f"inbox_{str(user_id).replace('-', '')}"


def broadcast_board_event(board_id: Any, event_type: str, payload: dict[str, Any]) -> None:
    """Überträgt ein persistiertes Board-Ereignis an verbundene Clients."""
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    async_to_sync(channel_layer.group_send)(
        board_group_name(board_id),
        {"type": "board.event", "eventType": event_type, "payload": payload},
    )


def broadcast_inbox_event(
    user_ids: Iterable[Any], event_type: str, payload: dict[str, Any]
) -> None:
    """Überträgt ein Inbox-Ereignis an alle betroffenen Nutzer."""
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    for user_id in user_ids:
        async_to_sync(channel_layer.group_send)(
            inbox_group_name(user_id),
            {"type": "inbox.event", "eventType": event_type, "payload": payload},
        )
