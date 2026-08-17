"""Tenant isolation test suite (Story 3.5).

Validates end-to-end multi-tenant isolation guarantees across the data, query,
and permission layers according to Blueprint §8 and DB & Auth Architecture §27:

1. Client vs. Client Isolation (DB §27):
   - Two Clients with active CLIENT memberships in the same Workspace are strictly isolated.
   - for_client() returns only the caller's records, never another Client's records in the
     same Workspace.
   - ID-tampering attack simulation: querying another Client's record by primary key (UUID)
     through a scoped queryset yields an empty result / DoesNotExist.
   - Two-level isolation enforcement: workspace-level validation alone is insufficient;
     record-level client_id matching is required.

2. Cross-Workspace Client Isolation (Membership-Gated Access):
   - A Client cannot access records in another Workspace without an active Membership there.
   - resolve_workspace_context() fails with NotFound for workspaces where the user has no
     membership.
   - When an active CLIENT Membership in the second workspace is created, access to that
     workspace's own records is granted, proving access is gated by membership existence
     rather than a blanket denial.
   - Multi-workspace clients retain strict per-context record separation.

3. Coach / Owner Cross-Workspace Denial:
   - An active OWNER or COACH of Workspace A cannot access Workspace B records via
     for_workspace() or for_context().
   - coach_membership_can_own_workspace() returns False for foreign workspaces and foreign
     records.
   - Coach resolution against foreign workspace slugs raises NotFound.

4. Generic Workspace-Scoped Record Isolation (Standing in for Orders, Plans, Check-ins):
   - IsolationTestRecord validates the generic WorkspaceScopedModel infrastructure contract.
   - Records in Workspace A and Workspace B never leak across workspace filters.
   - unscoped() returns all rows across workspaces, verifying that scoped queries genuinely
     filtered records rather than passing vacuously on empty tables.
   - DB §10 cross-workspace integrity: records with mismatched workspace and client membership
     associations are hidden from client queries.

DEFERRED ASSERTIONS (to their owning Epics):
- Order domain model isolation assertions -> Epic 08
- TrainingPlan / NutritionPlan domain model isolation assertions -> Epics 11–12
- CheckIn domain model isolation assertions -> Epic 14
These models do not exist yet in the codebase. This suite validates the underlying generic
WorkspaceScopedModel infrastructure contract they will inherit upon creation.

5. Permission Layer End-to-End Isolation:
   - CoachWorkspacePermission and ClientWorkspacePermission reject foreign workspace slugs
     with NotFound.
   - Granted permissions attach the exact WorkspaceContext (Workspace + Membership) to the
     request, ensuring downstream query scoping cannot be redirected to another tenant.
   - Role boundaries within a workspace prevent privilege escalation (e.g. Client attempting
     Coach-permission endpoints raises PermissionDenied).
"""

import uuid

from django.contrib.auth import get_user_model
from django.db import connection, models
from django.test import TestCase
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.test import APIRequestFactory

from apps.accounts.models import Membership
from apps.workspaces.models import Workspace
from common.middleware.workspace import WorkspaceContext, resolve_workspace_context
from common.models import (
    WorkspaceScopedModel,
    client_membership_can_own_workspace,
    coach_membership_can_own_workspace,
    membership_can_own_workspace,
)
from common.permissions import (
    ClientWorkspacePermission,
    CoachWorkspacePermission,
)

User = get_user_model()


class IsolationTestRecord(WorkspaceScopedModel):
    """Test-only concrete model implementing WorkspaceScopedModel.

    Stands in for generic workspace-scoped business entities (such as future
    Orders, Plans, Check-ins) and validates multi-tenant isolation contracts
    without inventing or validating any future domain model.

    Deferred domain-specific assertions:
    - Order domain model isolation is deferred to Epic 08.
    - TrainingPlan and NutritionPlan domain model isolation are deferred to Epics 11–12.
    - CheckIn domain model isolation is deferred to Epic 14.
    """

    client = models.ForeignKey(
        "accounts.Membership",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="test_isolation_records_as_client",
    )
    owner = models.ForeignKey(
        "accounts.Membership",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="test_isolation_records_as_owner",
    )
    title = models.CharField(max_length=100, default="Isolation Test Record")

    class Meta:
        app_label = "tests"


class FakeWorkspaceView:
    """Lightweight mock view carrying URL slug kwargs for DRF permission testing."""

    def __init__(self, slug: str) -> None:
        self.kwargs = {"workspace_slug": slug}


