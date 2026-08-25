"""Views for public workspace endpoints."""

from rest_framework import exceptions
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import CoachProfile, Membership
from apps.coaching.models import Package
from apps.coaching.serializers import PackageSerializer

from .models import Workspace
from .public_serializers import PublicCoachSerializer, PublicWorkspaceSerializer


def resolve_public_workspace(slug):
    """Resolve an active workspace from a public slug, or 404 indistinguishably."""
    try:
        return Workspace.objects.get(slug=slug, status=Workspace.Status.ACTIVE)
    except Workspace.DoesNotExist:
        raise exceptions.NotFound() from None


class PublicCoachView(APIView):
    """Return a public coach page for an active workspace slug."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, slug):
        """Return public workspace branding, owner profile, and active packages."""
        workspace = resolve_public_workspace(slug)

        owner_membership = (
            Membership.objects.filter(
                workspace=workspace,
                role=Membership.Role.OWNER,
                status=Membership.Status.ACTIVE,
            )
            .select_related("user")
            .order_by("created_at")
            .first()
        )
        coach_profile = None
        if owner_membership is not None:
            coach_profile = CoachProfile.objects.filter(user=owner_membership.user).first()

        packages = (
            Package.objects.for_workspace(workspace).filter(is_active=True).order_by("-created_at")
        )
        return Response(
            {
                "workspace": PublicWorkspaceSerializer(workspace).data,
                "coach": PublicCoachSerializer(coach_profile).data if coach_profile else None,
                "packages": PackageSerializer(packages, many=True).data,
            }
        )


class PublicPackagesView(GenericAPIView):
    """Return paginated active packages for an active public workspace."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, slug):
        """Return active workspace packages in descending creation order."""
        workspace = resolve_public_workspace(slug)
        packages = (
            Package.objects.for_workspace(workspace).filter(is_active=True).order_by("-created_at")
        )
        page = self.paginate_queryset(packages)
        if page is not None:
            return self.get_paginated_response(PackageSerializer(page, many=True).data)
        return Response(PackageSerializer(packages, many=True).data)
