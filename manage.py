# manage.py
"""Startpunkt für administrative Django-Befehle."""

import sys

from config.environment import load_environment


def main() -> None:
    """Führt einen Django-Verwaltungsbefehl aus."""
    load_environment()
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Django konnte nicht importiert werden. Ist die virtuelle Umgebung aktiv?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
