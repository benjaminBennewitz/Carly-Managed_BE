# apps/realtime/consumers.py
"""Validiert und verteilt flüchtige Board- und Inbox-Ereignisse."""

import math
import time
from typing import Any

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.core.cache import cache

from apps.realtime.events import board_group_name, inbox_group_name
from apps.realtime.rate_limit import TokenBucket


class BoardConsumer(AsyncJsonWebsocketConsumer):
    """Überträgt Presence, Cursor, Bearbeitung und kooperative Aktionen."""

    PRESENCE_TTL_SECONDS = 90

    async def connect(self) -> None:
        """Akzeptiert die Verbindung nur bei authentifiziertem Board-Zugriff."""
        user = self.scope["user"]
        if not user.is_authenticated:
            await self.close(code=4401)
            return
        self.board_id = self.scope["url_route"]["kwargs"]["board_id"]
        if not await self._can_access_board(str(user.id), self.board_id):
            await self.close(code=4403)
            return
        self.group_name = board_group_name(self.board_id)
        self.bucket = TokenBucket(capacity=60, refill_per_second=30)
        self.cursor_bucket = TokenBucket(capacity=30, refill_per_second=20)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        user_id = str(user.id)
        is_first_connection, online_user_ids, editing = await self._presence_join(user_id)
        members = await self._member_payloads(online_user_ids, self.board_id)
        await self.send_json(
            {
                "type": "presence.snapshot",
                "payload": {"users": members, "editing": editing},
            }
        )
        if is_first_connection:
            member = await self._member_payload(user_id, self.board_id)
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "board.event",
                    "eventType": "presence.joined",
                    "payload": {"user": member},
                },
            )

    async def disconnect(self, close_code: int) -> None:
        """Meldet den Nutzer ab und entfernt die Gruppenmitgliedschaft."""
        if not hasattr(self, "group_name"):
            return
        user = self.scope["user"]
        user_id = str(user.id)
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        is_offline = await self._presence_leave(user_id)
        if is_offline:
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "board.event",
                    "eventType": "presence.left",
                    "payload": {"userId": user_id},
                },
            )

    async def receive_json(self, content: Any, **kwargs: Any) -> None:
        """Akzeptiert nur bekannte, größenbegrenzte Ereignistypen."""
        if not isinstance(content, dict) or not self.bucket.consume():
            await self.send_json(
                {"type": "error", "code": "rate_limited", "message": "Zu viele Ereignisse."}
            )
            return
        event_type = content.get("type")
        if event_type == "heartbeat":
            await self._presence_touch(str(self.scope["user"].id))
            await self.send_json({"type": "heartbeat.ack"})
            return
        if event_type == "cursor.move":
            await self._handle_cursor(content)
            return
        if event_type == "editing.changed":
            await self._handle_editing(content)
            return
        if event_type == "carly.coop":
            await self._handle_cooperative_action(content)
            return
        await self.send_json(
            {"type": "error", "code": "unsupported_event", "message": "Unbekannter Ereignistyp."}
        )

    async def _handle_cursor(self, content: dict[str, Any]) -> None:
        """Prüft normierte Koordinaten und verteilt sie ohne Persistenz."""
        if not self.cursor_bucket.consume():
            return
        try:
            x = float(content["x"])
            y = float(content["y"])
        except (KeyError, TypeError, ValueError):
            return
        if not all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in (x, y)):
            return
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "board.event",
                "eventType": "cursor.moved",
                "payload": {"userId": str(self.scope["user"].id), "x": x, "y": y},
            },
        )

    async def _handle_editing(self, content: dict[str, Any]) -> None:
        """Prüft den Task-Zugriff vor einem Bearbeitungshinweis."""
        task_id = str(content.get("taskId", ""))[:36]
        active = bool(content.get("active", False))
        if task_id and not await self._task_belongs_to_board(task_id, self.board_id):
            return
        user_id = str(self.scope["user"].id)
        await self._presence_editing(user_id, task_id if active and task_id else None)
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "board.event",
                "eventType": "editing.changed",
                "payload": {
                    "userId": user_id,
                    "taskId": task_id or None,
                    "active": active,
                },
            },
        )

    async def _handle_cooperative_action(self, content: dict[str, Any]) -> None:
        """Löst definierte Carly-Aktionen erst mit zwei anwesenden Personen aus."""
        action = str(content.get("action", ""))
        if action not in {"high_five", "focus_start"}:
            return
        cache_key = f"carly-coop:{self.board_id}:{action}"
        current = await self._cache_get(cache_key) or []
        user_id = str(self.scope["user"].id)
        participants = [value for value in current if value != user_id]
        participants.append(user_id)
        participants = participants[-2:]
        await self._cache_set(cache_key, participants, 30)
        if len(set(participants)) < 2:
            await self.send_json({"type": "carly.coop.waiting", "action": action})
            return
        await self._cache_delete(cache_key)
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "board.event",
                "eventType": "carly.coop.completed",
                "payload": {"action": action, "participantIds": participants},
            },
        )

    async def board_event(self, event: dict[str, Any]) -> None:
        """Leitet ein validiertes Gruppenereignis an den Client weiter."""
        await self.send_json({"type": event["eventType"], "payload": event["payload"]})

    @database_sync_to_async
    def _can_access_board(self, user_id: str, board_id: str) -> bool:
        """Prüft den Zugriff ausschließlich gegen persistente Berechtigungen."""
        from apps.accounts.models import User
        from apps.workspaces.selectors import boards_for_user

        user = User.objects.filter(pk=user_id, is_active=True).first()
        return bool(user and boards_for_user(user).filter(pk=board_id).exists())

    @database_sync_to_async
    def _member_payloads(self, user_ids: list[str], board_id: str) -> list[dict[str, Any]]:
        """Liefert Presence-Daten für alle aktuell bekannten Boardmitglieder."""
        from apps.workspaces.models import Board, WorkspaceMembership
        from apps.workspaces.serializers import WorkspaceMemberSerializer

        board = Board.objects.filter(pk=board_id).first()
        if board is None:
            return []
        memberships = WorkspaceMembership.objects.select_related("user").filter(
            workspace=board.workspace, user_id__in=user_ids, is_active=True
        )
        return list(
            WorkspaceMemberSerializer(
                memberships, many=True, context={"online_user_ids": set(user_ids)}
            ).data
        )

    @database_sync_to_async
    def _member_payload(self, user_id: str, board_id: str) -> dict[str, Any] | None:
        """Liefert kompakte Presence-Daten aus der Workspace-Mitgliedschaft."""
        from apps.workspaces.models import Board, WorkspaceMembership
        from apps.workspaces.serializers import WorkspaceMemberSerializer

        board = Board.objects.filter(pk=board_id).first()
        if board is None:
            return None
        membership = (
            WorkspaceMembership.objects.select_related("user")
            .filter(workspace=board.workspace, user_id=user_id, is_active=True)
            .first()
        )
        return (
            WorkspaceMemberSerializer(
                membership, context={"online_user_ids": {user_id}}
            ).data
            if membership
            else None
        )

    @database_sync_to_async
    def _presence_join(
        self, user_id: str
    ) -> tuple[bool, list[str], list[dict[str, Any]]]:
        """Registriert eine Verbindung und liefert Presence samt aktiver Bearbeitungen."""
        key = f"board-presence:{self.board_id}"
        now = time.time()
        presence = cache.get(key) or {}
        cleaned = {
            uid: value
            for uid, value in presence.items()
            if now - float(value.get("seen", 0)) <= self.PRESENCE_TTL_SECONDS
        }
        current = cleaned.get(user_id, {"connections": 0, "seen": now, "taskId": None})
        first_connection = int(current.get("connections", 0)) <= 0
        cleaned[user_id] = {
            "connections": int(current.get("connections", 0)) + 1,
            "seen": now,
            "taskId": current.get("taskId"),
        }
        cache.set(key, cleaned, timeout=self.PRESENCE_TTL_SECONDS * 2)
        editing = [
            {"userId": uid, "taskId": value.get("taskId"), "active": True}
            for uid, value in cleaned.items()
            if value.get("taskId")
        ]
        return first_connection, list(cleaned), editing

    @database_sync_to_async
    def _presence_touch(self, user_id: str) -> None:
        """Aktualisiert den letzten Heartbeat einer aktiven Boardverbindung."""
        key = f"board-presence:{self.board_id}"
        presence = cache.get(key) or {}
        current = presence.get(user_id)
        if current is None:
            return
        current["seen"] = time.time()
        presence[user_id] = current
        cache.set(key, presence, timeout=self.PRESENCE_TTL_SECONDS * 2)

    @database_sync_to_async
    def _presence_editing(self, user_id: str, task_id: str | None) -> None:
        """Speichert den flüchtigen Bearbeitungszustand für neue Boardverbindungen."""
        key = f"board-presence:{self.board_id}"
        presence = cache.get(key) or {}
        current = presence.get(user_id)
        if current is None:
            return
        current["taskId"] = task_id
        current["seen"] = time.time()
        presence[user_id] = current
        cache.set(key, presence, timeout=self.PRESENCE_TTL_SECONDS * 2)

    @database_sync_to_async
    def _presence_leave(self, user_id: str) -> bool:
        """Entfernt eine Verbindung und meldet erst die letzte Sitzung als offline."""
        key = f"board-presence:{self.board_id}"
        presence = cache.get(key) or {}
        current = presence.get(user_id)
        if current is None:
            return True
        connections = max(0, int(current.get("connections", 1)) - 1)
        if connections == 0:
            presence.pop(user_id, None)
            cache.set(key, presence, timeout=self.PRESENCE_TTL_SECONDS * 2)
            return True
        current["connections"] = connections
        current["seen"] = time.time()
        presence[user_id] = current
        cache.set(key, presence, timeout=self.PRESENCE_TTL_SECONDS * 2)
        return False

    @database_sync_to_async
    def _task_belongs_to_board(self, task_id: str, board_id: str) -> bool:
        """Verhindert Bearbeitungshinweise für fremde Tasks."""
        from apps.workspaces.models import Task

        return Task.objects.filter(pk=task_id, board_id=board_id, archived_at__isnull=True).exists()

    @staticmethod
    async def _cache_get(key: str) -> Any:
        """Liest einen flüchtigen Kooperationszustand asynchron."""
        from asgiref.sync import sync_to_async

        return await sync_to_async(cache.get)(key)

    @staticmethod
    async def _cache_set(key: str, value: Any, timeout: int) -> None:
        """Speichert einen flüchtigen Kooperationszustand kurzzeitig."""
        from asgiref.sync import sync_to_async

        await sync_to_async(cache.set)(key, value, timeout)

    @staticmethod
    async def _cache_delete(key: str) -> None:
        """Entfernt einen abgeschlossenen Kooperationszustand."""
        from asgiref.sync import sync_to_async

        await sync_to_async(cache.delete)(key)


class InboxConsumer(AsyncJsonWebsocketConsumer):
    """Überträgt persönliche Inbox-Änderungen ohne Client-Schreibzugriff."""

    async def connect(self) -> None:
        """Akzeptiert ausschließlich authentifizierte Sitzungen."""
        user = self.scope["user"]
        if not user.is_authenticated:
            await self.close(code=4401)
            return
        self.group_name = inbox_group_name(user.id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code: int) -> None:
        """Entfernt die Verbindung aus der persönlichen Gruppe."""
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content: Any, **kwargs: Any) -> None:
        """Erlaubt Clients nur einen Heartbeat."""
        if isinstance(content, dict) and content.get("type") == "heartbeat":
            await self.send_json({"type": "heartbeat.ack"})

    async def inbox_event(self, event: dict[str, Any]) -> None:
        """Leitet ein persönliches Inbox-Ereignis weiter."""
        await self.send_json({"type": event["eventType"], "payload": event["payload"]})
