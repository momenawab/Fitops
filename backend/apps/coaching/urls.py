"""URL routes for coaching package API endpoints."""

from django.urls import path

from .views import PackageDetailView, PackageView

urlpatterns = [
    path("packages", PackageView.as_view(), name="package-list"),
    path("packages/<uuid:package_id>", PackageDetailView.as_view(), name="package-detail"),
]
