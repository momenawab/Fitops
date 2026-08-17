"""Shared middleware-related infrastructure."""

from .workspace import WorkspaceContext, resolve_workspace_context

__all__ = ["WorkspaceContext", "resolve_workspace_context"]
