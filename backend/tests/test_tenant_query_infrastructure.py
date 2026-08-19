"""Tests for tenant query infrastructure, abstract scoping, and ownership predicates (Story 3.4).

Validates:
- WorkspaceScopedModel abstract model contract: abstract=True, workspace FK with CASCADE,
  non-null, and zero model pollution to workspaces or accounts apps
- TenantQuerySet.for_workspace: strict workspace isolation and fail-closed behavior on None
- TenantQuerySet.for_context: resolution matching for_workspace and fail-closed behavior on None
- TenantQuerySet.for_client: strict active CLIENT ownership scoping, fail-closed on None/INACTIVE/
  non-CLIENT roles, cross-tenant isolation for same user across multiple workspaces, and
  workspace boundary enforcement
- TenantQuerySet.unscoped: escape hatch returning unfiltered rows across all workspaces
- Object-ownership helper predicates: pure boolean return values, status/workspace/role checks,
  fail-closed on None/invalid inputs, and strict non-raising behavior
"""

import importlib
import inspect
import uuid

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import connection, models
from django.test import TestCase

# Attempt import of WorkspaceContext from Story 3.3 for context-based scoping tests
try:
    from common.middleware.workspace import WorkspaceContext
except ImportError:
    WorkspaceContext = None

CANDIDATE_MODULES = [
    "common.models",
    "common.models.workspace",
    "common.models.tenant",
    "common.models.scoping",
    "common.models.query",
    "common.models.queryset",
    "common.models.ownership",
    "common.models.predicates",
    "common.models.base",
    "common.ownership",
    "common.predicates",
    "common.scoping",
]


def get_workspace_scoped_model():
    """Dynamically locates the abstract WorkspaceScopedModel from common modules."""
    for mod_name in CANDIDATE_MODULES:
        try:
            mod = importlib.import_module(mod_name)
        except ImportError:
            continue

        if hasattr(mod, "WorkspaceScopedModel"):
            return mod.WorkspaceScopedModel

        for attr_name in dir(mod):
            if attr_name.startswith("_"):
                continue
            attr = getattr(mod, attr_name)
            if (
                inspect.isclass(attr)
                and issubclass(attr, models.Model)
                and getattr(attr._meta, "abstract", False)
                and any(field.name == "workspace" for field in attr._meta.fields)
            ):
                return attr

    return None


def get_tenant_queryset_class():
    """Dynamically locates the TenantQuerySet class from common modules."""
    for mod_name in CANDIDATE_MODULES:
        try:
            mod = importlib.import_module(mod_name)
        except ImportError:
            continue

        if hasattr(mod, "TenantQuerySet"):
            return mod.TenantQuerySet

        for attr_name in dir(mod):
            if attr_name.startswith("_"):
                continue
            attr = getattr(mod, attr_name)
            if (
                inspect.isclass(attr)
                and issubclass(attr, models.QuerySet)
                and hasattr(attr, "for_workspace")
            ):
                return attr

    # Fallback to inspecting WorkspaceScopedModel.objects
    scoped_model = get_workspace_scoped_model()
    if scoped_model is not None and hasattr(scoped_model, "objects"):
        mgr = scoped_model.objects
        qs_class = getattr(mgr, "_queryset_class", None)
        if qs_class is not None and issubclass(qs_class, models.QuerySet):
            return qs_class

    return None


def get_ownership_predicates():
    """Dynamically discovers and classifies ownership helper predicates.

    Returns a tuple: (client_predicate, coach_predicate, general_predicate)
    """
    discovered_callables = {}

    for mod_name in CANDIDATE_MODULES:
        try:
            mod = importlib.import_module(mod_name)
        except ImportError:
            continue

        for attr_name in dir(mod):
            if attr_name.startswith("_"):
                continue
            attr = getattr(mod, attr_name)
            if (
                callable(attr)
                and not inspect.isclass(attr)
                and attr not in discovered_callables.values()
            ):
                discovered_callables[attr_name] = attr

    client_pred = None
    coach_pred = None
    general_pred = None

    # Priority 1: Exact / well-known names
    for name, func in list(discovered_callables.items()):
        name_lower = name.lower()
        if name_lower in {
            "can_client_own",
            "can_client_own_record",
            "can_client_own_in_workspace",
            "is_client_owner",
            "client_can_own",
            "check_client_ownership",
            "validate_client_ownership",
            "is_client_member_of",
        }:
            client_pred = func
        elif name_lower in {
            "can_coach_own",
            "can_coach_or_owner_own",
            "can_owner_or_coach_own",
            "can_staff_own",
            "is_coach_or_owner",
            "coach_can_own",
            "check_coach_ownership",
            "validate_coach_ownership",
            "is_coach_member_of",
        }:
            coach_pred = func
        elif name_lower in {
            "can_own",
            "can_membership_own",
            "check_ownership",
            "validate_ownership",
            "is_member_of",
        }:
            general_pred = func

    # Priority 2: Heuristic matching by name and docstring
    if not client_pred or not coach_pred:
        for name, func in discovered_callables.items():
            name_lower = name.lower()
            doc_lower = (func.__doc__ or "").lower()
            combined = f"{name_lower} {doc_lower}"

            if (
                not client_pred
                and "client" in combined
                and any(
                    k in combined for k in ("own", "member", "valid", "check", "can", "predicate")
                )
            ):
                client_pred = func
            elif (
                not coach_pred
                and any(r in combined for r in ("coach", "owner", "staff"))
                and any(
                    k in combined for k in ("own", "member", "valid", "check", "can", "predicate")
                )
            ):
                coach_pred = func
            elif (
                not general_pred
                and any(k in combined for k in ("own", "member", "valid", "check", "can"))
                and "client" not in combined
                and "coach" not in combined
            ):
                general_pred = func

    return client_pred, coach_pred, general_pred


