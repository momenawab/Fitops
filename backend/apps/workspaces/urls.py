"""URL routes for workspace API endpoints."""

from django.urls import path

from .views import WorkspaceCreateView

urlpatterns = [
    path("workspace", WorkspaceCreateView.as_view(), name="workspace-create"),
]
