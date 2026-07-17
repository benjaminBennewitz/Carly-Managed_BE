# config/urls.py
"""Bündelt die versionierten HTTP-Endpunkte der Anwendung."""

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="api-schema"),
        name="api-docs",
    ),
    path("api/v1/", include("apps.common.urls")),
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/workspaces/", include("apps.workspaces.urls")),
    path("api/v1/inbox/", include("apps.inbox.urls")),
    path("api/v1/preferences/", include("apps.preferences.urls")),
    path("api/v1/demo/", include("apps.demo.urls")),
]
