# apps/common/urls.py
"""Routet allgemeine Betriebsendpunkte."""

from django.urls import path

from apps.common.views import health_view

urlpatterns = [path("health/", health_view, name="health")]
