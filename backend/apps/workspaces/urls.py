"""URL routes for workspace API endpoints."""

from django.urls import path

from .views import WorkspaceBrandingView, WorkspaceCreateView, WorkspaceLogoUploadView

urlpatterns = [
    path("workspace", WorkspaceCreateView.as_view(), name="workspace-create"),
    path("workspace/branding", WorkspaceBrandingView.as_view(), name="workspace-branding"),
    path("workspace/logo", WorkspaceLogoUploadView.as_view(), name="workspace-logo"),
]