def invoke_ownership_predicate(predicate, membership, workspace):
    """Invokes an ownership predicate callable handling keyword or positional signatures."""
    if predicate is None:
        return False
    try:
        sig = inspect.signature(predicate)
        param_names = list(sig.parameters.keys())
    except ValueError, TypeError:
        param_names = []

    # Try keyword invocation if parameter names match
    if "membership" in param_names and "workspace" in param_names:
        return predicate(membership=membership, workspace=workspace)
    if "membership" in param_names and "workspace_id" in param_names:
        ws_id = getattr(workspace, "id", workspace) if workspace is not None else None
        return predicate(membership=membership, workspace_id=ws_id)
    if "member" in param_names and "workspace" in param_names:
        return predicate(member=membership, workspace=workspace)
    if "workspace" in param_names and "membership" in param_names:
        return predicate(workspace=workspace, membership=membership)

    # Positional invocation fallbacks
    try:
        return predicate(membership, workspace)
    except TypeError:
        try:
            return predicate(workspace, membership)
        except TypeError:
            ws_id = getattr(workspace, "id", workspace) if workspace is not None else None
            return predicate(membership, ws_id)


# Resolve abstract base dynamically
WorkspaceScopedBase = get_workspace_scoped_model()
if WorkspaceScopedBase is None:
    # Fallback to models.Model during import so module import succeeds;
    # tests and setUpClass will fail cleanly if base is genuinely missing.
    WorkspaceScopedBase = models.Model


class ConcreteWorkspaceScopedRecord(WorkspaceScopedBase):
    """Concrete throwaway model subclassing WorkspaceScopedModel for testing queries."""

    client = models.ForeignKey(
        "accounts.Membership",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="test_concrete_scoped_records",
    )
    title = models.CharField(max_length=100, default="Test Record")

    class Meta:
        app_label = "tests"


