"""Safe tenant-scoping primitives for workspace business models."""

from django.db import models

from apps.accounts.models import Membership
from apps.workspaces.models import Workspace
from common.middleware.workspace import WorkspaceContext


class TenantQuerySet(models.QuerySet):
    """QuerySet helpers that scope workspace records and fail closed."""

    def for_workspace(self, workspace):
        """Return rows for ``workspace``, or no rows for an invalid workspace."""
        if not isinstance(workspace, Workspace) or workspace.pk is None:
            return self.none()
        return self.filter(workspace_id=workspace.pk)

    def for_context(self, context):
        """Return rows available in a Story 3.3 workspace context."""
        if not isinstance(context, WorkspaceContext):
            return self.none()
        return self.for_workspace(context.workspace)

    def for_client(self, membership):
        """Return rows owned by an active Client membership, or no rows."""
        if (
            not isinstance(membership, Membership)
            or membership.pk is None
            or membership.workspace_id is None
            or membership.status != Membership.Status.ACTIVE
            or membership.role != Membership.Role.CLIENT
        ):
            return self.none()
        return self.filter(
            workspace_id=membership.workspace_id,
            client_id=membership.pk,
        )

    def unscoped(self):
        """Deliberately return an unfiltered queryset for system/admin use."""
        return self.model._base_manager.all()


class WorkspaceScopedModel(models.Model):
    """Abstract base model for records owned by one Workspace."""

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
    )

    objects = TenantQuerySet.as_manager()

    class Meta:
        abstract = True


def membership_can_own_workspace(membership, workspace) -> bool:
    """Whether an active membership belongs to ``workspace``."""
    workspace_id = _workspace_id(workspace)
    return bool(
        isinstance(membership, Membership)
        and membership.status == Membership.Status.ACTIVE
        and membership.workspace_id is not None
        and membership.workspace_id == workspace_id
    )


def client_membership_can_own_workspace(membership, workspace) -> bool:
    """Whether an active Client membership belongs to ``workspace``."""
    return bool(
        membership_can_own_workspace(membership, workspace)
        and membership.role == Membership.Role.CLIENT
    )


def coach_membership_can_own_workspace(membership, workspace) -> bool:
    """Whether an active Owner or Coach membership belongs to ``workspace``."""
    return bool(
        membership_can_own_workspace(membership, workspace)
        and membership.role in {Membership.Role.OWNER, Membership.Role.COACH}
    )


def _workspace_id(workspace):
    """Extract a workspace id from either a Workspace or scoped record."""
    if workspace is None:
        return None
    return getattr(workspace, "workspace_id", getattr(workspace, "pk", None))
