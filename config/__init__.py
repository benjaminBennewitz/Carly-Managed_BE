# config/__init__.py
"""Initialisiert die Celery-Anwendung gemeinsam mit Django."""

from config.celery import app as celery_app

__all__ = ("celery_app",)
