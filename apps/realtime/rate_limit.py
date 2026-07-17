# apps/realtime/rate_limit.py
"""Begrenzt hochfrequente WebSocket-Nachrichten pro Verbindung."""

import time
from dataclasses import dataclass


@dataclass(slots=True)
class TokenBucket:
    """Implementiert einen einfachen Token-Bucket ohne persistente Nutzerdaten."""

    capacity: float
    refill_per_second: float
    tokens: float | None = None
    last_refill: float | None = None

    def __post_init__(self) -> None:
        """Initialisiert den Bucket vollständig gefüllt."""
        self.tokens = self.capacity
        self.last_refill = time.monotonic()

    def consume(self, amount: float = 1.0) -> bool:
        """Verbraucht Token oder lehnt die Nachricht ab."""
        now = time.monotonic()
        elapsed = now - (self.last_refill or now)
        self.last_refill = now
        self.tokens = min(self.capacity, (self.tokens or 0) + elapsed * self.refill_per_second)
        if self.tokens < amount:
            return False
        self.tokens -= amount
        return True
