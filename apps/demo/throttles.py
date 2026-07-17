# apps/demo/throttles.py
"""Schützt den destruktiven Demo-Reset vor versehentlichen Wiederholungen."""

from rest_framework.throttling import UserRateThrottle


class DemoResetRateThrottle(UserRateThrottle):
    """Begrenzt Reset-Aufrufe je Administrationskonto."""

    scope = "demo_reset"
