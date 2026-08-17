"""Shared DRF permission classes."""

from .workspace import (
    ClientWorkspacePermission,
    CoachWorkspacePermission,
    WorkspacePermission,
)

__all__ = [
    "ClientWorkspacePermission",
    "CoachWorkspacePermission",
    "WorkspacePermission",
]
