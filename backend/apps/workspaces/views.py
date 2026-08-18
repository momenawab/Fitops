"""Views for workspace API endpoints."""

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Membership
from apps.audit.models import AuditLog

from .models import Workspace
from .serializers import WorkspaceCreateSerializer, WorkspaceSerializer


class WorkspaceConflict(exceptions.APIException):
    """Return the documented conflict response for a reserved workspace slug."""

    status_code = status.HTTP_409_CONFLICT
    default_code = "CONFLICT"
    default_detail = "A workspace with this slug already exists."


class WorkspaceCreateView(APIView):
    """Create a workspace and its initial active Owner membership."""

    def post(self, request):
        serializer = WorkspaceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            user = get_user_model().objects.select_for_update().get(pk=request.user.pk)
            if Membership.objects.filter(user=user, role=Membership.Role.OWNER).exists():
                raise exceptions.PermissionDenied()

            try:
                with transaction.atomic():
                    workspace = Workspace.objects.create(**serializer.validated_data)
            except IntegrityError as exc:
                raise WorkspaceConflict() from exc

            Membership.objects.create(
                user=user,
                workspace=workspace,
                role=Membership.Role.OWNER,
                status=Membership.Status.ACTIVE,
            )
            AuditLog.objects.create(
                user=user,
                workspace=workspace,
                action="WORKSPACE_CREATED",
                target_type="Workspace",
                target_id=workspace.id,
                ip_address=request.META.get("REMOTE_ADDR"),
            )

        return Response(WorkspaceSerializer(workspace).data, status=status.HTTP_201_CREATED)
