# apps/accounts/validators.py
"""Erweitert die Django-Passwortprüfung um unsichtbare Zeichen."""

import re
from typing import Any

from django.core.exceptions import ValidationError

CONTROL_CHARACTERS = re.compile(r"[\x00-\x1F\x7F]")


class ControlCharacterPasswordValidator:
    """Verhindert schwer erkennbare Steuerzeichen in Passwörtern."""

    def validate(self, password: str, user: Any | None = None) -> None:
        """Lehnt Passwörter mit Steuerzeichen ab."""
        if CONTROL_CHARACTERS.search(password):
            raise ValidationError(
                "Das Passwort enthält unzulässige Steuerzeichen.",
                code="password_control_characters",
            )

    def get_help_text(self) -> str:
        """Beschreibt die zusätzliche Passwortanforderung."""
        return "Das Passwort darf keine unsichtbaren Steuerzeichen enthalten."