class TenantIsolationBaseTestCase(TestCase):
    """Base test case providing schema lifecycle management and entity factories."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.schema_editor() as editor:
            editor.create_model(IsolationTestRecord)

    @classmethod
    def tearDownClass(cls):
        with connection.schema_editor() as editor:
            editor.delete_model(IsolationTestRecord)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.request_factory = APIRequestFactory()

    def _create_user(self, email=None, password="SecurePassword123!", **kwargs):
        """Helper to create a User instance with a unique default email."""
        if email is None:
            email = f"user-{uuid.uuid4().hex[:8]}@example.com"
        return User.objects.create_user(email=email, password=password, **kwargs)

    def _create_workspace(self, name=None, slug=None, status=Workspace.Status.ACTIVE, **kwargs):
        """Helper to create a Workspace instance with required defaults."""
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
        return Workspace.objects.create(**defaults)

    def _create_membership(
        self,
        user=None,
        workspace=None,
        role=Membership.Role.CLIENT,
        status=Membership.Status.ACTIVE,
        **kwargs,
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
        return Membership.objects.create(**defaults)

    def _create_record(self, workspace=None, client=None, owner=None, title=None, **kwargs):
        """Helper to create an IsolationTestRecord instance."""
        if workspace is None:
            if client is not None:
                workspace = client.workspace
            elif owner is not None:
                workspace = owner.workspace
            else:
                workspace = self._create_workspace()
        if title is None:
            title = f"Record {uuid.uuid4().hex[:8]}"
        defaults = {
            "workspace": workspace,
            "client": client,
            "owner": owner,
            "title": title,
        }
        defaults.update(kwargs)
        return IsolationTestRecord.objects.create(**defaults)


class ClientIsolationSameWorkspaceTests(TenantIsolationBaseTestCase):
    """Validates DB §27: Client A cannot access Client B within the same workspace."""

    def test_client_scoped_queryset_excludes_other_client_in_same_workspace(self):
        """Asserts for_client() returns only caller's rows and excludes peer client rows."""
        ws = self._create_workspace(slug="shared-gym")
        user_a = self._create_user(email="client.a@example.com")
        user_b = self._create_user(email="client.b@example.com")
        member_a = self._create_membership(user=user_a, workspace=ws, role=Membership.Role.CLIENT)
        member_b = self._create_membership(user=user_b, workspace=ws, role=Membership.Role.CLIENT)

        rec_a1 = self._create_record(workspace=ws, client=member_a, title="Plan A1")
        rec_a2 = self._create_record(workspace=ws, client=member_a, title="Plan A2")
        rec_b1 = self._create_record(workspace=ws, client=member_b, title="Plan B1")
        rec_b2 = self._create_record(workspace=ws, client=member_b, title="Plan B2")

        # Workspace filter alone contains all four records
        ws_records = IsolationTestRecord.objects.for_workspace(ws)
        self.assertEqual(ws_records.count(), 4)
        self.assertEqual(
            set(ws_records.values_list("pk", flat=True)),
            {rec_a1.pk, rec_a2.pk, rec_b1.pk, rec_b2.pk},
        )

        # Client A scoped queryset must strictly contain only A's records
        qs_a = IsolationTestRecord.objects.for_client(member_a)
        self.assertEqual(qs_a.count(), 2)
        self.assertEqual(set(qs_a.values_list("pk", flat=True)), {rec_a1.pk, rec_a2.pk})
        self.assertFalse(qs_a.filter(client=member_b).exists())

        # Client B scoped queryset must strictly contain only B's records
        qs_b = IsolationTestRecord.objects.for_client(member_b)
        self.assertEqual(qs_b.count(), 2)
        self.assertEqual(set(qs_b.values_list("pk", flat=True)), {rec_b1.pk, rec_b2.pk})
        self.assertFalse(qs_b.filter(client=member_a).exists())

    def test_id_tampering_attack_direct_pk_filter_yields_empty(self):
        """Simulates DB §27 attack: querying peer client's record ID yields zero rows."""
        ws = self._create_workspace(slug="tamper-gym")
        user_a = self._create_user(email="attacker.a@example.com")
        user_b = self._create_user(email="victim.b@example.com")
        member_a = self._create_membership(user=user_a, workspace=ws, role=Membership.Role.CLIENT)
        member_b = self._create_membership(user=user_b, workspace=ws, role=Membership.Role.CLIENT)

        self._create_record(workspace=ws, client=member_a, title="Attacker Record")
        victim_rec = self._create_record(workspace=ws, client=member_b, title="Victim Record")

        # Attacker crafts a request targeting victim's record UUID through scoped queryset
        tampered_qs = IsolationTestRecord.objects.for_client(member_a).filter(pk=victim_rec.pk)
        self.assertEqual(tampered_qs.count(), 0)
        self.assertIsNone(tampered_qs.first())
        self.assertFalse(tampered_qs.exists())
        with self.assertRaises(IsolationTestRecord.DoesNotExist):
            IsolationTestRecord.objects.for_client(member_a).get(pk=victim_rec.pk)

    def test_id_tampering_attack_batch_pk_lookup_yields_empty(self):
        """Asserts batch lookups with peer client IDs return only caller-owned rows."""
        ws = self._create_workspace(slug="batch-tamper-gym")
        member_a = self._create_membership(
            user=self._create_user(email="client.a@example.com"),
            workspace=ws,
            role=Membership.Role.CLIENT,
        )
        member_b = self._create_membership(
            user=self._create_user(email="client.b@example.com"),
            workspace=ws,
            role=Membership.Role.CLIENT,
        )

        rec_a = self._create_record(workspace=ws, client=member_a, title="Rec A")
        rec_b1 = self._create_record(workspace=ws, client=member_b, title="Rec B1")
        rec_b2 = self._create_record(workspace=ws, client=member_b, title="Rec B2")

        # Looking up only B's IDs via A's scoped queryset returns nothing
        b_batch = IsolationTestRecord.objects.for_client(member_a).filter(
            pk__in=[rec_b1.pk, rec_b2.pk]
        )
        self.assertEqual(b_batch.count(), 0)
        self.assertListEqual(list(b_batch), [])

        # Looking up mixed IDs returns only A's record
        mixed_batch = IsolationTestRecord.objects.for_client(member_a).filter(
            pk__in=[rec_a.pk, rec_b1.pk]
        )
        self.assertEqual(mixed_batch.count(), 1)
        self.assertEqual(mixed_batch.first().pk, rec_a.pk)

    def test_client_cannot_query_unassigned_workspace_record(self):
        """Asserts records without a client FK are excluded from for_client querysets."""
        ws = self._create_workspace(slug="unassigned-gym")
        member_a = self._create_membership(
            user=self._create_user(email="client.a@example.com"),
            workspace=ws,
            role=Membership.Role.CLIENT,
        )
        rec_a = self._create_record(workspace=ws, client=member_a, title="Client Record")
        rec_unassigned = self._create_record(workspace=ws, client=None, title="Gym General")

        qs = IsolationTestRecord.objects.for_client(member_a)
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().pk, rec_a.pk)
        self.assertFalse(qs.filter(pk=rec_unassigned.pk).exists())
        self.assertEqual(qs.filter(client__isnull=True).count(), 0)

    def test_two_level_isolation_workspace_predicate_vs_record_ownership(self):
        """Demonstrates that Level 1 workspace match alone does not grant row ownership."""
        ws = self._create_workspace(slug="two-level-gym")
        member_a = self._create_membership(
            user=self._create_user(email="client.a@example.com"),
            workspace=ws,
            role=Membership.Role.CLIENT,
        )
        member_b = self._create_membership(
            user=self._create_user(email="client.b@example.com"),
            workspace=ws,
            role=Membership.Role.CLIENT,
        )
        rec_b = self._create_record(workspace=ws, client=member_b, title="Client B Plan")

        # Level 1: Workspace check passes because both belong to ws
        self.assertTrue(client_membership_can_own_workspace(member_a, ws))
        self.assertTrue(client_membership_can_own_workspace(member_a, rec_b))

        # Level 2: Record-level ownership check blocks Client A from accessing Client B's record
        self.assertNotEqual(rec_b.client_id, member_a.pk)
        self.assertEqual(rec_b.client_id, member_b.pk)
        self.assertFalse(
            IsolationTestRecord.objects.for_client(member_a).filter(pk=rec_b.pk).exists()
        )


