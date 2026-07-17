# config/celery.py
"""Konfiguriert Celery für Automationen und Wiederholungsaufgaben."""

from celery import Celery

from config.environment import load_environment

load_environment()

app = Celery("carly_managed")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
