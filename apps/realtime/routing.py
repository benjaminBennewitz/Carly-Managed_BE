# apps/realtime/routing.py
"""Routet authentifizierte WebSocket-Verbindungen."""

from django.urls import re_path

from apps.realtime.consumers import BoardConsumer, InboxConsumer

websocket_urlpatterns = [
    re_path(r"^ws/v1/boards/(?P<board_id>[0-9a-fA-F-]{36})/$", BoardConsumer.as_asgi()),
    re_path(r"^ws/v1/inbox/$", InboxConsumer.as_asgi()),
]
