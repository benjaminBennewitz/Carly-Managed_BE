# apps/realtime/presence.py
"""Verwaltet flüchtige anwendungsweite Online-Präsenz über den Cache."""

import time
from collections.abc import Iterable
from typing import Any

from django.core.cache import cache

APP_PRESENCE_TTL_SECONDS = 90
APP_PRESENCE_KEY_PREFIX = "app-presence:"


def _key(user_id: Any) -> str:
    """Erzeugt einen stabilen Cache-Schlüssel ohne personenbezogene Nutzdaten."""
    return f"{APP_PRESENCE_KEY_PREFIX}{user_id}"


def join_app_presence(user_id: Any) -> bool:
    """Registriert eine App-Verbindung und meldet, ob der Nutzer neu online ist."""
    key = _key(user_id)
    now = time.time()
    current = cache.get(key)
    is_stale = not current or now - float(current.get("seen", 0)) > APP_PRESENCE_TTL_SECONDS
    connections = 0 if is_stale else max(0, int(current.get("connections", 0)))
    cache.set(
        key,
        {"connections": connections + 1, "seen": now},
        timeout=APP_PRESENCE_TTL_SECONDS * 2,
    )
    return connections == 0


def touch_app_presence(user_id: Any) -> None:
    """Verlängert die Präsenz einer bestehenden App-Verbindung per Heartbeat."""
    key = _key(user_id)
    current = cache.get(key)
    if not current:
        return
    current["seen"] = time.time()
    cache.set(key, current, timeout=APP_PRESENCE_TTL_SECONDS * 2)


def leave_app_presence(user_id: Any) -> bool:
    """Entfernt eine Verbindung und meldet erst die letzte Sitzung als offline."""
    key = _key(user_id)
    current = cache.get(key)
    if not current:
        cache.delete(key)
        return True
    connections = max(0, int(current.get("connections", 1)) - 1)
    if connections == 0:
        cache.delete(key)
        return True
    cache.set(
        key,
        {"connections": connections, "seen": time.time()},
        timeout=APP_PRESENCE_TTL_SECONDS * 2,
    )
    return False


def online_user_ids(user_ids: Iterable[Any]) -> set[str]:
    """Liefert die aktuell im App-Shell verbundenen Nutzer aus einer ID-Menge."""
    normalized_ids = [str(user_id) for user_id in user_ids]
    values = cache.get_many({_key(user_id) for user_id in normalized_ids})
    now = time.time()
    return {
        user_id
        for user_id in normalized_ids
        if (value := values.get(_key(user_id)))
        and int(value.get("connections", 0)) > 0
        and now - float(value.get("seen", 0)) <= APP_PRESENCE_TTL_SECONDS
    }