class CrossWorkspaceClientIsolationTests(TenantIsolationBaseTestCase):
    """Validates that Client access across workspaces is strictly gated by membership."""

    def test_client_denied_other_workspace_records_when_no_membership_exists(self):
        """Asserts a client with membership in WS A gets zero rows from WS B."""
        ws_a = self._create_workspace(slug="workspace-alpha")
        ws_b = self._create_workspace(slug="workspace-beta")
        user = self._create_user(email="single.client@example.com")
        member_a = self._create_membership(user=user, workspace=ws_a, role=Membership.Role.CLIENT)

        other_member_b = self._create_membership(
            user=self._create_user(email="other.client@example.com"),
            workspace=ws_b,
            role=Membership.Role.CLIENT,
        )

        rec_a = self._create_record(workspace=ws_a, client=member_a, title="Plan Alpha")
        rec_b = self._create_record(workspace=ws_b, client=other_member_b, title="Plan Beta")

        qs = IsolationTestRecord.objects.for_client(member_a)
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().pk, rec_a.pk)
        self.assertFalse(qs.filter(workspace=ws_b).exists())
        self.assertFalse(qs.filter(pk=rec_b.pk).exists())

    def test_resolve_workspace_context_fails_for_client_without_membership_in_target_workspace(
        self,
    ):
        """Asserts resolve_workspace_context raises NotFound for non-member workspaces."""
        ws_a = self._create_workspace(slug="user-home-ws")
        ws_b = self._create_workspace(slug="user-foreign-ws")
        user = self._create_user(email="traveler.client@example.com")
        self._create_membership(user=user, workspace=ws_a, role=Membership.Role.CLIENT)

        with self.assertRaises(NotFound):
            resolve_workspace_context(user, ws_b.slug)

        with self.assertRaises(NotFound):
            resolve_workspace_context(user, ws_b.slug, allowed_roles=[Membership.Role.CLIENT])

    def test_client_granted_access_to_second_workspace_when_membership_added(self):
        """Proves access is allowed when membership exists, showing the rule is conditional."""
        ws_a = self._create_workspace(slug="gym-north")
        ws_b = self._create_workspace(slug="gym-south")
        user = self._create_user(email="dual.member@example.com")

        member_a = self._create_membership(user=user, workspace=ws_a, role=Membership.Role.CLIENT)
        rec_a = self._create_record(workspace=ws_a, client=member_a, title="North Plan")

        # Prior to joining WS B: resolution fails
        with self.assertRaises(NotFound):
            resolve_workspace_context(user, ws_b.slug, allowed_roles=[Membership.Role.CLIENT])

        # Add active CLIENT membership in WS B
        member_b = self._create_membership(user=user, workspace=ws_b, role=Membership.Role.CLIENT)
        rec_b = self._create_record(workspace=ws_b, client=member_b, title="South Plan")

        # Now resolution succeeds for WS B
        ctx_b = resolve_workspace_context(user, ws_b.slug, allowed_roles=[Membership.Role.CLIENT])
        self.assertEqual(ctx_b.workspace, ws_b)
        self.assertEqual(ctx_b.membership, member_b)

        # Scoped queryset for WS B returns South Plan and excludes North Plan
        qs_b = IsolationTestRecord.objects.for_client(member_b)
        self.assertEqual(qs_b.count(), 1)
        self.assertEqual(qs_b.first().pk, rec_b.pk)
        self.assertFalse(qs_b.filter(pk=rec_a.pk).exists())
        self.assertFalse(qs_b.filter(workspace=ws_a).exists())

    def test_multi_workspace_client_scoped_queries_remain_strictly_isolated(self):
        """Asserts each membership queryset only returns rows belonging to that membership."""
        ws_a = self._create_workspace(slug="hub-a")
        ws_b = self._create_workspace(slug="hub-b")
        user = self._create_user(email="multi.hub.client@example.com")

        member_a = self._create_membership(user=user, workspace=ws_a, role=Membership.Role.CLIENT)
        member_b = self._create_membership(user=user, workspace=ws_b, role=Membership.Role.CLIENT)

        rec_a1 = self._create_record(workspace=ws_a, client=member_a, title="A1")
        rec_a2 = self._create_record(workspace=ws_a, client=member_a, title="A2")
        rec_b1 = self._create_record(workspace=ws_b, client=member_b, title="B1")
        rec_b2 = self._create_record(workspace=ws_b, client=member_b, title="B2")

        qs_a = IsolationTestRecord.objects.for_client(member_a)
        qs_b = IsolationTestRecord.objects.for_client(member_b)

        self.assertEqual(set(qs_a.values_list("pk", flat=True)), {rec_a1.pk, rec_a2.pk})
        self.assertEqual(set(qs_b.values_list("pk", flat=True)), {rec_b1.pk, rec_b2.pk})

        pks_a = set(qs_a.values_list("pk", flat=True))
        pks_b = set(qs_b.values_list("pk", flat=True))
        self.assertTrue(pks_a.isdisjoint(pks_b))

        self.assertEqual(qs_a.filter(workspace=ws_b).count(), 0)
        self.assertEqual(qs_b.filter(workspace=ws_a).count(), 0)
        self.assertEqual(qs_a.filter(client=member_b).count(), 0)
        self.assertEqual(qs_b.filter(client=member_a).count(), 0)


