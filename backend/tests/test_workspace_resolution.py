"""Tests for server-side workspace resolution and permission guards (Story 3.3).

Validates:
- Successful workspace resolution by URL slug for OWNER, COACH, and CLIENT roles
- Strict resolution by slug ensuring tenant boundaries across multiple workspaces
- The 404 NotFound family: non-existent slug, missing membership, inactive membership,
  and suspended workspace
- Anti-enumeration guarantee: mutual indistinguishability across all four 404 cases
- Cross-tenant isolation: Coach-A cannot reach Workspace-B
- Stateless resolution: independent context resolution for multi-workspace users
- Role-based permissions: Coach areas (OWNER, COACH) and Client areas (CLIENT)
- 403 PermissionDenied distinguishability from 404 NotFound for authorized tenants
  with wrong role
- Permission class guards against inactive memberships, suspended workspaces, and non-members
"""

import importlib
import inspect
import uuid

from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import BasePermission
from rest_framework.test import APIRequestFactory


def get_workspace_resolver():
    """Dynamically locates the workspace resolution callable from common modules.

    Attempts canonical import locations and falls back to scanning common modules
    for callables whose name contains 'resolve' and 'workspace'.
    """
    candidate_modules = [
        "common.middleware.workspace",
        "common.middleware",
        "common.workspace",
        "common.permissions.workspace",
        "common.permissions",
    ]

    for mod_name in candidate_modules:
        try:
            mod = importlib.import_module(mod_name)
        except ImportError:
            continue

        if hasattr(mod, "resolve_workspace_context"):
            return mod.resolve_workspace_context

        for attr_name in dir(mod):
            if attr_name.startswith("_"):
                continue
            lower_name = attr_name.lower()
            if "resolve" in lower_name and "workspace" in lower_name:
                attr = getattr(mod, attr_name)
                if callable(attr):
                    return attr

    return None


def get_workspace_permission_classes():
    """Dynamically discovers and classifies coach and client permission classes.

    Scans common.permissions for BasePermission subclasses and classifies them
    into coach-area permission (allowing OWNER, COACH) and client-area permission (allowing CLIENT).
    """
    candidate_modules = [
        "common.permissions.workspace",
        "common.permissions",
    ]
    discovered = []

    for mod_name in candidate_modules:
        try:
            mod = importlib.import_module(mod_name)
        except ImportError:
            continue

        for attr_name in dir(mod):
            if attr_name.startswith("_"):
                continue
            attr = getattr(mod, attr_name)
            if (
                inspect.isclass(attr)
                and issubclass(attr, BasePermission)
                and attr is not BasePermission
                and attr not in discovered
            ):
                discovered.append(attr)

    coach_perm = None
    client_perm = None

    for cls in discovered:
        name_lower = cls.__name__.lower()
        doc_lower = (cls.__doc__ or "").lower()
        allowed_roles = getattr(cls, "allowed_roles", None) or getattr(cls, "roles", None)

        if allowed_roles:
            role_set = set(allowed_roles)
            if "COACH" in role_set or "OWNER" in role_set:
                coach_perm = cls
            elif "CLIENT" in role_set:
                client_perm = cls
            continue

        if "coach" in name_lower or "owner" in name_lower:
            coach_perm = cls
        elif "client" in name_lower:
            client_perm = cls
        elif "coach" in doc_lower or "owner" in doc_lower:
            coach_perm = cls
        elif "client" in doc_lower:
            client_perm = cls

    return coach_perm, client_perm


def invoke_resolver(resolver, user, slug):
    """Invokes the resolver callable handling keyword or positional signatures."""
    sig = inspect.signature(resolver)
    param_names = list(sig.parameters.keys())

    if "user" in param_names and "slug" in param_names:
        return resolver(user=user, slug=slug)
    if "user" in param_names and "workspace_slug" in param_names:
        return resolver(user=user, workspace_slug=slug)
    if "slug" in param_names and "user" in param_names:
        return resolver(slug=slug, user=user)
    if "workspace_slug" in param_names and "user" in param_names:
        return resolver(workspace_slug=slug, user=user)

    try:
        return resolver(user, slug)
    except TypeError:
        return resolver(slug, user)


