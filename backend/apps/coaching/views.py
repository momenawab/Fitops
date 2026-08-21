"""Views for coaching package API endpoints."""

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.workspaces.views import resolve_active_coach_membership

from .models import Package
from .serializers import PackageSerializer


class PackageView(GenericAPIView):
    """List and create packages for the caller's active workspace."""

    def get(self, request):
        membership = resolve_active_coach_membership(request.user)
        packages = Package.objects.for_workspace(membership.workspace).order_by("-created_at")

        is_active = request.query_params.get("is_active")
        if is_active in {"true", "false"}:
            packages = packages.filter(is_active=is_active == "true")

        search = request.query_params.get("search")
        if search:
            packages = packages.filter(name__icontains=search)

        page = self.paginate_queryset(packages)
        if page is not None:
            return self.get_paginated_response(PackageSerializer(page, many=True).data)
        return Response(PackageSerializer(packages, many=True).data)

    def post(self, request):
        membership = resolve_active_coach_membership(request.user)
        serializer = PackageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(workspace=membership.workspace)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class PackageDetailView(APIView):
    """Retrieve, update, or hard-delete one package in the active workspace."""

    @staticmethod
    def _package(membership, package_id):
        return get_object_or_404(
            Package.objects.for_workspace(membership.workspace),
            pk=package_id,
        )

    def get(self, request, package_id):
        membership = resolve_active_coach_membership(request.user)
        package = self._package(membership, package_id)
        return Response(PackageSerializer(package).data)

    def patch(self, request, package_id):
        membership = resolve_active_coach_membership(request.user)
        package = self._package(membership, package_id)
        serializer = PackageSerializer(package, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, package_id):
        membership = resolve_active_coach_membership(request.user)
        package = self._package(membership, package_id)
        package.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PackageStateView(APIView):
    """Set a package's active state within the caller's active workspace."""

    is_active = None

    def post(self, request, package_id):
        membership = resolve_active_coach_membership(request.user)
        package = PackageDetailView._package(membership, package_id)
        if package.is_active != self.is_active:
            package.is_active = self.is_active
            package.save(update_fields=["is_active", "updated_at"])
        return Response(PackageSerializer(package).data)


class PackageActivateView(PackageStateView):
    """Activate a package."""

    is_active = True


class PackageDeactivateView(PackageStateView):
    """Deactivate a package."""

    is_active = False