class CoachCrossWorkspaceIsolationTests(TenantIsolationBaseTestCase):
    """Validates Coach / Owner cross-workspace isolation beyond Story 3.3 resolution."""

    def test_owner_cannot_query_other_workspace_records_via_workspace_filter(self):
        """Asserts for_workspace() using Owner A's workspace returns zero WS B records."""
        ws_a = self._create_workspace(slug="owner-ws-a")
        ws_b = self._create_workspace(slug="owner-ws-b")
        owner_a = self._create_membership(
            user=self._create_user(email="owner.a@example.com"),
            workspace=ws_a,
            role=Membership.Role.OWNER,
        )

        rec_a = self._create_record(workspace=ws_a, owner=owner_a, title="Owner A Record")
        rec_b = self._create_record(workspace=ws_b, title="WS B Record")

        qs = IsolationTestRecord.objects.for_workspace(owner_a.workspace)
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().pk, rec_a.pk)
        self.assertFalse(qs.filter(pk=rec_b.pk).exists())
        self.assertEqual(qs.filter(workspace=ws_b).count(), 0)

    def test_owner_cannot_query_other_workspace_records_via_context_filter(self):
        """Asserts for_context() with Owner A context returns zero WS B records."""
        ws_a = self._create_workspace(slug="owner-ctx-a")
        ws_b = self._create_workspace(slug="owner-ctx-b")
        owner_a = self._create_membership(
            user=self._create_user(email="owner.ctx@example.com"),
            workspace=ws_a,
            role=Membership.Role.OWNER,
        )

        rec_a = self._create_record(workspace=ws_a, owner=owner_a, title="Record A")
        rec_b = self._create_record(workspace=ws_b, title="Record B")

        ctx_a = WorkspaceContext(workspace=ws_a, membership=owner_a)
        qs = IsolationTestRecord.objects.for_context(ctx_a)
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().pk, rec_a.pk)
        self.assertFalse(qs.filter(pk=rec_b.pk).exists())
        self.assertEqual(qs.filter(workspace=ws_b).count(), 0)

    def test_coach_cannot_query_other_workspace_records_via_context_filter(self):
        """Asserts for_context() with Coach A context returns zero WS B records."""
        ws_a = self._create_workspace(slug="coach-ctx-a")
        ws_b = self._create_workspace(slug="coach-ctx-b")
        coach_a = self._create_membership(
            user=self._create_user(email="coach.ctx@example.com"),
            workspace=ws_a,
            role=Membership.Role.COACH,
        )

        rec_a = self._create_record(workspace=ws_a, owner=coach_a, title="Record A")
        rec_b = self._create_record(workspace=ws_b, title="Record B")

        ctx_a = WorkspaceContext(workspace=ws_a, membership=coach_a)
        qs = IsolationTestRecord.objects.for_context(ctx_a)
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().pk, rec_a.pk)
        self.assertFalse(qs.filter(pk=rec_b.pk).exists())
        self.assertEqual(qs.filter(workspace=ws_b).count(), 0)

    def test_coach_ownership_predicate_rejects_other_workspace(self):
        """Asserts coach_membership_can_own_workspace returns False for foreign workspaces."""
        ws_a = self._create_workspace(slug="pred-ws-a")
        ws_b = self._create_workspace(slug="pred-ws-b")
        owner_a = self._create_membership(
            user=self._create_user(email="owner.pred@example.com"),
            workspace=ws_a,
            role=Membership.Role.OWNER,
        )
        coach_a = self._create_membership(
            user=self._create_user(email="coach.pred@example.com"),
            workspace=ws_a,
            role=Membership.Role.COACH,
        )

        self.assertFalse(coach_membership_can_own_workspace(owner_a, ws_b))
        self.assertFalse(coach_membership_can_own_workspace(coach_a, ws_b))
        self.assertTrue(coach_membership_can_own_workspace(owner_a, ws_a))
        self.assertTrue(coach_membership_can_own_workspace(coach_a, ws_a))

    def test_coach_ownership_predicate_rejects_other_workspace_record(self):
        """Asserts coach_membership_can_own_workspace returns False for foreign records."""
        ws_a = self._create_workspace(slug="rec-pred-ws-a")
        ws_b = self._create_workspace(slug="rec-pred-ws-b")
        owner_a = self._create_membership(
            user=self._create_user(email="owner.rpred@example.com"),
            workspace=ws_a,
            role=Membership.Role.OWNER,
        )
        coach_a = self._create_membership(
            user=self._create_user(email="coach.rpred@example.com"),
            workspace=ws_a,
            role=Membership.Role.COACH,
        )

        rec_a = self._create_record(workspace=ws_a, owner=owner_a, title="Rec A")
        rec_b = self._create_record(workspace=ws_b, title="Rec B")

        self.assertFalse(coach_membership_can_own_workspace(owner_a, rec_b))
        self.assertFalse(coach_membership_can_own_workspace(coach_a, rec_b))
        self.assertTrue(coach_membership_can_own_workspace(owner_a, rec_a))
        self.assertTrue(coach_membership_can_own_workspace(coach_a, rec_a))

    def test_coach_resolution_for_other_workspace_raises_not_found(self):
        """Asserts Coach / Owner resolution for foreign workspace slug raises NotFound."""
        ws_a = self._create_workspace(slug="slug-res-a")
        ws_b = self._create_workspace(slug="slug-res-b")
        coach_user = self._create_user(email="coach.res@example.com")
        owner_user = self._create_user(email="owner.res@example.com")

        self._create_membership(user=coach_user, workspace=ws_a, role=Membership.Role.COACH)
        self._create_membership(user=owner_user, workspace=ws_a, role=Membership.Role.OWNER)

        with self.assertRaises(NotFound):
            resolve_workspace_context(
                coach_user,
                ws_b.slug,
                allowed_roles=(Membership.Role.OWNER, Membership.Role.COACH),
            )

        with self.assertRaises(NotFound):
            resolve_workspace_context(
                owner_user,
                ws_b.slug,
                allowed_roles=(Membership.Role.OWNER, Membership.Role.COACH),
            )


