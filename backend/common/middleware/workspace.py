"""Workspace resolution helpers for slug-scoped API views."""

from collections.abc import Collection
from dataclasses import dataclass

from rest_framework.exceptions import NotFound, PermissionDenied

from apps.accounts.models import Membership
from apps.workspaces.models import Workspace


@dataclass(frozen=True)
class WorkspaceContext:
    """The active workspace and the caller's membership within it."""

    workspace: Workspace
    membership: Membership


def resolve_workspace_context(
    user,
    slug: str,
    *,
    allowed_roles: Collection[str] | None = None,
) -> WorkspaceContext:
    """Resolve a caller's active workspace context from a URL slug.

    All resolution failures that could reveal workspace existence intentionally
    raise the same ``NotFound`` response.
    """
    workspace = Workspace.objects.filter(
        slug=slug,
        status=Workspace.Status.ACTIVE,
    ).first()
    if workspace is None or not getattr(user, "is_authenticated", False):
        raise NotFound()

    membership = (
        Membership.objects.select_related("workspace")
        .filter(
            user=user,
            workspace=workspace,
            status=Membership.Status.ACTIVE,
        )
        .first()
    )
    if membership is None:
        raise NotFound()

    if allowed_roles is not None and membership.role not in allowed_roles:
        raise PermissionDenied()

    return WorkspaceContext(workspace=workspace, membership=membership)