def extract_workspace(context):
    """Extracts the Workspace instance from a resolved workspace context."""
    if hasattr(context, "workspace"):
        return context.workspace
    if isinstance(context, dict) and "workspace" in context:
        return context["workspace"]
    return None


def extract_membership(context):
    """Extracts the Membership instance from a resolved workspace context."""
    if hasattr(context, "membership"):
        return context.membership
    if isinstance(context, dict) and "membership" in context:
        return context["membership"]
    return None


class FakeWorkspaceView:
    """Lightweight view mock carrying workspace routing kwargs."""

    def __init__(self, slug):
        self.kwargs = {"workspace_slug": slug, "slug": slug}


class BaseWorkspaceResolutionTestCase(TestCase):
    """Base test case providing model resolution, entity factories, and execution helpers."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.membership_model = apps.get_model("accounts", "Membership")
        cls.workspace_model = apps.get_model("workspaces", "Workspace")
        cls.user_model = get_user_model()
        # staticmethod(): assigning a plain function to a class attribute would turn it
        # into a bound method, silently passing the TestCase instance as the first argument.
        cls.resolver = staticmethod(get_workspace_resolver())
        cls.coach_permission_class, cls.client_permission_class = get_workspace_permission_classes()
        cls.request_factory = APIRequestFactory()

    def _create_user(self, email=None, password="SecurePassword123!", **kwargs):
        """Helper to create a User instance with a unique default email."""
        if email is None:
            email = f"user-{uuid.uuid4().hex[:8]}@example.com"
        return self.user_model.objects.create_user(email=email, password=password, **kwargs)

    def _create_workspace(self, name=None, slug=None, status="ACTIVE", **kwargs):
        """Helper to create a Workspace instance with default required attributes."""
        unique_id = uuid.uuid4().hex[:8]
        if name is None:
            name = f"Workspace {unique_id}"
        if slug is None:
            slug = f"workspace-{unique_id}"
        defaults = {
            "name": name,
            "slug": slug,
            "currency": "USD",
            "timezone": "UTC",
            "status": status,
        }
        defaults.update(kwargs)
        return self.workspace_model.objects.create(**defaults)

    def _create_membership(
        self, user=None, workspace=None, role="COACH", status="ACTIVE", **kwargs
    ):
        """Helper to create a Membership instance with explicit role and status."""
        if user is None:
            user = self._create_user()
        if workspace is None:
            workspace = self._create_workspace()
        defaults = {
            "user": user,
            "workspace": workspace,
            "role": role,
            "status": status,
        }
        defaults.update(kwargs)
        return self.membership_model.objects.create(**defaults)

    def _resolve(self, user, slug):
        """Resolves workspace context using the dynamically discovered resolver."""
        if self.resolver is None:
            self.fail(
                "Workspace resolution callable could not be located in common modules "
                "(expected 'resolve_workspace_context' or equivalent callable)."
            )
        return invoke_resolver(self.resolver, user, slug)

    def _build_request(self, user, slug):
        """Creates a mock DRF request authenticated with user and configured parser context."""
        request = self.request_factory.get(f"/{slug}/mock-endpoint/")
        request.user = user
        request.parser_context = {"kwargs": {"workspace_slug": slug, "slug": slug}}
        return request

    def _build_view(self, slug):
        """Creates a mock DRF view carrying URL slug kwargs."""
        return FakeWorkspaceView(slug)

    def _check_permission(self, perm_class, request, view):
        """Evaluates has_permission on the permission class instance.

        Returns (allowed: bool, exception: Exception | None).
        Propagates NotFound directly to allow 404 assertions.
        """
        if perm_class is None:
            self.fail("Permission class could not be discovered in common.permissions for check.")
        perm = perm_class()
        try:
            allowed = perm.has_permission(request, view)
            if allowed:
                return True, None
            return False, PermissionDenied()
        except PermissionDenied as exc:
            return False, exc

    def _assert_context_on_request(self, request, expected_workspace, expected_membership):
        """Asserts resolved Workspace and Membership are attached and reachable on request."""
        ws = getattr(request, "workspace", None)
        mem = getattr(request, "membership", None)
        ctx = getattr(request, "workspace_context", None)

        if ws is None and ctx is not None:
            ws = extract_workspace(ctx)
        if mem is None and ctx is not None:
            mem = extract_membership(ctx)

        self.assertIsNotNone(
            ws,
            "Permission class must leave resolved Workspace reachable on request.",
        )
        self.assertEqual(
            ws,
            expected_workspace,
            "Reachable workspace on request must match expected Workspace instance.",
        )
        self.assertIsNotNone(
            mem,
            "Permission class must leave resolved Membership reachable on request.",
        )
        self.assertEqual(
            mem,
            expected_membership,
            "Reachable membership on request must match expected Membership instance.",
        )


class WorkspaceResolutionSuccessTests(BaseWorkspaceResolutionTestCase):
    """Verifies successful workspace resolution for valid memberships and slug specificity."""

    def test_resolve_workspace_context_for_owner_returns_workspace_and_membership(self):
        """Asserts OWNER with an active Membership resolves to correct workspace and membership."""
        owner = self._create_user(email="owner.success@example.com")
        workspace = self._create_workspace(slug="owner-active-ws", status="ACTIVE")
        membership = self._create_membership(
            user=owner,
            workspace=workspace,
            role="OWNER",
            status="ACTIVE",
        )

        context = self._resolve(owner, workspace.slug)

        self.assertIsNotNone(context, "Resolved workspace context must not be None.")
        self.assertEqual(
            extract_workspace(context),
            workspace,
            "Resolved context must expose the correct Workspace instance.",
        )
        self.assertEqual(
            extract_membership(context),
            membership,
            "Resolved context must expose the caller's active Membership instance.",
        )
        self.assertEqual(
            extract_membership(context).role,
            "OWNER",
            "Resolved membership role must be 'OWNER'.",
        )

    def test_resolve_workspace_context_for_coach_returns_workspace_and_membership(self):
        """Asserts COACH with an active Membership resolves to correct workspace and membership."""
        coach = self._create_user(email="coach.success@example.com")
        workspace = self._create_workspace(slug="coach-active-ws", status="ACTIVE")
        membership = self._create_membership(
            user=coach,
            workspace=workspace,
            role="COACH",
            status="ACTIVE",
        )

        context = self._resolve(coach, workspace.slug)

        self.assertIsNotNone(context, "Resolved workspace context must not be None.")
        self.assertEqual(
            extract_workspace(context),
            workspace,
            "Resolved context must expose the correct Workspace instance.",
        )
        self.assertEqual(
            extract_membership(context),
            membership,
            "Resolved context must expose the caller's active Membership instance.",
        )
        self.assertEqual(
            extract_membership(context).role,
            "COACH",
            "Resolved membership role must be 'COACH'.",
        )

    def test_resolve_workspace_context_for_client_returns_workspace_and_membership(self):
        """Asserts CLIENT with an active Membership resolves to correct workspace and membership."""
        client = self._create_user(email="client.success@example.com")
        workspace = self._create_workspace(slug="client-active-ws", status="ACTIVE")
        membership = self._create_membership(
            user=client,
            workspace=workspace,
            role="CLIENT",
            status="ACTIVE",
        )

        context = self._resolve(client, workspace.slug)

        self.assertIsNotNone(context, "Resolved workspace context must not be None.")
        self.assertEqual(
            extract_workspace(context),
            workspace,
            "Resolved context must expose the correct Workspace instance.",
        )
        self.assertEqual(
            extract_membership(context),
            membership,
            "Resolved context must expose the caller's active Membership instance.",
        )
        self.assertEqual(
            extract_membership(context).role,
            "CLIENT",
            "Resolved membership role must be 'CLIENT'.",
        )

    def test_resolution_is_strictly_by_slug_and_matches_requested_workspace_only(self):
        """Asserts resolution is strictly by slug and returns only the requested workspace.

        When a user owns two distinct workspaces, passing slug A returns workspace A
        and never workspace B; passing slug B returns workspace B and never workspace A.
        """
        user = self._create_user(email="dual.owner@example.com")
        workspace_a = self._create_workspace(name="Gym Alpha", slug="gym-alpha-slug")
        workspace_b = self._create_workspace(name="Gym Beta", slug="gym-beta-slug")

        membership_a = self._create_membership(
            user=user,
            workspace=workspace_a,
            role="OWNER",
            status="ACTIVE",
        )
        membership_b = self._create_membership(
            user=user,
            workspace=workspace_b,
            role="OWNER",
            status="ACTIVE",
        )

        context_a = self._resolve(user, "gym-alpha-slug")
        self.assertEqual(extract_workspace(context_a), workspace_a)
        self.assertEqual(extract_membership(context_a), membership_a)
        self.assertNotEqual(extract_workspace(context_a), workspace_b)

        context_b = self._resolve(user, "gym-beta-slug")
        self.assertEqual(extract_workspace(context_b), workspace_b)
        self.assertEqual(extract_membership(context_b), membership_b)
        self.assertNotEqual(extract_workspace(context_b), workspace_a)


class WorkspaceResolutionNotFoundFamilyTests(BaseWorkspaceResolutionTestCase):
    """Verifies the four 404 NotFound cases and their strict mutual indistinguishability."""

    def test_resolve_non_existent_slug_raises_not_found(self):
        """Asserts resolving a non-existent workspace slug raises DRF NotFound (HTTP 404)."""
        user = self._create_user(email="user.missing.slug@example.com")

        with self.assertRaises(NotFound) as cm:
            self._resolve(user, "non-existent-workspace-slug-999")

        self.assertEqual(cm.exception.status_code, 404)

    def test_resolve_user_with_no_membership_in_existing_workspace_raises_not_found(self):
        """Asserts an authenticated user with no Membership in a workspace raises NotFound (404)."""
        user_without_membership = self._create_user(email="no.membership@example.com")
        workspace = self._create_workspace(slug="existing-target-ws", status="ACTIVE")

        with self.assertRaises(NotFound) as cm:
            self._resolve(user_without_membership, workspace.slug)

        self.assertEqual(cm.exception.status_code, 404)

    def test_resolve_user_with_inactive_membership_raises_not_found(self):
        """Central guard: asserts user whose Membership has status='INACTIVE' raises NotFound (404).

        Guards that INACTIVE memberships never grant access or reveal workspace existence.
        """
        inactive_user = self._create_user(email="inactive.member@example.com")
        workspace = self._create_workspace(slug="inactive-member-ws", status="ACTIVE")
        self._create_membership(
            user=inactive_user,
            workspace=workspace,
            role="COACH",
            status="INACTIVE",
        )

        with self.assertRaises(NotFound) as cm:
            self._resolve(inactive_user, workspace.slug)

        self.assertEqual(cm.exception.status_code, 404)

    def test_resolve_suspended_workspace_with_active_membership_raises_not_found(self):
        """Asserts a SUSPENDED workspace raises NotFound even with an active membership."""
        user = self._create_user(email="suspended.ws.member@example.com")
        suspended_workspace = self._create_workspace(
            slug="suspended-workspace-ws",
            status="SUSPENDED",
        )
        self._create_membership(
            user=user,
            workspace=suspended_workspace,
            role="OWNER",
            status="ACTIVE",
        )

        with self.assertRaises(NotFound) as cm:
            self._resolve(user, suspended_workspace.slug)

        self.assertEqual(cm.exception.status_code, 404)

    def test_all_four_not_found_cases_are_mutually_indistinguishable(self):
        """Anti-enumeration guarantee: asserts all four 404 cases produce identical exceptions.

        Captures real exceptions from all four failure scenarios and verifies their
        exception type, status_code, error code, and detail message are pairwise equal.
        """
        user_non_existent = self._create_user(email="enum.user1@example.com")

        user_no_membership = self._create_user(email="enum.user2@example.com")
        ws_no_membership = self._create_workspace(slug="enum-no-mem-ws", status="ACTIVE")

        user_inactive = self._create_user(email="enum.user3@example.com")
        ws_inactive = self._create_workspace(slug="enum-inactive-ws", status="ACTIVE")
        self._create_membership(
            user=user_inactive,
            workspace=ws_inactive,
            role="COACH",
            status="INACTIVE",
        )

        user_suspended = self._create_user(email="enum.user4@example.com")
        ws_suspended = self._create_workspace(slug="enum-suspended-ws", status="SUSPENDED")
        self._create_membership(
            user=user_suspended,
            workspace=ws_suspended,
            role="OWNER",
            status="ACTIVE",
        )

        # 1. Non-existent slug
        with self.assertRaises(NotFound) as cm1:
            self._resolve(user_non_existent, "non-existent-enumeration-slug")
        exc_non_existent = cm1.exception

        # 2. No membership in existing workspace
        with self.assertRaises(NotFound) as cm2:
            self._resolve(user_no_membership, ws_no_membership.slug)
        exc_no_membership = cm2.exception

        # 3. Inactive membership in active workspace
        with self.assertRaises(NotFound) as cm3:
            self._resolve(user_inactive, ws_inactive.slug)
        exc_inactive_membership = cm3.exception

        # 4. Active membership in suspended workspace
        with self.assertRaises(NotFound) as cm4:
            self._resolve(user_suspended, ws_suspended.slug)
        exc_suspended_workspace = cm4.exception

        exceptions = [
            ("non-existent slug", exc_non_existent),
            ("no membership", exc_no_membership),
            ("inactive membership", exc_inactive_membership),
            ("suspended workspace", exc_suspended_workspace),
        ]

        # Pairwise comparison across all four captured exceptions
        for i, (name_a, exc_a) in enumerate(exceptions):
            for j, (name_b, exc_b) in enumerate(exceptions):
                if i < j:
                    with self.subTest(pair=f"{name_a} vs {name_b}"):
                        self.assertEqual(
                            type(exc_a),
                            type(exc_b),
                            f"Exception types must match between '{name_a}' and '{name_b}'.",
                        )
                        self.assertEqual(
                            exc_a.status_code,
                            exc_b.status_code,
                            f"HTTP status codes must match between '{name_a}' and '{name_b}'.",
                        )
                        code_a = getattr(exc_a, "default_code", None) or getattr(
                            getattr(exc_a, "detail", None), "code", None
                        )
                        code_b = getattr(exc_b, "default_code", None) or getattr(
                            getattr(exc_b, "detail", None), "code", None
                        )
                        self.assertEqual(
                            code_a,
                            code_b,
                            f"Error codes must match between '{name_a}' and '{name_b}'.",
                        )
                        self.assertEqual(
                            str(exc_a.detail),
                            str(exc_b.detail),
                            f"Detail messages must match between '{name_a}' and '{name_b}'.",
                        )


class WorkspaceCrossTenantIsolationTests(BaseWorkspaceResolutionTestCase):
    """Verifies cross-tenant boundaries and stateless per-slug context resolution."""

    def test_owner_of_workspace_a_cannot_resolve_workspace_b(self):
        """Coach-A-cannot-reach-Workspace-B: owner of workspace A gets 404 for workspace B."""
        coach_a = self._create_user(email="coach.tenant.a@example.com")
        coach_b = self._create_user(email="coach.tenant.b@example.com")

        workspace_a = self._create_workspace(slug="tenant-a-gym", status="ACTIVE")
        workspace_b = self._create_workspace(slug="tenant-b-gym", status="ACTIVE")

        self._create_membership(
            user=coach_a,
            workspace=workspace_a,
            role="OWNER",
            status="ACTIVE",
        )
        self._create_membership(
            user=coach_b,
            workspace=workspace_b,
            role="OWNER",
            status="ACTIVE",
        )

        with self.assertRaises(NotFound) as cm:
            self._resolve(coach_a, workspace_b.slug)

        self.assertEqual(cm.exception.status_code, 404)

    def test_multi_workspace_user_resolves_each_independently_without_global_state(self):
        """Asserts user holding memberships in multiple workspaces resolves each independently.

        Proves there is no global 'current workspace' state and each call resolves
        from the provided slug.
        """
        multi_user = self._create_user(email="multi.tenant.member@example.com")
        workspace_coach = self._create_workspace(slug="multi-coach-ws", status="ACTIVE")
        workspace_client = self._create_workspace(slug="multi-client-ws", status="ACTIVE")

        membership_coach = self._create_membership(
            user=multi_user,
            workspace=workspace_coach,
            role="COACH",
            status="ACTIVE",
        )
        membership_client = self._create_membership(
            user=multi_user,
            workspace=workspace_client,
            role="CLIENT",
            status="ACTIVE",
        )

        # Resolve first workspace
        ctx_1 = self._resolve(multi_user, "multi-coach-ws")
        self.assertEqual(extract_workspace(ctx_1), workspace_coach)
        self.assertEqual(extract_membership(ctx_1), membership_coach)
        self.assertEqual(extract_membership(ctx_1).role, "COACH")

        # Resolve second workspace
        ctx_2 = self._resolve(multi_user, "multi-client-ws")
        self.assertEqual(extract_workspace(ctx_2), workspace_client)
        self.assertEqual(extract_membership(ctx_2), membership_client)
        self.assertEqual(extract_membership(ctx_2).role, "CLIENT")

        # Re-resolve first workspace to ensure no global state contamination
        ctx_1_again = self._resolve(multi_user, "multi-coach-ws")
        self.assertEqual(extract_workspace(ctx_1_again), workspace_coach)
        self.assertEqual(extract_membership(ctx_1_again), membership_coach)
        self.assertEqual(extract_membership(ctx_1_again).role, "COACH")


class WorkspaceRolePermissionTests(BaseWorkspaceResolutionTestCase):
    """Verifies role-based access control for Coach and Client areas and the 403 case."""

    def test_coach_permission_grants_access_to_workspace_owner(self):
        """Asserts Coach permission class grants access to an active OWNER and attaches context."""
        owner = self._create_user(email="coach.area.owner@example.com")
        workspace = self._create_workspace(slug="coach-area-owner-ws", status="ACTIVE")
        membership = self._create_membership(
            user=owner,
            workspace=workspace,
            role="OWNER",
            status="ACTIVE",
        )

        request = self._build_request(owner, workspace.slug)
        view = self._build_view(workspace.slug)

        allowed, _ = self._check_permission(self.coach_permission_class, request, view)

        self.assertTrue(allowed, "Coach permission class must grant access to active OWNER.")
        self._assert_context_on_request(request, workspace, membership)

    def test_coach_permission_grants_access_to_workspace_coach(self):
        """Asserts Coach permission class grants access to an active COACH and attaches context."""
        coach = self._create_user(email="coach.area.coach@example.com")
        workspace = self._create_workspace(slug="coach-area-coach-ws", status="ACTIVE")
        membership = self._create_membership(
            user=coach,
            workspace=workspace,
            role="COACH",
            status="ACTIVE",
        )

        request = self._build_request(coach, workspace.slug)
        view = self._build_view(workspace.slug)

        allowed, _ = self._check_permission(self.coach_permission_class, request, view)

        self.assertTrue(allowed, "Coach permission class must grant access to active COACH.")
        self._assert_context_on_request(request, workspace, membership)

    def test_coach_permission_denies_workspace_client_with_permission_denied(self):
        """Asserts Coach permission class denies active CLIENT with PermissionDenied (HTTP 403)."""
        client = self._create_user(email="client.on.coach.area@example.com")
        workspace = self._create_workspace(slug="coach-area-denies-client", status="ACTIVE")
        self._create_membership(
            user=client,
            workspace=workspace,
            role="CLIENT",
            status="ACTIVE",
        )

        request = self._build_request(client, workspace.slug)
        view = self._build_view(workspace.slug)

        allowed, exc = self._check_permission(self.coach_permission_class, request, view)

        self.assertFalse(allowed, "Coach permission class must deny access to CLIENT role.")
        self.assertIsNotNone(exc, "Permission denial must produce an exception with status 403.")
        self.assertEqual(exc.status_code, 403)

    def test_client_permission_grants_access_to_workspace_client(self):
        """Asserts the Client permission grants an active CLIENT and attaches context."""
        client = self._create_user(email="client.area.member@example.com")
        workspace = self._create_workspace(slug="client-area-client-ws", status="ACTIVE")
        membership = self._create_membership(
            user=client,
            workspace=workspace,
            role="CLIENT",
            status="ACTIVE",
        )

        request = self._build_request(client, workspace.slug)
        view = self._build_view(workspace.slug)

        allowed, _ = self._check_permission(self.client_permission_class, request, view)

        self.assertTrue(allowed, "Client permission class must grant access to active CLIENT.")
        self._assert_context_on_request(request, workspace, membership)

    def test_client_permission_denies_workspace_owner_with_permission_denied(self):
        """Asserts Client permission class denies active OWNER with PermissionDenied (HTTP 403)."""
        owner = self._create_user(email="owner.on.client.area@example.com")
        workspace = self._create_workspace(slug="client-area-denies-owner", status="ACTIVE")
        self._create_membership(
            user=owner,
            workspace=workspace,
            role="OWNER",
            status="ACTIVE",
        )

        request = self._build_request(owner, workspace.slug)
        view = self._build_view(workspace.slug)

        allowed, exc = self._check_permission(self.client_permission_class, request, view)

        self.assertFalse(allowed, "Client permission class must deny access to OWNER role.")
        self.assertIsNotNone(exc, "Permission denial must produce an exception with status 403.")
        self.assertEqual(exc.status_code, 403)

    def test_client_permission_denies_workspace_coach_with_permission_denied(self):
        """Asserts Client permission class denies active COACH with PermissionDenied (HTTP 403)."""
        coach = self._create_user(email="coach.on.client.area@example.com")
        workspace = self._create_workspace(slug="client-area-denies-coach", status="ACTIVE")
        self._create_membership(
            user=coach,
            workspace=workspace,
            role="COACH",
            status="ACTIVE",
        )

        request = self._build_request(coach, workspace.slug)
        view = self._build_view(workspace.slug)

        allowed, exc = self._check_permission(self.client_permission_class, request, view)

        self.assertFalse(allowed, "Client permission class must deny access to COACH role.")
        self.assertIsNotNone(exc, "Permission denial must produce an exception with status 403.")
        self.assertEqual(exc.status_code, 403)

    def test_permission_denied_is_distinguishable_from_not_found_family(self):
        """Asserts PermissionDenied (403) is distinguishable from the 404 NotFound family.

        Leaking existence via HTTP 403 is acceptable here because the authenticated
        caller already holds an active Membership in this workspace and thus already
        knows it exists. Only their role is unauthorized for the requested area.
        """
        # Scenario 1: Active CLIENT user on Coach area -> 403 PermissionDenied
        client_user = self._create_user(email="distinguish.client@example.com")
        workspace_active = self._create_workspace(slug="distinguish-ws", status="ACTIVE")
        self._create_membership(
            user=client_user,
            workspace=workspace_active,
            role="CLIENT",
            status="ACTIVE",
        )

        request_403 = self._build_request(client_user, workspace_active.slug)
        view_403 = self._build_view(workspace_active.slug)
        allowed_403, exc_403 = self._check_permission(
            self.coach_permission_class, request_403, view_403
        )

        # Scenario 2: Non-member user on Coach area -> 404 NotFound
        non_member_user = self._create_user(email="distinguish.nonmember@example.com")
        request_404 = self._build_request(non_member_user, workspace_active.slug)
        view_404 = self._build_view(workspace_active.slug)

        with self.assertRaises(NotFound) as cm_404:
            perm = self.coach_permission_class()
            perm.has_permission(request_404, view_404)
        exc_404 = cm_404.exception

        self.assertFalse(allowed_403)
        self.assertEqual(exc_403.status_code, 403)
        self.assertEqual(exc_404.status_code, 404)
        self.assertNotEqual(
            exc_403.status_code,
            exc_404.status_code,
            "PermissionDenied (403) must be distinguishable from NotFound (404).",
        )


class WorkspacePermissionGuardTests(BaseWorkspaceResolutionTestCase):
    """Verifies permission class guards against inactive memberships, suspended workspaces, etc."""

    def test_coach_permission_raises_not_found_for_inactive_coach_membership(self):
        """Asserts Coach permission class raises NotFound (404) when Membership is INACTIVE."""
        inactive_coach = self._create_user(email="inactive.coach.perm@example.com")
        workspace = self._create_workspace(slug="inactive-coach-perm-ws", status="ACTIVE")
        self._create_membership(
            user=inactive_coach,
            workspace=workspace,
            role="COACH",
            status="INACTIVE",
        )

        request = self._build_request(inactive_coach, workspace.slug)
        view = self._build_view(workspace.slug)

        with self.assertRaises(NotFound) as cm:
            perm = self.coach_permission_class()
            perm.has_permission(request, view)

        self.assertEqual(cm.exception.status_code, 404)

    def test_client_permission_raises_not_found_for_inactive_client_membership(self):
        """Asserts Client permission class raises NotFound (404) when Membership is INACTIVE."""
        inactive_client = self._create_user(email="inactive.client.perm@example.com")
        workspace = self._create_workspace(slug="inactive-client-perm-ws", status="ACTIVE")
        self._create_membership(
            user=inactive_client,
            workspace=workspace,
            role="CLIENT",
            status="INACTIVE",
        )

        request = self._build_request(inactive_client, workspace.slug)
        view = self._build_view(workspace.slug)

        with self.assertRaises(NotFound) as cm:
            perm = self.client_permission_class()
            perm.has_permission(request, view)

        self.assertEqual(cm.exception.status_code, 404)

    def test_coach_permission_raises_not_found_for_suspended_workspace(self):
        """Asserts Coach permission class raises NotFound (404) for a SUSPENDED workspace."""
        owner = self._create_user(email="suspended.coach.perm@example.com")
        suspended_ws = self._create_workspace(slug="suspended-coach-perm-ws", status="SUSPENDED")
        self._create_membership(
            user=owner,
            workspace=suspended_ws,
            role="OWNER",
            status="ACTIVE",
        )

        request = self._build_request(owner, suspended_ws.slug)
        view = self._build_view(suspended_ws.slug)

        with self.assertRaises(NotFound) as cm:
            perm = self.coach_permission_class()
            perm.has_permission(request, view)

        self.assertEqual(cm.exception.status_code, 404)

    def test_coach_permission_raises_not_found_for_non_member_user(self):
        """Asserts Coach permission class raises NotFound (404) for authenticated non-member."""
        non_member = self._create_user(email="nonmember.coach.perm@example.com")
        workspace = self._create_workspace(slug="nonmember-coach-perm-ws", status="ACTIVE")

        request = self._build_request(non_member, workspace.slug)
        view = self._build_view(workspace.slug)

        with self.assertRaises(NotFound) as cm:
            perm = self.coach_permission_class()
            perm.has_permission(request, view)

        self.assertEqual(cm.exception.status_code, 404)

    def test_coach_permission_raises_not_found_for_non_existent_slug(self):
        """Asserts Coach permission class raises NotFound (404) for a non-existent slug."""
        user = self._create_user(email="nonexistent.slug.perm@example.com")
        non_existent_slug = "non-existent-perm-slug-000"

        request = self._build_request(user, non_existent_slug)
        view = self._build_view(non_existent_slug)

        with self.assertRaises(NotFound) as cm:
            perm = self.coach_permission_class()
            perm.has_permission(request, view)

        self.assertEqual(cm.exception.status_code, 404)
