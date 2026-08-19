"""Views for workspace API endpoints."""

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts.models import Membership
from apps.audit.models import AuditLog

from .models import PaymentMethod, Workspace
from .serializers import (
    PaymentMethodSerializer,
    WorkspaceBrandingSerializer,
    WorkspaceBrandingUpdateSerializer,
    WorkspaceCreateSerializer,
    WorkspaceLogoUploadSerializer,
    WorkspaceSerializer,
    WorkspaceSettingsSerializer,
)


def resolve_active_coach_membership(user):
    """Resolve this caller's active Owner or Coach membership without a slug."""
    membership = (
        Membership.objects.select_related("workspace")
        .filter(
            user=user,
            status=Membership.Status.ACTIVE,
            workspace__status=Workspace.Status.ACTIVE,
            role__in=(Membership.Role.OWNER, Membership.Role.COACH),
        )
        .first()
    )
    if membership is None:
        raise exceptions.NotFound()
    return membership


class WorkspaceConflict(exceptions.APIException):
    """Return the documented conflict response for a reserved workspace slug."""

    status_code = status.HTTP_409_CONFLICT
    default_code = "CONFLICT"
    default_detail = "A workspace with this slug already exists."


class WorkspaceCreateView(APIView):
    """Create a workspace and its initial active Owner membership."""

    def get(self, request):
        """Return the active workspace available to the authenticated Coach."""
        membership = resolve_active_coach_membership(request.user)
        return Response(WorkspaceSerializer(membership.workspace).data)

    def patch(self, request):
        """Partially update settings for the caller's active owned workspace."""
        membership = resolve_active_coach_membership(request.user)
        if membership.role != Membership.Role.OWNER:
            raise exceptions.PermissionDenied()

        serializer = WorkspaceSettingsSerializer(
            membership.workspace,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        workspace = serializer.save()
        return Response(WorkspaceSerializer(workspace).data)

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


class WorkspaceBrandingView(APIView):
    """Update branding for the caller's active owned workspace."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "workspace_logo_upload"

    def patch(self, request):
        membership = resolve_active_coach_membership(request.user)
        if membership.role != Membership.Role.OWNER:
            raise exceptions.PermissionDenied()

        serializer = WorkspaceBrandingUpdateSerializer(
            membership.workspace,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        workspace = serializer.save()
        return Response(WorkspaceBrandingSerializer(workspace).data)


class WorkspaceLogoUploadView(APIView):
    """Replace the logo for the caller's active owned workspace."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "workspace_logo_upload"

    def post(self, request):
        membership = resolve_active_coach_membership(request.user)
        if membership.role != Membership.Role.OWNER:
            raise exceptions.PermissionDenied()

        serializer = WorkspaceLogoUploadSerializer(
            membership.workspace,
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)
        workspace = serializer.save()
        return Response({"logo": workspace.logo.url})


class PaymentMethodView(APIView):
    """List and create payment methods for the caller's active workspace."""

    throttle_scope = "workspace_logo_upload"

    def get_throttles(self):
        if self.request.method == "POST":
            return [ScopedRateThrottle()]
        return []

    def get(self, request):
        membership = resolve_active_coach_membership(request.user)
        payment_methods = PaymentMethod.objects.for_workspace(membership.workspace).order_by(
            "-created_at"
        )
        return Response(PaymentMethodSerializer(payment_methods, many=True).data)

    def post(self, request):
        membership = resolve_active_coach_membership(request.user)
        serializer = PaymentMethodSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(workspace=membership.workspace)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class PaymentMethodDetailView(APIView):
    """Update or hard-delete one payment method within the active workspace."""

    throttle_scope = "workspace_logo_upload"

    def get_throttles(self):
        if self.request.method == "PATCH":
            return [ScopedRateThrottle()]
        return []

    @staticmethod
    def _payment_method(membership, payment_method_id):
        return get_object_or_404(
            PaymentMethod.objects.for_workspace(membership.workspace),
            pk=payment_method_id,
        )

    def patch(self, request, payment_method_id):
        membership = resolve_active_coach_membership(request.user)
        payment_method = self._payment_method(membership, payment_method_id)
        serializer = PaymentMethodSerializer(payment_method, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, payment_method_id):
        membership = resolve_active_coach_membership(request.user)
        payment_method = self._payment_method(membership, payment_method_id)
        payment_method.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