class BaseTenantQueryInfrastructureTestCase(TestCase):
    """Base test case providing model resolution, table creation, and test factories."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.membership_model = apps.get_model("accounts", "Membership")
        cls.workspace_model = apps.get_model("workspaces", "Workspace")
        cls.user_model = get_user_model()
        cls.workspace_scoped_model = get_workspace_scoped_model()
        cls.tenant_queryset_class = get_tenant_queryset_class()
        # staticmethod(): a plain function assigned to a class attribute becomes a bound
        # method, silently passing the TestCase instance as the first positional argument.
        client_predicate, coach_predicate, general_predicate = get_ownership_predicates()
        cls.client_predicate = staticmethod(client_predicate)
        cls.coach_predicate = staticmethod(coach_predicate)
        cls.general_predicate = staticmethod(general_predicate)

        with connection.schema_editor() as editor:
            editor.create_model(ConcreteWorkspaceScopedRecord)

    @classmethod
    def tearDownClass(cls):
        with connection.schema_editor() as editor:
            editor.delete_model(ConcreteWorkspaceScopedRecord)
        super().tearDownClass()

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

    def _create_scoped_record(self, workspace=None, client=None, title=None, **kwargs):
        """Helper to create a ConcreteWorkspaceScopedRecord instance."""
        if workspace is None:
            if client is not None and hasattr(client, "workspace"):
                workspace = client.workspace
            else:
                workspace = self._create_workspace()
        if title is None:
            title = f"Record {uuid.uuid4().hex[:8]}"
        defaults = {
            "workspace": workspace,
            "client": client,
            "title": title,
        }
        defaults.update(kwargs)
        return ConcreteWorkspaceScopedRecord.objects.create(**defaults)

    def _check_client_predicate(self, membership, workspace):
        """Helper to invoke discovered client ownership predicate with discovery guard."""
        if self.client_predicate is None:
            self.fail(
                "Client ownership predicate could not be discovered in common.models "
                "(expected 'can_client_own' or equivalent pure boolean callable)."
            )
        return invoke_ownership_predicate(self.client_predicate, membership, workspace)

    def _check_coach_predicate(self, membership, workspace):
        """Helper to invoke discovered coach ownership predicate with discovery guard."""
        if self.coach_predicate is None:
            self.fail(
                "Coach/owner ownership predicate could not be discovered in common.models "
                "(expected 'can_coach_own' or equivalent pure boolean callable)."
            )
        return invoke_ownership_predicate(self.coach_predicate, membership, workspace)

    def _check_general_predicate(self, membership, workspace):
        """Helper to invoke discovered general ownership predicate if available."""
        if self.general_predicate is None:
            self.fail(
                "General ownership predicate could not be discovered in common.models "
                "(expected 'can_own' or equivalent pure boolean callable)."
            )
        return invoke_ownership_predicate(self.general_predicate, membership, workspace)


class WorkspaceScopedModelContractTests(BaseTenantQueryInfrastructureTestCase):
    """Verifies schema specification, abstract meta attribute, and app boundaries."""

    def test_workspace_scoped_model_is_abstract(self):
        """Asserts WorkspaceScopedModel._meta.abstract is True."""
        if self.workspace_scoped_model is None:
            self.fail(
                "WorkspaceScopedModel could not be located in common.models or submodules. "
                "Expected an abstract model class with a 'workspace' ForeignKey to Workspace."
            )
        self.assertTrue(
            self.workspace_scoped_model._meta.abstract,
            "WorkspaceScopedModel must have abstract = True in Meta.",
        )

    def test_workspace_field_is_non_null_foreign_key_with_cascade_delete(self):
        """Asserts workspace field is a non-null ForeignKey configured with on_delete=CASCADE."""
        if self.workspace_scoped_model is None:
            self.fail("WorkspaceScopedModel could not be discovered in common.models.")
        field = self.workspace_scoped_model._meta.get_field("workspace")
        self.assertEqual(
            field.get_internal_type(),
            "ForeignKey",
            "WorkspaceScopedModel.workspace must report internal type 'ForeignKey'.",
        )
        self.assertFalse(
            field.null,
            "WorkspaceScopedModel.workspace must be required (null=False).",
        )
        self.assertEqual(
            field.remote_field.on_delete,
            models.CASCADE,
            "WorkspaceScopedModel.workspace on_delete must be models.CASCADE.",
        )

    def test_workspace_field_targets_workspace_model(self):
        """Asserts workspace field targets the Workspace model."""
        if self.workspace_scoped_model is None:
            self.fail("WorkspaceScopedModel could not be discovered in common.models.")
        field = self.workspace_scoped_model._meta.get_field("workspace")
        self.assertEqual(
            field.related_model,
            self.workspace_model,
            "WorkspaceScopedModel.workspace must target the Workspace model.",
        )

    def test_workspace_scoped_model_contributes_no_models_to_real_apps(self):
        """Asserts workspaces and accounts app model sets are completely unchanged.

        Guards that WorkspaceScopedModel is purely abstract: it contributes no model of its
        own. Concrete subclasses (PaymentMethod, Story 4.4) are expected members of the set;
        the abstract base itself must never appear.
        """
        workspaces_app = apps.get_app_config("workspaces")
        concrete_workspaces_models = {
            model._meta.object_name for model in workspaces_app.get_models()
        }
        self.assertSetEqual(
            concrete_workspaces_models,
            {"Workspace", "PaymentMethod"},
            "workspaces must expose exactly its approved concrete models.",
        )

        accounts_app = apps.get_app_config("accounts")
        concrete_accounts_models = {model._meta.object_name for model in accounts_app.get_models()}
        expected_accounts_models = {
            "User",
            "CoachProfile",
            "ClientProfile",
            "CoachSecurity",
            "Membership",
        }
        self.assertSetEqual(
            concrete_accounts_models,
            expected_accounts_models,
            "accounts app must expose exactly the 5 approved models.",
        )

    def test_workspace_scoped_model_has_no_standalone_database_table(self):
        """Asserts abstract WorkspaceScopedModel generates no standalone table."""
        if self.workspace_scoped_model is None:
            self.fail("WorkspaceScopedModel could not be discovered in common.models.")
        table_name = getattr(self.workspace_scoped_model._meta, "db_table", None)
        with connection.cursor() as cursor:
            table_list = connection.introspection.table_names(cursor)
        if table_name:
            self.assertNotIn(
                table_name,
                table_list,
                f"Abstract base table '{table_name}' must not exist in the database.",
            )


class TenantQuerySetForWorkspaceTests(BaseTenantQueryInfrastructureTestCase):
    """Verifies for_workspace isolation, fail-closed behavior on None, and chaining."""

    def test_for_workspace_filters_rows_to_target_workspace_only(self):
        """Asserts for_workspace returns only target workspace records and excludes others."""
        ws_a = self._create_workspace(slug="ws-isolation-a")
        ws_b = self._create_workspace(slug="ws-isolation-b")

        rec_a1 = self._create_scoped_record(workspace=ws_a, title="Alpha 1")
        rec_a2 = self._create_scoped_record(workspace=ws_a, title="Alpha 2")
        rec_b1 = self._create_scoped_record(workspace=ws_b, title="Beta 1")
        rec_b2 = self._create_scoped_record(workspace=ws_b, title="Beta 2")

        qs_a = ConcreteWorkspaceScopedRecord.objects.for_workspace(ws_a)
        self.assertEqual(
            qs_a.count(),
            2,
            "for_workspace(ws_a) must return exactly the 2 records belonging to ws_a.",
        )
        self.assertEqual(
            set(qs_a.values_list("id", flat=True)),
            {rec_a1.id, rec_a2.id},
            "for_workspace(ws_a) must match the exact PK set of Workspace A records.",
        )
        self.assertNotIn(rec_b1, qs_a)
        self.assertNotIn(rec_b2, qs_a)

        qs_b = ConcreteWorkspaceScopedRecord.objects.for_workspace(ws_b)
        self.assertEqual(
            qs_b.count(),
            2,
            "for_workspace(ws_b) must return exactly the 2 records belonging to ws_b.",
        )
        self.assertEqual(
            set(qs_b.values_list("id", flat=True)),
            {rec_b1.id, rec_b2.id},
            "for_workspace(ws_b) must match the exact PK set of Workspace B records.",
        )
        self.assertNotIn(rec_a1, qs_b)
        self.assertNotIn(rec_a2, qs_b)

    def test_for_workspace_with_none_returns_empty_queryset_fail_closed(self):
        """Fail-closed guard: asserts for_workspace(None) returns an empty queryset."""
        ws_a = self._create_workspace(slug="ws-for-none-a")
        ws_b = self._create_workspace(slug="ws-for-none-b")
        self._create_scoped_record(workspace=ws_a, title="Record A")
        self._create_scoped_record(workspace=ws_b, title="Record B")

        qs = ConcreteWorkspaceScopedRecord.objects.for_workspace(None)

        self.assertEqual(
            qs.count(),
            0,
            "for_workspace(None) must return an empty queryset (fail-closed guard).",
        )
        self.assertFalse(qs.exists(), "for_workspace(None) queryset exists() must be False.")
        self.assertEqual(
            list(qs),
            [],
            "for_workspace(None) must evaluate to an empty list, not all rows.",
        )

    def test_for_workspace_supports_further_filtering_and_chaining(self):
        """Asserts for_workspace querysets can be chained with standard Django filters."""
        ws_a = self._create_workspace(slug="ws-chaining-a")
        ws_b = self._create_workspace(slug="ws-chaining-b")

        rec_matching = self._create_scoped_record(workspace=ws_a, title="Special Target")
        self._create_scoped_record(workspace=ws_a, title="Other Title")
        self._create_scoped_record(workspace=ws_b, title="Special Target")

        qs = ConcreteWorkspaceScopedRecord.objects.for_workspace(ws_a).filter(
            title="Special Target"
        )
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().id, rec_matching.id)

    def test_for_workspace_isolation_with_multiple_records_across_workspaces(self):
        """Asserts multiple records created across workspaces maintain strict counts."""
        ws_a = self._create_workspace(slug="ws-counts-a")
        ws_b = self._create_workspace(slug="ws-counts-b")

        for i in range(3):
            self._create_scoped_record(workspace=ws_a, title=f"A-{i}")
        for i in range(2):
            self._create_scoped_record(workspace=ws_b, title=f"B-{i}")

        self.assertEqual(
            ConcreteWorkspaceScopedRecord.objects.for_workspace(ws_a).count(),
            3,
            "Workspace A must return exactly 3 records.",
        )
        self.assertEqual(
            ConcreteWorkspaceScopedRecord.objects.for_workspace(ws_b).count(),
            2,
            "Workspace B must return exactly 2 records.",
        )


class TenantQuerySetForContextTests(BaseTenantQueryInfrastructureTestCase):
    """Verifies for_context integration with WorkspaceContext and fail-closed handling."""

    def test_for_context_scopes_to_context_workspace(self):
        """Asserts for_context scopes to context.workspace matching for_workspace results."""
        ws_a = self._create_workspace(slug="ws-context-a")
        ws_b = self._create_workspace(slug="ws-context-b")
        coach_a = self._create_user(email="coach.ctx.a@example.com")
        mem_a = self._create_membership(user=coach_a, workspace=ws_a, role="COACH")

        rec_a = self._create_scoped_record(workspace=ws_a, title="Context A Record")
        rec_b = self._create_scoped_record(workspace=ws_b, title="Context B Record")

        if WorkspaceContext is not None:
            ctx_a = WorkspaceContext(workspace=ws_a, membership=mem_a)
        else:

            class SimpleContext:
                def __init__(self, workspace, membership):
                    self.workspace = workspace
                    self.membership = membership

            ctx_a = SimpleContext(workspace=ws_a, membership=mem_a)

        qs_ctx = ConcreteWorkspaceScopedRecord.objects.for_context(ctx_a)
        qs_ws = ConcreteWorkspaceScopedRecord.objects.for_workspace(ws_a)

        self.assertEqual(
            qs_ctx.count(),
            1,
            "for_context(ctx_a) must return exactly the 1 record in Workspace A.",
        )
        self.assertEqual(qs_ctx.first().id, rec_a.id)
        self.assertNotIn(rec_b, qs_ctx)
        self.assertEqual(
            set(qs_ctx.values_list("id", flat=True)),
            set(qs_ws.values_list("id", flat=True)),
            "for_context and for_workspace must produce identical result sets.",
        )

    def test_for_context_with_none_returns_empty_queryset_fail_closed(self):
        """Fail-closed guard: asserts for_context(None) returns an empty queryset."""
        ws_a = self._create_workspace(slug="ws-context-none-a")
        self._create_scoped_record(workspace=ws_a, title="Record A")

        qs = ConcreteWorkspaceScopedRecord.objects.for_context(None)

        self.assertEqual(
            qs.count(),
            0,
            "for_context(None) must return an empty queryset (fail-closed guard).",
        )
        self.assertFalse(qs.exists(), "for_context(None) queryset exists() must be False.")
        self.assertEqual(list(qs), [])

    def test_for_context_with_none_workspace_attribute_returns_empty_queryset(self):
        """Fail-closed guard: asserts a context whose workspace is None returns empty queryset."""
        ws_a = self._create_workspace(slug="ws-context-nullws-a")
        self._create_scoped_record(workspace=ws_a, title="Record A")

        class NullWorkspaceContext:
            workspace = None
            membership = None

        qs = ConcreteWorkspaceScopedRecord.objects.for_context(NullWorkspaceContext())

        self.assertEqual(
            qs.count(),
            0,
            "for_context with workspace=None must return an empty queryset.",
        )
        self.assertFalse(qs.exists())


class TenantQuerySetForClientTests(BaseTenantQueryInfrastructureTestCase):
    """Verifies for_client ownership filtering, fail-closed guards, and cross-tenant isolation."""

    def test_for_client_returns_only_active_client_records_in_workspace(self):
        """Asserts for_client returns only rows owned by that active client in that workspace."""
        ws_a = self._create_workspace(slug="ws-client-ownership-a")
        client_1_mem = self._create_membership(workspace=ws_a, role="CLIENT", status="ACTIVE")
        client_2_mem = self._create_membership(workspace=ws_a, role="CLIENT", status="ACTIVE")

        rec_c1 = self._create_scoped_record(
            workspace=ws_a, client=client_1_mem, title="Client 1 Record"
        )
        rec_c2 = self._create_scoped_record(
            workspace=ws_a, client=client_2_mem, title="Client 2 Record"
        )
        rec_unassigned = self._create_scoped_record(
            workspace=ws_a, client=None, title="Unassigned Record"
        )

        qs_c1 = ConcreteWorkspaceScopedRecord.objects.for_client(client_1_mem)
        self.assertEqual(
            qs_c1.count(),
            1,
            "for_client(client_1) must return only Client 1's record.",
        )
        self.assertEqual(qs_c1.first().id, rec_c1.id)
        self.assertNotIn(rec_c2, qs_c1)
        self.assertNotIn(rec_unassigned, qs_c1)

        qs_c2 = ConcreteWorkspaceScopedRecord.objects.for_client(client_2_mem)
        self.assertEqual(
            qs_c2.count(),
            1,
            "for_client(client_2) must return only Client 2's record.",
        )
        self.assertEqual(qs_c2.first().id, rec_c2.id)
        self.assertNotIn(rec_c1, qs_c2)
        self.assertNotIn(rec_unassigned, qs_c2)

    def test_for_client_with_none_membership_returns_empty_queryset_fail_closed(self):
        """Fail-closed guard: asserts for_client(None) returns an empty queryset."""
        ws_a = self._create_workspace(slug="ws-client-none-a")
        client_mem = self._create_membership(workspace=ws_a, role="CLIENT", status="ACTIVE")
        self._create_scoped_record(workspace=ws_a, client=client_mem, title="Client Record")

        qs = ConcreteWorkspaceScopedRecord.objects.for_client(None)

        self.assertEqual(
            qs.count(),
            0,
            "for_client(None) must return an empty queryset (fail-closed guard).",
        )
        self.assertFalse(qs.exists(), "for_client(None) queryset exists() must be False.")
        self.assertEqual(list(qs), [])

    def test_for_client_with_inactive_membership_returns_empty_queryset_fail_closed(self):
        """Central guard: asserts for_client with an INACTIVE membership returns empty queryset.

        Even though the membership row exists and references data, status='INACTIVE'
        must fail closed and yield zero rows.
        """
        ws_a = self._create_workspace(slug="ws-client-inactive-a")
        client_mem = self._create_membership(workspace=ws_a, role="CLIENT", status="ACTIVE")
        self._create_scoped_record(workspace=ws_a, client=client_mem, title="Client Record")

        # Confirm data is returned when active
        self.assertEqual(
            ConcreteWorkspaceScopedRecord.objects.for_client(client_mem).count(),
            1,
        )

        # Transition membership to INACTIVE
        client_mem.status = "INACTIVE"
        client_mem.save()
        client_mem.refresh_from_db()

        qs = ConcreteWorkspaceScopedRecord.objects.for_client(client_mem)

        self.assertEqual(
            qs.count(),
            0,
            "for_client() with status='INACTIVE' must return an empty queryset (fail-closed).",
        )
        self.assertFalse(qs.exists(), "Inactive client queryset exists() must be False.")
        self.assertEqual(list(qs), [])

    def test_for_client_with_owner_role_membership_returns_empty_queryset(self):
        """Fail-closed guard: asserts for_client with an OWNER role membership returns empty."""
        ws_a = self._create_workspace(slug="ws-client-owner-role-a")
        owner_mem = self._create_membership(workspace=ws_a, role="OWNER", status="ACTIVE")
        self._create_scoped_record(workspace=ws_a, client=owner_mem, title="Owner Record")

        qs = ConcreteWorkspaceScopedRecord.objects.for_client(owner_mem)

        self.assertEqual(
            qs.count(),
            0,
            "for_client() with role='OWNER' must return an empty queryset.",
        )
        self.assertFalse(
            qs.exists(),
            "OWNER membership for_client queryset exists() must be False.",
        )
        self.assertEqual(list(qs), [])

    def test_for_client_with_coach_role_membership_returns_empty_queryset(self):
        """Fail-closed guard: asserts for_client with a COACH role membership returns empty."""
        ws_a = self._create_workspace(slug="ws-client-coach-role-a")
        coach_mem = self._create_membership(workspace=ws_a, role="COACH", status="ACTIVE")
        self._create_scoped_record(workspace=ws_a, client=coach_mem, title="Coach Record")

        qs = ConcreteWorkspaceScopedRecord.objects.for_client(coach_mem)

        self.assertEqual(
            qs.count(),
            0,
            "for_client() with role='COACH' must return an empty queryset.",
        )
        self.assertFalse(
            qs.exists(),
            "COACH membership for_client queryset exists() must be False.",
        )
        self.assertEqual(list(qs), [])

    def test_for_client_cross_tenant_isolation_same_user_different_workspaces(self):
        """Prominent cross-tenant guard: single User with memberships in two workspaces.

        CLIENT membership in Workspace A must return zero rows belonging to Workspace B,
        even though rows in Workspace B reference the same underlying User's membership B.
        """
        shared_user = self._create_user(email="multi.client.user@example.com")
        ws_a = self._create_workspace(slug="multi-client-ws-a")
        ws_b = self._create_workspace(slug="multi-client-ws-b")

        membership_a = self._create_membership(
            user=shared_user,
            workspace=ws_a,
            role="CLIENT",
            status="ACTIVE",
        )
        membership_b = self._create_membership(
            user=shared_user,
            workspace=ws_b,
            role="CLIENT",
            status="ACTIVE",
        )

        rec_a1 = self._create_scoped_record(
            workspace=ws_a, client=membership_a, title="Workspace A Record 1"
        )
        rec_a2 = self._create_scoped_record(
            workspace=ws_a, client=membership_a, title="Workspace A Record 2"
        )
        rec_b1 = self._create_scoped_record(
            workspace=ws_b, client=membership_b, title="Workspace B Record 1"
        )
        rec_b2 = self._create_scoped_record(
            workspace=ws_b, client=membership_b, title="Workspace B Record 2"
        )

        # Scoping by membership A returns only Workspace A records
        qs_a = ConcreteWorkspaceScopedRecord.objects.for_client(membership_a)
        self.assertEqual(
            qs_a.count(),
            2,
            "for_client(membership_a) must return exactly the 2 records in Workspace A.",
        )
        self.assertEqual(
            set(qs_a.values_list("id", flat=True)),
            {rec_a1.id, rec_a2.id},
            "for_client(membership_a) must match exact PK set of Workspace A records.",
        )
        self.assertNotIn(rec_b1, qs_a)
        self.assertNotIn(rec_b2, qs_a)

        # Scoping by membership B returns only Workspace B records
        qs_b = ConcreteWorkspaceScopedRecord.objects.for_client(membership_b)
        self.assertEqual(
            qs_b.count(),
            2,
            "for_client(membership_b) must return exactly the 2 records in Workspace B.",
        )
        self.assertEqual(
            set(qs_b.values_list("id", flat=True)),
            {rec_b1.id, rec_b2.id},
            "for_client(membership_b) must match exact PK set of Workspace B records.",
        )
        self.assertNotIn(rec_a1, qs_b)
        self.assertNotIn(rec_a2, qs_b)

    def test_for_client_scopes_by_membership_workspace_preventing_cross_workspace_anomaly(self):
        """Asserts for_client strictly scopes by membership.workspace even if client FK is forged.

        If a row in Workspace B references Client A (from Workspace A), for_client(client_a)
        must exclude the Workspace B row because client_a belongs to Workspace A.
        """
        ws_a = self._create_workspace(slug="ws-anomaly-a")
        ws_b = self._create_workspace(slug="ws-anomaly-b")
        client_a = self._create_membership(workspace=ws_a, role="CLIENT", status="ACTIVE")

        rec_valid = self._create_scoped_record(
            workspace=ws_a, client=client_a, title="Valid Row in A"
        )
        rec_cross_ws = self._create_scoped_record(
            workspace=ws_b, client=client_a, title="Anomalous Row in B"
        )

        qs = ConcreteWorkspaceScopedRecord.objects.for_client(client_a)
        self.assertEqual(
            qs.count(),
            1,
            "for_client must restrict to the membership's own workspace.",
        )
        self.assertEqual(qs.first().id, rec_valid.id)
        self.assertNotIn(rec_cross_ws, qs)


class TenantQuerySetUnscopedTests(BaseTenantQueryInfrastructureTestCase):
    """Verifies the unscoped() escape hatch behavior across workspaces."""

    def test_unscoped_returns_rows_across_all_workspaces(self):
        """Asserts unscoped() returns all records across multiple workspaces.

        Proves the escape hatch works and that scoped methods were genuinely filtering.
        """
        ws_a = self._create_workspace(slug="unscoped-ws-a")
        ws_b = self._create_workspace(slug="unscoped-ws-b")

        rec_a1 = self._create_scoped_record(workspace=ws_a, title="Unscoped A1")
        rec_a2 = self._create_scoped_record(workspace=ws_a, title="Unscoped A2")
        rec_b1 = self._create_scoped_record(workspace=ws_b, title="Unscoped B1")
        rec_b2 = self._create_scoped_record(workspace=ws_b, title="Unscoped B2")
        rec_b3 = self._create_scoped_record(workspace=ws_b, title="Unscoped B3")

        all_ids = {rec_a1.id, rec_a2.id, rec_b1.id, rec_b2.id, rec_b3.id}

        # Verify scoped counts first
        self.assertEqual(ConcreteWorkspaceScopedRecord.objects.for_workspace(ws_a).count(), 2)
        self.assertEqual(ConcreteWorkspaceScopedRecord.objects.for_workspace(ws_b).count(), 3)

        # Verify unscoped returns all 5
        qs_unscoped = ConcreteWorkspaceScopedRecord.objects.unscoped()
        self.assertEqual(
            qs_unscoped.count(),
            5,
            "unscoped() must return all records across all workspaces.",
        )
        self.assertEqual(
            set(qs_unscoped.values_list("id", flat=True)),
            all_ids,
            "unscoped() must include exact PK set of all created records.",
        )

    def test_unscoped_resets_prior_workspace_scoping(self):
        """Asserts calling unscoped() on an already scoped queryset resets the filter."""
        ws_a = self._create_workspace(slug="unscoped-reset-ws-a")
        ws_b = self._create_workspace(slug="unscoped-reset-ws-b")

        self._create_scoped_record(workspace=ws_a, title="A1")
        self._create_scoped_record(workspace=ws_b, title="B1")

        scoped_qs = ConcreteWorkspaceScopedRecord.objects.for_workspace(ws_a)
        self.assertEqual(scoped_qs.count(), 1)

        reset_qs = scoped_qs.unscoped()
        self.assertEqual(
            reset_qs.count(),
            2,
            "Calling unscoped() on a scoped queryset must reset the workspace filter.",
        )


class OwnershipPredicatesContractTests(BaseTenantQueryInfrastructureTestCase):
    """Verifies pure boolean return values, role/status guards, and non-raising behavior."""

    def test_client_ownership_predicate_success_for_active_client_in_target_workspace(self):
        """Asserts client ownership predicate returns True for active CLIENT in target workspace."""
        ws_a = self._create_workspace(slug="pred-client-success-a")
        client_mem = self._create_membership(workspace=ws_a, role="CLIENT", status="ACTIVE")

        result = self._check_client_predicate(client_mem, ws_a)

        self.assertIs(
            result,
            True,
            "Client ownership predicate must return True for active CLIENT in workspace.",
        )

    def test_client_ownership_predicate_returns_false_for_inactive_client(self):
        """Asserts client ownership predicate returns False for INACTIVE client."""
        ws_a = self._create_workspace(slug="pred-client-inactive-a")
        client_mem = self._create_membership(workspace=ws_a, role="CLIENT", status="INACTIVE")

        result = self._check_client_predicate(client_mem, ws_a)

        self.assertIs(
            result,
            False,
            "Client ownership predicate must return False for INACTIVE status.",
        )

    def test_client_ownership_predicate_returns_false_for_different_workspace(self):
        """Asserts client ownership predicate returns False when target workspace mismatches."""
        ws_a = self._create_workspace(slug="pred-client-diff-a")
        ws_b = self._create_workspace(slug="pred-client-diff-b")
        client_mem = self._create_membership(workspace=ws_a, role="CLIENT", status="ACTIVE")

        result = self._check_client_predicate(client_mem, ws_b)

        self.assertIs(
            result,
            False,
            "Client ownership predicate must return False when target workspace mismatches.",
        )

    def test_client_ownership_predicate_returns_false_for_coach_or_owner_role(self):
        """Asserts client ownership predicate returns False for OWNER and COACH roles."""
        ws_a = self._create_workspace(slug="pred-client-roles-a")
        coach_mem = self._create_membership(workspace=ws_a, role="COACH", status="ACTIVE")
        owner_mem = self._create_membership(workspace=ws_a, role="OWNER", status="ACTIVE")

        self.assertIs(
            self._check_client_predicate(coach_mem, ws_a),
            False,
            "Client ownership predicate must return False for COACH role.",
        )
        self.assertIs(
            self._check_client_predicate(owner_mem, ws_a),
            False,
            "Client ownership predicate must return False for OWNER role.",
        )

    def test_coach_ownership_predicate_success_for_active_coach_and_owner_in_workspace(self):
        """Asserts coach ownership predicate returns True for active COACH and OWNER."""
        ws_a = self._create_workspace(slug="pred-coach-success-a")
        coach_mem = self._create_membership(workspace=ws_a, role="COACH", status="ACTIVE")
        owner_mem = self._create_membership(workspace=ws_a, role="OWNER", status="ACTIVE")

        self.assertIs(
            self._check_coach_predicate(coach_mem, ws_a),
            True,
            "Coach ownership predicate must return True for active COACH in workspace.",
        )
        self.assertIs(
            self._check_coach_predicate(owner_mem, ws_a),
            True,
            "Coach ownership predicate must return True for active OWNER in workspace.",
        )

    def test_coach_ownership_predicate_returns_false_for_client_inactive_or_wrong_workspace(self):
        """Asserts coach ownership predicate returns False for CLIENT, INACTIVE, and wrong ws."""
        ws_a = self._create_workspace(slug="pred-coach-guards-a")
        ws_b = self._create_workspace(slug="pred-coach-guards-b")

        client_mem = self._create_membership(workspace=ws_a, role="CLIENT", status="ACTIVE")
        inactive_coach = self._create_membership(workspace=ws_a, role="COACH", status="INACTIVE")
        active_coach_a = self._create_membership(workspace=ws_a, role="COACH", status="ACTIVE")

        self.assertIs(
            self._check_coach_predicate(client_mem, ws_a),
            False,
            "Coach ownership predicate must return False for CLIENT role.",
        )
        self.assertIs(
            self._check_coach_predicate(inactive_coach, ws_a),
            False,
            "Coach ownership predicate must return False for INACTIVE status.",
        )
        self.assertIs(
            self._check_coach_predicate(active_coach_a, ws_b),
            False,
            "Coach ownership predicate must return False for wrong workspace.",
        )

    def test_ownership_predicates_return_strict_booleans_and_do_not_raise_on_invalid_inputs(self):
        """Asserts ownership predicates return booleans and never raise exceptions.

        Tests None, invalid types, and mismatched inputs across client and coach predicates.
        """
        ws = self._create_workspace(slug="pred-safe-ws")
        client_mem = self._create_membership(workspace=ws, role="CLIENT", status="ACTIVE")
        coach_mem = self._create_membership(workspace=ws, role="COACH", status="ACTIVE")

        # Test None inputs for client predicate
        res_client_none_mem = self._check_client_predicate(None, ws)
        res_client_none_ws = self._check_client_predicate(client_mem, None)
        res_client_both_none = self._check_client_predicate(None, None)

        self.assertIs(res_client_none_mem, False)
        self.assertIs(res_client_none_ws, False)
        self.assertIs(res_client_both_none, False)
        self.assertIsInstance(res_client_none_mem, bool)
        self.assertIsInstance(res_client_none_ws, bool)
        self.assertIsInstance(res_client_both_none, bool)

        # Test None inputs for coach predicate
        res_coach_none_mem = self._check_coach_predicate(None, ws)
        res_coach_none_ws = self._check_coach_predicate(coach_mem, None)
        res_coach_both_none = self._check_coach_predicate(None, None)

        self.assertIs(res_coach_none_mem, False)
        self.assertIs(res_coach_none_ws, False)
        self.assertIs(res_coach_both_none, False)
        self.assertIsInstance(res_coach_none_mem, bool)
        self.assertIsInstance(res_coach_none_ws, bool)
        self.assertIsInstance(res_coach_both_none, bool)
