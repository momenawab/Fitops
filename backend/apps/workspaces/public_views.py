"""Views for public workspace endpoints."""

from rest_framework import exceptions
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import CoachProfile, Membership
from apps.coaching.models import Package
from apps.coaching.serializers import PackageSerializer

from .models import Workspace
from .public_serializers import PublicCoachSerializer, PublicWorkspaceSerializer


class PublicCoachView(APIView):
    """Return a public coach page for an active workspace slug."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, slug):
        """Return public workspace branding, owner profile, and active packages."""
        try:
            workspace = Workspace.objects.get(slug=slug, status=Workspace.Status.ACTIVE)
        except Workspace.DoesNotExist:
            raise exceptions.NotFound() from None

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
