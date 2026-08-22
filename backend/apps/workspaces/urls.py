"""URL routes for workspace API endpoints."""

from django.urls import path

from .public_views import PublicCoachView
from .views import (
    PaymentMethodDetailView,
    PaymentMethodView,
    WorkspaceBrandingView,
    WorkspaceCreateView,
    WorkspaceLogoUploadView,
)

urlpatterns = [
    path("workspace", WorkspaceCreateView.as_view(), name="workspace-create"),
    path("public/coaches/<slug:slug>", PublicCoachView.as_view(), name="public-coach"),
    path("workspace/branding", WorkspaceBrandingView.as_view(), name="workspace-branding"),
    path("workspace/logo", WorkspaceLogoUploadView.as_view(), name="workspace-logo"),
    path("workspace/payment-methods", PaymentMethodView.as_view(), name="payment-method-list"),
    path(
        "workspace/payment-methods/<uuid:payment_method_id>",
        PaymentMethodDetailView.as_view(),
        name="payment-method-detail",
    ),
]
