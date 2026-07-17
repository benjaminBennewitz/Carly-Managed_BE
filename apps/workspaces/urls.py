# apps/workspaces/urls.py
"""Routet Workspace-, Projekt-, Board- und Task-Endpunkte."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.workspaces.views import (
    AttachmentDownloadView,
    AutomationRuleViewSet,
    BoardColumnViewSet,
    BoardViewSet,
    DashboardView,
    GlobalSearchView,
    InvitationViewSet,
    JoinRequestViewSet,
    ProjectViewSet,
    TaskViewSet,
    WorkspaceViewSet,
)

router = DefaultRouter()
router.register("projects", ProjectViewSet, basename="project")
router.register("boards", BoardViewSet, basename="board")
router.register("columns", BoardColumnViewSet, basename="column")
router.register("tasks", TaskViewSet, basename="task")
router.register("automations", AutomationRuleViewSet, basename="automation")
router.register("invitations", InvitationViewSet, basename="invitation")
router.register("join-requests", JoinRequestViewSet, basename="join-request")
router.register("", WorkspaceViewSet, basename="workspace")

urlpatterns = [
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("search/", GlobalSearchView.as_view(), name="global-search"),
    path(
        "attachments/<uuid:attachment_id>/download/",
        AttachmentDownloadView.as_view(),
        name="attachment-download",
    ),
    path("", include(router.urls)),
]