class GenericWorkspaceScopedRecordIsolationTests(TenantIsolationBaseTestCase):
    """Validates generic WorkspaceScopedModel isolation (proxy for Orders, Plans, Check-ins)."""

    def test_records_in_different_workspaces_never_cross_workspace_filters(self):
        """Asserts for_workspace() strictly isolates records across distinct workspaces."""
        ws_a = self._create_workspace(slug="generic-ws-a")
        ws_b = self._create_workspace(slug="generic-ws-b")

        rec_a1 = self._create_record(workspace=ws_a, title="Entity A1")
        rec_a2 = self._create_record(workspace=ws_a, title="Entity A2")
        rec_a3 = self._create_record(workspace=ws_a, title="Entity A3")

        rec_b1 = self._create_record(workspace=ws_b, title="Entity B1")
        rec_b2 = self._create_record(workspace=ws_b, title="Entity B2")
        rec_b3 = self._create_record(workspace=ws_b, title="Entity B3")

        qs_a = IsolationTestRecord.objects.for_workspace(ws_a)
        qs_b = IsolationTestRecord.objects.for_workspace(ws_b)

        self.assertEqual(qs_a.count(), 3)
        self.assertEqual(qs_b.count(), 3)
        self.assertEqual(
            set(qs_a.values_list("pk", flat=True)),
            {rec_a1.pk, rec_a2.pk, rec_a3.pk},
        )
        self.assertEqual(
            set(qs_b.values_list("pk", flat=True)),
            {rec_b1.pk, rec_b2.pk, rec_b3.pk},
        )

        pks_a = set(qs_a.values_list("pk", flat=True))
        pks_b = set(qs_b.values_list("pk", flat=True))
        self.assertTrue(pks_a.isdisjoint(pks_b))

    def test_unscoped_queryset_returns_all_workspace_records_preventing_vacuous_pass(self):
        """Asserts unscoped() returns all rows across workspaces, verifying genuine filtering."""
        ws_a = self._create_workspace(slug="unscoped-ws-a")
        ws_b = self._create_workspace(slug="unscoped-ws-b")

        rec_a = self._create_record(workspace=ws_a, title="Record A")
        rec_b = self._create_record(workspace=ws_b, title="Record B")

        all_records = IsolationTestRecord.objects.unscoped()
        self.assertGreaterEqual(all_records.count(), 2)
        all_pks = set(all_records.values_list("pk", flat=True))
        self.assertTrue({rec_a.pk, rec_b.pk}.issubset(all_pks))

    def test_mismatched_client_workspace_record_is_hidden_from_client_queries(self):
        """Asserts DB §10: records with cross-workspace client FK are hidden from for_client."""
        ws_a = self._create_workspace(slug="cross-integrity-a")
        ws_b = self._create_workspace(slug="cross-integrity-b")

        member_a = self._create_membership(
            user=self._create_user(email="client.a@example.com"),
            workspace=ws_a,
            role=Membership.Role.CLIENT,
        )
        member_b = self._create_membership(
            user=self._create_user(email="client.b@example.com"),
            workspace=ws_b,
            role=Membership.Role.CLIENT,
        )

        # Mismatched record: workspace is WS A, but client membership belongs to WS B
        corrupt_rec = IsolationTestRecord.objects.create(
            workspace=ws_a,
            client=member_b,
            title="Corrupted Mismatched Record",
        )

        # Query for Client B filters workspace_id=ws_b, so it excludes corrupt_rec (in ws_a)
        qs_b = IsolationTestRecord.objects.for_client(member_b)
        self.assertFalse(qs_b.filter(pk=corrupt_rec.pk).exists())
        self.assertEqual(qs_b.count(), 0)

        # Query for Client A filters client_id=member_a.pk, so it excludes corrupt_rec
        qs_a = IsolationTestRecord.objects.for_client(member_a)
        self.assertFalse(qs_a.filter(pk=corrupt_rec.pk).exists())

    def test_general_membership_can_own_workspace_rejects_cross_workspace(self):
        """Asserts membership_can_own_workspace rejects all cross-workspace combinations."""
        ws_a = self._create_workspace(slug="gen-mem-a")
        ws_b = self._create_workspace(slug="gen-mem-b")

        owner_a = self._create_membership(
            user=self._create_user(email="owner@example.com"),
            workspace=ws_a,
            role=Membership.Role.OWNER,
        )
        coach_a = self._create_membership(
            user=self._create_user(email="coach@example.com"),
            workspace=ws_a,
            role=Membership.Role.COACH,
        )
        client_a = self._create_membership(
            user=self._create_user(email="client@example.com"),
            workspace=ws_a,
            role=Membership.Role.CLIENT,
        )

        # Rejects WS B
        self.assertFalse(membership_can_own_workspace(owner_a, ws_b))
        self.assertFalse(membership_can_own_workspace(coach_a, ws_b))
        self.assertFalse(membership_can_own_workspace(client_a, ws_b))

        # Accepts WS A
        self.assertTrue(membership_can_own_workspace(owner_a, ws_a))
        self.assertTrue(membership_can_own_workspace(coach_a, ws_a))
        self.assertTrue(membership_can_own_workspace(client_a, ws_a))


