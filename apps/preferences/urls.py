# apps/preferences/urls.py
"""Routet Einstellungen und Carly-Interaktionen."""

from django.urls import path

from apps.preferences.views import AppSettingsView, CarlyActionView, CarlyStateView

urlpatterns = [
    path("settings/", AppSettingsView.as_view(), name="settings"),
    path("carly/", CarlyStateView.as_view(), name="carly-state"),
    path("carly/actions/<str:action>/", CarlyActionView.as_view(), name="carly-action"),
]
