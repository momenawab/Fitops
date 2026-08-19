"""Root URL configuration for FitOps."""

from django.urls import include, path

urlpatterns = [
    path("api/v1/", include("apps.accounts.urls")),
    path("api/v1/", include("apps.workspaces.urls")),
    path("api/v1/", include("apps.coaching.urls")),
]
