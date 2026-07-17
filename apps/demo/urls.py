# apps/demo/urls.py
"""Routet ausschließlich Status und Reset der Demo-Daten."""

from django.urls import path

from apps.demo.views import DemoResetView, DemoStatusView

urlpatterns = [
    path("status/", DemoStatusView.as_view(), name="demo-status"),
    path("reset/", DemoResetView.as_view(), name="demo-reset"),
]
