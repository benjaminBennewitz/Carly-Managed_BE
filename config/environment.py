# config/environment.py
"""Lädt die passende ENV-Datei vor der Initialisierung von Django."""

from __future__ import annotations

import os
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parents[1]
_ENV_FILES = {
    "development": ".env.local",
    "local": ".env.local",
    "prod": ".env.prod",
    "production": ".env.prod",
    "test": None,
}
_SETTINGS_MODULES = {
    "development": "config.settings.development",
    "local": "config.settings.development",
    "prod": "config.settings.production",
    "production": "config.settings.production",
    "test": "config.settings.test",
}


def load_environment() -> Path | None:
    """Lädt eine ENV-Datei und setzt das passende Django-Settings-Modul.

    Bereits gesetzte Prozessvariablen haben immer Vorrang vor Dateiwerten. Lokal
    wird standardmäßig ``.env.local`` verwendet. Für Produktion muss der Prozess
    ``DJANGO_ENV=production`` oder ``CARLY_ENV_FILE=.env.prod`` setzen.
    """
    requested_environment = os.getenv("DJANGO_ENV", "local").strip().lower()
    explicit_file = os.getenv("CARLY_ENV_FILE", "").strip()
    file_name = explicit_file or _ENV_FILES.get(requested_environment, ".env.local")
    env_path = BASE_DIR / file_name if file_name else None

    if env_path and env_path.is_file():
        environ.Env.read_env(env_path, overwrite=False)

    resolved_environment = os.getenv("DJANGO_ENV", requested_environment).strip().lower()
    settings_module = _SETTINGS_MODULES.get(
        resolved_environment,
        "config.settings.development",
    )
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", settings_module)
    return env_path if env_path and env_path.is_file() else None