class PermissionLayerEndToEndIsolationTests(TenantIsolationBaseTestCase):
    """Validates DRF permissions and downstream WorkspaceContext query chaining."""

    def test_coach_permission_denies_access_to_unaffiliated_workspace_slug(self):
        """Asserts CoachWorkspacePermission raises NotFound for foreign workspace slug."""
        ws_a = self._create_workspace(slug="perm-coach-a")
        ws_b = self._create_workspace(slug="perm-coach-b")
        coach_user = self._create_user(email="coach.perm@example.com")
        self._create_membership(user=coach_user, workspace=ws_a, role=Membership.Role.COACH)

        request = self.request_factory.get(f"/{ws_b.slug}/records/")
        request.user = coach_user
        view = FakeWorkspaceView(slug=ws_b.slug)

        with self.assertRaises(NotFound):
            CoachWorkspacePermission().has_permission(request, view)
        self.assertFalse(hasattr(request, "workspace_context"))

    def test_client_permission_denies_access_to_unaffiliated_workspace_slug(self):
        """Asserts ClientWorkspacePermission raises NotFound for foreign workspace slug."""
        ws_a = self._create_workspace(slug="perm-client-a")
        ws_b = self._create_workspace(slug="perm-client-b")
        client_user = self._create_user(email="client.perm@example.com")
        self._create_membership(user=client_user, workspace=ws_a, role=Membership.Role.CLIENT)

        request = self.request_factory.get(f"/{ws_b.slug}/records/")
        request.user = client_user
        view = FakeWorkspaceView(slug=ws_b.slug)

        with self.assertRaises(NotFound):
            ClientWorkspacePermission().has_permission(request, view)
        self.assertFalse(hasattr(request, "workspace_context"))

    def test_granted_coach_permission_attaches_exact_workspace_context_for_downstream_queries(
        self,
    ):
        """Asserts granted Coach permission populates request.workspace_context accurately."""
        ws_a = self._create_workspace(slug="chain-coach-a")
        ws_b = self._create_workspace(slug="chain-coach-b")
        coach_user = self._create_user(email="coach.chain@example.com")
        coach_m_a = self._create_membership(
            user=coach_user,
            workspace=ws_a,
            role=Membership.Role.COACH,
        )

        rec_a1 = self._create_record(workspace=ws_a, owner=coach_m_a, title="Record A1")
        rec_a2 = self._create_record(workspace=ws_a, owner=coach_m_a, title="Record A2")
        rec_b = self._create_record(workspace=ws_b, title="Record B")

        request = self.request_factory.get(f"/{ws_a.slug}/records/")
        request.user = coach_user
        view = FakeWorkspaceView(slug=ws_a.slug)

        allowed = CoachWorkspacePermission().has_permission(request, view)
        self.assertTrue(allowed)
        self.assertTrue(hasattr(request, "workspace_context"))
        self.assertEqual(request.workspace_context.workspace, ws_a)
        self.assertNotEqual(request.workspace_context.workspace, ws_b)
        self.assertEqual(request.workspace_context.membership, coach_m_a)

        # Downstream query execution using the attached workspace_context
        downstream_records = IsolationTestRecord.objects.for_context(request.workspace_context)
        self.assertEqual(downstream_records.count(), 2)
        self.assertEqual(
            set(downstream_records.values_list("pk", flat=True)),
            {rec_a1.pk, rec_a2.pk},
        )
        self.assertFalse(downstream_records.filter(pk=rec_b.pk).exists())
        self.assertEqual(downstream_records.filter(workspace=ws_b).count(), 0)

    def test_granted_client_permission_enforces_client_scoped_queries_downstream(self):
        """Asserts granted Client permission attaches membership used for client scoping."""
        ws_a = self._create_workspace(slug="chain-client-a")
        ws_b = self._create_workspace(slug="chain-client-b")

        user_a = self._create_user(email="client.chain.a@example.com")
        user_b = self._create_user(email="client.chain.b@example.com")
        member_a = self._create_membership(user=user_a, workspace=ws_a, role=Membership.Role.CLIENT)
        member_b = self._create_membership(user=user_b, workspace=ws_a, role=Membership.Role.CLIENT)

        rec_a = self._create_record(workspace=ws_a, client=member_a, title="Client A Record")
        rec_b = self._create_record(workspace=ws_a, client=member_b, title="Client B Record")
        rec_ws_b = self._create_record(workspace=ws_b, title="WS B Record")

        request = self.request_factory.get(f"/{ws_a.slug}/records/")
        request.user = user_a
        view = FakeWorkspaceView(slug=ws_a.slug)

        allowed = ClientWorkspacePermission().has_permission(request, view)
        self.assertTrue(allowed)
        self.assertTrue(hasattr(request, "workspace_context"))
        self.assertEqual(request.workspace_context.workspace, ws_a)
        self.assertEqual(request.workspace_context.membership, member_a)

        # Downstream query execution using the attached membership
        scoped_records = IsolationTestRecord.objects.for_client(
            request.workspace_context.membership
        )
        self.assertEqual(scoped_records.count(), 1)
        self.assertEqual(scoped_records.first().pk, rec_a.pk)
        self.assertFalse(scoped_records.filter(pk=rec_b.pk).exists())
        self.assertFalse(scoped_records.filter(pk=rec_ws_b.pk).exists())

    def test_client_role_cannot_access_coach_permission_endpoint_in_same_workspace(self):
        """Asserts Client role attempting Coach permission endpoint raises PermissionDenied."""
        ws = self._create_workspace(slug="esc-coach-gym")
        client_user = self._create_user(email="client.esc@example.com")
        self._create_membership(user=client_user, workspace=ws, role=Membership.Role.CLIENT)

        request = self.request_factory.get(f"/{ws.slug}/coach-dashboard/")
        request.user = client_user
        view = FakeWorkspaceView(slug=ws.slug)

        with self.assertRaises(PermissionDenied):
            CoachWorkspacePermission().has_permission(request, view)

    def test_coach_role_cannot_access_client_permission_endpoint_in_same_workspace(self):
        """Asserts Coach role attempting Client permission endpoint raises PermissionDenied."""
        ws = self._create_workspace(slug="cross-role-gym")
        coach_user = self._create_user(email="coach.cross@example.com")
        self._create_membership(user=coach_user, workspace=ws, role=Membership.Role.COACH)

        request = self.request_factory.get(f"/{ws.slug}/client-portal/")
        request.user = coach_user
        view = FakeWorkspaceView(slug=ws.slug)

        with self.assertRaises(PermissionDenied):
            ClientWorkspacePermission().has_permission(request, view)
