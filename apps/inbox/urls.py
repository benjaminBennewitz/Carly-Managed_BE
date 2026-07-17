# apps/inbox/urls.py
"""Routet Benachrichtigungen und Gespräche."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.inbox.views import ConversationViewSet, NotificationViewSet

router = DefaultRouter()
router.register("notifications", NotificationViewSet, basename="notification")
router.register("conversations", ConversationViewSet, basename="conversation")

urlpatterns = [path("", include(router.urls))]
