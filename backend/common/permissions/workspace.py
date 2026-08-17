"""DRF permissions for workspace-slug-scoped views."""

from rest_framework.permissions import BasePermission

from apps.accounts.models import Membership
from common.middleware import resolve_workspace_context


class WorkspacePermission(BasePermission):
    """Resolve and attach the workspace context required by a view."""

    workspace_slug_kwarg = "workspace_slug"
    allowed_roles: tuple[str, ...] | None = None

    def has_permission(self, request, view):
        slug = view.kwargs[self.workspace_slug_kwarg]
        request.workspace_context = resolve_workspace_context(
            request.user,
            slug,
            allowed_roles=self.allowed_roles,
        )
        return True


class CoachWorkspacePermission(WorkspacePermission):
    """Require an active OWNER or COACH membership."""

    allowed_roles = (Membership.Role.OWNER, Membership.Role.COACH)


class ClientWorkspacePermission(WorkspacePermission):
    """Require an active CLIENT membership."""

    allowed_roles = (Membership.Role.CLIENT,)
