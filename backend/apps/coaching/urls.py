"""URL routes for coaching package API endpoints."""

from django.urls import path

from .views import (
    PackageActivateView,
    PackageDeactivateView,
    PackageDetailView,
    PackageDuplicateView,
    PackageView,
)

urlpatterns = [
    path("packages", PackageView.as_view(), name="package-list"),
    path("packages/<uuid:package_id>", PackageDetailView.as_view(), name="package-detail"),
    path(
        "packages/<uuid:package_id>/activate",
        PackageActivateView.as_view(),
        name="package-activate",
    ),
    path(
        "packages/<uuid:package_id>/deactivate",
        PackageDeactivateView.as_view(),
        name="package-deactivate",
    ),
    path(
        "packages/<uuid:package_id>/duplicate",
        PackageDuplicateView.as_view(),
        name="package-duplicate",
    ),
]
