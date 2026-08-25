"""Tests for the Order model schema contract, constraints, and scoping (Story 8.1).

Validates:
- Exact model location and registration under apps.commerce (Point 1)
- Exact concrete field set specification (10 fields, set equality) (Point 2)
- UUID primary key typing and uniqueness (Point 3)
- Foreign key relation to Membership (accounts), not User or ClientProfile (Point 4)
- Client Membership round-tripping with CLIENT role (Point 5)
- Foreign key relation to Package (coaching) with round-tripping (Point 6)
- Multi-tenant workspace scoping and cross-tenant query isolation (Point 7)
- Status choices (5 documented values) and default to PENDING_PAYMENT (Point 8)
- Lifecycle status value persistence and round-tripping (Point 9)
- High-precision DecimalField round-tripping for amount (Point 10)
- 3-character CharField specification and round-tripping for currency (Point 11)
- Per-workspace UNIQUE(workspace, order_number) constraint and zero-padding (Point 12)
- Required, non-blank, non-null order_number field specification (Point 13)
- Automatic population and advancement of timestamps (Point 14)
- Architecture boundaries: commerce defines only {Order}, applications {Application} (Point 15)
"""

import time
import uuid
from datetime import datetime
from decimal import Decimal

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, models, transaction
from django.test import TestCase
from django.utils import timezone

from common.models.tenant import WorkspaceScopedModel

EXPECTED_ORDER_FIELDS = {
    "id",
    "workspace",
    "client",
    "package",
    "order_number",
    "amount",
    "currency",
    "status",
    "created_at",
    "updated_at",
}

EXPECTED_STATUS_CHOICES = {
    "PENDING_PAYMENT",
    "PAYMENT_SUBMITTED",
    "APPROVED",
    "REJECTED",
    "CANCELLED",
}


class BaseOrderModelTestCase(TestCase):
    """Base test case providing model resolution, cache resets, and factory helpers."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.order_model = apps.get_model("commerce", "Order")
        self.workspace_model = apps.get_model("workspaces", "Workspace")
        self.package_model = apps.get_model("coaching", "Package")
        self.membership_model = apps.get_model("accounts", "Membership")
        self.client_profile_model = apps.get_model("accounts", "ClientProfile")
        self.user_model = get_user_model()

    def _create_user(self, email=None, password="SecurePassword123!", **kwargs):
        """Creates and returns an email-verified user instance."""
        if email is None:
            email = f"user-{uuid.uuid4().hex[:8]}@example.com"
        kwargs.setdefault("email_verified_at", timezone.now())
        return self.user_model.objects.create_user(email=email, password=password, **kwargs)

    def _create_workspace(self, name=None, slug=None, **kwargs):
        """Creates and returns a Workspace instance."""
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
            "status": "ACTIVE",
        }
        defaults.update(kwargs)
        return self.workspace_model.objects.create(**defaults)

    def _create_membership(
        self,
        user=None,
        workspace=None,
        role="CLIENT",
        status="ACTIVE",
        **kwargs,
    ):
        """Creates and returns a Membership instance."""
        if workspace is None:
            workspace = self._create_workspace()
        if user is None:
            user = self._create_user()
        defaults = {
            "user": user,
            "workspace": workspace,
            "role": role,
            "status": status,
        }
        defaults.update(kwargs)
        return self.membership_model.objects.create(**defaults)

    def _create_package(self, workspace=None, is_active=True, **kwargs):
        """Creates and returns a coaching Package instance."""
        if workspace is None:
            workspace = self._create_workspace()
        unique_id = uuid.uuid4().hex[:8]
        defaults = {
            "workspace": workspace,
            "name": f"Pro Package {unique_id}",
            "description": "Comprehensive coaching package.",
            "price": Decimal("2500.00"),
            "currency": "USD",
            "duration_days": 30,
            "features": ["Personalized Coaching"],
            "is_active": is_active,
        }
        defaults.update(kwargs)
        return self.package_model.objects.create(**defaults)

    def _create_order(
        self,
        workspace=None,
        client=None,
        package=None,
        order_number=None,
        amount=Decimal("2500.00"),
        currency="USD",
        **kwargs,
    ):
        """Creates and returns an Order instance with valid foreign keys and defaults."""
        if workspace is None:
            workspace = self._create_workspace()
        if client is None:
            client = self._create_membership(
                workspace=workspace,
                role="CLIENT",
                status="ACTIVE",
            )
        if package is None:
            package = self._create_package(workspace=workspace)
        if order_number is None:
            order_number = f"ORD-{uuid.uuid4().hex[:8]}"
        defaults = {
            "workspace": workspace,
            "client": client,
            "package": package,
            "order_number": order_number,
            "amount": amount,
            "currency": currency,
        }
        defaults.update(kwargs)
        return self.order_model.objects.create(**defaults)


class OrderModelResolutionAndAppTests(BaseOrderModelTestCase):
    """Verifies that the Order model is registered in the correct app (Point 1)."""

    def test_order_model_resolves_and_belongs_to_commerce_app(self):
        """Asserts Order is registered under apps.commerce with correct app label (Point 1).

        Per ERD §19, the Order model belongs strictly to the commerce app.
        """
        self.assertEqual(
            self.order_model._meta.app_label,
            "commerce",
            "Order model must belong to the 'commerce' app.",
        )
        self.assertEqual(
            self.order_model._meta.object_name,
            "Order",
            "Order model class name must be 'Order'.",
        )


class OrderSchemaFieldContractTests(BaseOrderModelTestCase):
    """Verifies field set specification, foreign keys, currency, and requirement rules."""

    def test_exact_concrete_field_set(self):
        """Asserts Order defines exactly the 10 approved concrete fields (Point 2).

        Guards against invented extra fields (paid_at, notes, payment_method, subscription)
        or missing documented fields per DB Architecture §12 and ERD specifications.
        """
        concrete_fields = {field.name for field in self.order_model._meta.concrete_fields}
        self.assertSetEqual(
            concrete_fields,
            EXPECTED_ORDER_FIELDS,
            "Order concrete fields must match authoritative DB Architecture §12 schema.",
        )

    def test_client_field_is_foreign_key_to_membership_model_not_user_or_profile(self):
        """Guards tenant relationship: client must target accounts.Membership (Point 4).

        Per DB Architecture §10, Order.client must reference Membership to retain workspace
        context. Referencing User or ClientProfile is explicitly incorrect because global user
        entities lose workspace scoping.
        """
        client_field = self.order_model._meta.get_field("client")
        self.assertEqual(
            client_field.get_internal_type(),
            "ForeignKey",
            "Order.client must report internal type 'ForeignKey'.",
        )
        self.assertEqual(
            client_field.related_model,
            self.membership_model,
            "Order.client must target the accounts.Membership model.",
        )
        self.assertNotEqual(
            client_field.related_model,
            self.user_model,
            "Order.client must NOT target User model (loses workspace context).",
        )
        self.assertNotEqual(
            client_field.related_model,
            self.client_profile_model,
            "Order.client must NOT target ClientProfile model (loses workspace context).",
        )
        self.assertFalse(
            client_field.null,
            "Order.client must be required (null=False).",
        )
        self.assertFalse(
            client_field.blank,
            "Order.client must be non-blank (blank=False).",
        )

    def test_package_field_is_foreign_key_to_package_model(self):
        """Asserts package is a non-null ForeignKey to coaching.Package (Point 6)."""
        package_field = self.order_model._meta.get_field("package")
        self.assertEqual(
            package_field.get_internal_type(),
            "ForeignKey",
            "Order.package must report internal type 'ForeignKey'.",
        )
        self.assertEqual(
            package_field.related_model,
            self.package_model,
            "Order.package must target the coaching.Package model.",
        )
        self.assertFalse(
            package_field.null,
            "Order.package must be required (null=False).",
        )
        self.assertFalse(
            package_field.blank,
            "Order.package must be non-blank (blank=False).",
        )

    def test_order_package_reads_back_associated_package(self):
        """Asserts saved Order reads back the exact associated package (Point 6)."""
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)
        order = self._create_order(workspace=workspace, package=package)

        refetched = self.order_model.objects.get(pk=order.pk)
        self.assertEqual(refetched.package, package)
        self.assertEqual(refetched.package_id, package.id)

    def test_currency_field_is_three_character_char_field(self):
        """Asserts currency is a 3-character CharField matching ISO-4217 standard (Point 11)."""
        currency_field = self.order_model._meta.get_field("currency")
        self.assertEqual(
            currency_field.get_internal_type(),
            "CharField",
            "Order.currency must report internal type 'CharField'.",
        )
        self.assertEqual(
            currency_field.max_length,
            3,
            "Order.currency max_length must be 3 characters.",
        )
        self.assertFalse(
            currency_field.null,
            "Order.currency must be required (null=False).",
        )
        self.assertFalse(
            currency_field.blank,
            "Order.currency must be non-blank (blank=False).",
        )

    def test_currency_round_trips_standard_currency_codes(self):
        """Asserts standard 3-letter currency codes persist and round-trip (Point 11)."""
        for code in ("EGP", "USD", "EUR"):
            with self.subTest(currency=code):
                order = self._create_order(currency=code)
                refetched = self.order_model.objects.get(pk=order.pk)
                self.assertEqual(
                    refetched.currency,
                    code,
                    f"Order currency '{code}' must round-trip accurately.",
                )

    def test_order_number_field_is_required_non_blank_and_non_null(self):
        """Guards requirement contract: order_number is required on the model (Point 13).

        Story 8.1 provides the field and uniqueness constraint; allocation happens later
        inside transaction boundaries of Stories 7.3 and 8.2. No auto-generation or signal
        should exist at the model layer.
        """
        order_num_field = self.order_model._meta.get_field("order_number")
        self.assertEqual(
            order_num_field.get_internal_type(),
            "CharField",
            "Order.order_number must report internal type 'CharField'.",
        )
        self.assertFalse(
            order_num_field.null,
            "Order.order_number must be non-null (null=False).",
        )
        self.assertFalse(
            order_num_field.blank,
            "Order.order_number must be non-blank (blank=False).",
        )


class OrderPrimaryKeyTests(BaseOrderModelTestCase):
    """Verifies UUID primary key typing, uniqueness, and configuration (Point 3)."""

    def test_id_field_is_uuid_primary_key(self):
        """Guards architectural rule: primary key must be UUIDField, not BigAutoField (Point 3).

        WorkspaceScopedModel does NOT provide a primary key. A model subclass that omits
        an explicit primary key definition will silently receive an autoincrementing
        BigAutoField, violating API §25 Rule 13 (UUIDs for externally exposed identifiers).
        """
        pk_field = self.order_model._meta.pk
        self.assertTrue(
            pk_field.primary_key,
            "Order.id must be configured as a primary key.",
        )
        self.assertEqual(
            pk_field.get_internal_type(),
            "UUIDField",
            "Order.id must report internal type 'UUIDField', never BigAutoField.",
        )

    def test_saved_instance_id_is_uuid_instance(self):
        """Asserts saved Order instance receives a valid uuid.UUID identifier (Point 3)."""
        order = self._create_order()
        self.assertIsInstance(
            order.pk,
            uuid.UUID,
            "Order.pk must be an instance of uuid.UUID.",
        )
        self.assertIsInstance(
            order.id,
            uuid.UUID,
            "Order.id must be an instance of uuid.UUID.",
        )

    def test_two_saved_orders_receive_distinct_uuid_ids(self):
        """Asserts distinct Order instances receive distinct UUID primary keys (Point 3)."""
        order1 = self._create_order()
        order2 = self._create_order()
        self.assertNotEqual(
            order1.id,
            order2.id,
            "Two distinct Order instances must receive different UUID primary keys.",
        )


class OrderClientRelationshipTests(BaseOrderModelTestCase):
    """Verifies client Membership relationship and role round-tripping (Point 5)."""

    def test_order_round_trips_client_membership_relationship(self):
        """Asserts Order associates with a CLIENT Membership and round-trips (Point 5)."""
        workspace = self._create_workspace()
        user = self._create_user()
        membership = self._create_membership(
            user=user,
            workspace=workspace,
            role="CLIENT",
            status="ACTIVE",
        )
        order = self._create_order(
            workspace=workspace,
            client=membership,
        )

        refetched = self.order_model.objects.get(pk=order.pk)
        self.assertEqual(
            refetched.client,
            membership,
            "Order.client must match the associated Membership instance.",
        )
        self.assertEqual(
            refetched.client_id,
            membership.id,
            "Order.client_id must match the associated Membership id.",
        )
        self.assertEqual(
            refetched.client.role,
            "CLIENT",
            "Order client Membership must hold the 'CLIENT' role.",
        )
        self.assertEqual(
            refetched.client.status,
            "ACTIVE",
            "Order client Membership must hold the 'ACTIVE' status.",
        )


class OrderWorkspaceScopingTests(BaseOrderModelTestCase):
    """Verifies WorkspaceScopedModel inheritance and cross-tenant isolation (Point 7)."""

    def test_is_subclass_of_workspace_scoped_model(self):
        """Guards architectural rule: Order must inherit from WorkspaceScopedModel (Point 7)."""
        self.assertTrue(
            issubclass(self.order_model, WorkspaceScopedModel),
            "Order must be a subclass of WorkspaceScopedModel.",
        )

    def test_workspace_field_is_foreign_key_to_workspace_model(self):
        """Asserts workspace is a non-null ForeignKey targeting Workspace model (Point 7)."""
        workspace_field = self.order_model._meta.get_field("workspace")
        self.assertEqual(
            workspace_field.get_internal_type(),
            "ForeignKey",
            "Order.workspace must report internal type 'ForeignKey'.",
        )
        self.assertEqual(
            workspace_field.related_model,
            self.workspace_model,
            "Order.workspace must target the Workspace model.",
        )
        self.assertFalse(
            workspace_field.null,
            "Order.workspace must be required (null=False).",
        )
        self.assertEqual(
            workspace_field.remote_field.on_delete,
            models.CASCADE,
            "Order.workspace on_delete must be models.CASCADE.",
        )

    def test_manager_for_workspace_filters_strictly_by_workspace(self):
        """Guards cross-tenant isolation: for_workspace returns only target workspace records.

        Tenant isolation is a non-negotiable invariant. Orders created in Workspace 1
        must never leak into queries scoped to Workspace 2 (Point 7).
        """
        ws1 = self._create_workspace(slug="tenant-alpha")
        ws2 = self._create_workspace(slug="tenant-beta")
        pkg1 = self._create_package(workspace=ws1)
        pkg2 = self._create_package(workspace=ws2)
        client1 = self._create_membership(workspace=ws1, role="CLIENT", status="ACTIVE")
        client2 = self._create_membership(workspace=ws2, role="CLIENT", status="ACTIVE")

        order1 = self._create_order(
            workspace=ws1,
            client=client1,
            package=pkg1,
            order_number="ORD-WS1-001",
        )
        order2 = self._create_order(
            workspace=ws1,
            client=client1,
            package=pkg1,
            order_number="ORD-WS1-002",
        )
        order3 = self._create_order(
            workspace=ws2,
            client=client2,
            package=pkg2,
            order_number="ORD-WS2-001",
        )

        ws1_orders = self.order_model.objects.for_workspace(ws1)
        ws2_orders = self.order_model.objects.for_workspace(ws2)
        ws1_ids = set(ws1_orders.values_list("id", flat=True))
        ws2_ids = set(ws2_orders.values_list("id", flat=True))

        self.assertSetEqual(
            ws1_ids,
            {order1.id, order2.id},
            "for_workspace(ws1) must return exactly the orders belonging to Workspace 1.",
        )
        self.assertSetEqual(
            ws2_ids,
            {order3.id},
            "for_workspace(ws2) must return exactly the orders belonging to Workspace 2.",
        )
        self.assertNotIn(
            order3.id,
            ws1_ids,
            "Cross-tenant isolation failure: Workspace 2 order appeared in Workspace 1.",
        )
        self.assertNotIn(
            order1.id,
            ws2_ids,
            "Cross-tenant isolation failure: Workspace 1 order appeared in Workspace 2.",
        )


class OrderStatusAndLifecycleTests(BaseOrderModelTestCase):
    """Verifies status choices, default value, and lifecycle round-tripping (Points 8, 9)."""

    def test_status_choices_exact_five_documented_values(self):
        """Asserts status choices are exactly the five documented values (Point 8)."""
        status_field = self.order_model._meta.get_field("status")
        stored_choices = {
            choice[0] if isinstance(choice, (list, tuple)) else choice
            for choice in status_field.choices
        }
        self.assertSetEqual(
            stored_choices,
            EXPECTED_STATUS_CHOICES,
            "Order.status choices must be exactly the five documented values.",
        )

    def test_status_defaults_to_pending_payment_on_creation(self):
        """Asserts creating an Order without status defaults to PENDING_PAYMENT (Point 8)."""
        status_field = self.order_model._meta.get_field("status")
        default_val = (
            status_field.default.value
            if hasattr(status_field.default, "value")
            else status_field.default
        )
        self.assertEqual(
            default_val,
            "PENDING_PAYMENT",
            "Order.status default must be 'PENDING_PAYMENT'.",
        )

        order = self._create_order()
        refetched = self.order_model.objects.get(pk=order.pk)
        self.assertEqual(
            refetched.status,
            "PENDING_PAYMENT",
            "Order saved without explicit status must default to 'PENDING_PAYMENT'.",
        )

    def test_all_five_status_values_round_trip(self):
        """Asserts each documented lifecycle status can be saved and read back (Point 9).

        Guards status persistence across all five lifecycle states without asserting
        unspecified state machine transition enforcement at the model layer.
        """
        for expected_status in (
            "PENDING_PAYMENT",
            "PAYMENT_SUBMITTED",
            "APPROVED",
            "REJECTED",
            "CANCELLED",
        ):
            with self.subTest(status=expected_status):
                order = self._create_order(status=expected_status)
                refetched = self.order_model.objects.get(pk=order.pk)
                self.assertEqual(
                    refetched.status,
                    expected_status,
                    f"Order status '{expected_status}' must persist and round-trip.",
                )


class OrderAmountAndPrecisionTests(BaseOrderModelTestCase):
    """Verifies high-precision DecimalField round-tripping for amount (Point 10)."""

    def test_amount_field_is_decimal_field_with_two_decimal_places(self):
        """Asserts amount is a DecimalField configured with two decimal places (Point 10)."""
        amount_field = self.order_model._meta.get_field("amount")
        self.assertEqual(
            amount_field.get_internal_type(),
            "DecimalField",
            "Order.amount must report internal type 'DecimalField'.",
        )
        self.assertEqual(
            amount_field.decimal_places,
            2,
            "Order.amount must configure decimal_places=2.",
        )
        self.assertFalse(
            amount_field.null,
            "Order.amount must be non-null (null=False).",
        )
        self.assertFalse(
            amount_field.blank,
            "Order.amount must be non-blank (blank=False).",
        )

    def test_amount_decimal_precision_round_trips_without_float_drift(self):
        """Asserts amount round-trips precisely as Decimals with no float drift (Point 10).

        Financial amounts must never drift or truncate due to floating point conversions.
        """
        for test_amount in (Decimal("3500.00"), Decimal("1234.56"), Decimal("0.99")):
            with self.subTest(amount=test_amount):
                order = self._create_order(amount=test_amount)
                refetched = self.order_model.objects.get(pk=order.pk)
                self.assertEqual(
                    refetched.amount,
                    test_amount,
                    f"Order.amount must equal Decimal('{test_amount}') exactly.",
                )
                self.assertIsInstance(
                    refetched.amount,
                    Decimal,
                    "Order.amount must be an instance of Decimal.",
                )


class OrderNumberUniquenessAndFormattingTests(BaseOrderModelTestCase):
    """Verifies per-workspace order number uniqueness and formatting contracts (Point 12)."""

    def test_duplicate_order_number_in_same_workspace_is_rejected(self):
        """Guards uniqueness: duplicate order_number in SAME workspace raises IntegrityError.

        Per Blueprint §2D Decision 52, order numbers are unique per workspace. Attempting
        to insert an order with an existing order_number in the same workspace must fail.
        """
        workspace = self._create_workspace()
        self._create_order(workspace=workspace, order_number="000001")

        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                self._create_order(workspace=workspace, order_number="000001")

    def test_same_order_number_in_different_workspaces_is_permitted(self):
        """Guards per-workspace scoping: same order_number in DIFFERENT workspaces succeeds.

        Per Blueprint §2D Decision 52, order numbering is sequential and scoped per workspace
        rather than globally. Two workspaces may independently have order '000001'.
        """
        ws1 = self._create_workspace(slug="ws-num-alpha")
        ws2 = self._create_workspace(slug="ws-num-beta")

        order1 = self._create_order(workspace=ws1, order_number="000001")
        order2 = self._create_order(workspace=ws2, order_number="000001")

        self.assertIsNotNone(order1.pk)
        self.assertIsNotNone(order2.pk)

        refetched1 = self.order_model.objects.get(pk=order1.pk)
        refetched2 = self.order_model.objects.get(pk=order2.pk)
        self.assertEqual(refetched1.order_number, "000001")
        self.assertEqual(refetched2.order_number, "000001")
        self.assertNotEqual(refetched1.workspace_id, refetched2.workspace_id)

    def test_zero_padded_order_number_round_trips_as_exact_string(self):
        """Asserts zero-padded order_number preserves leading zeros as string (Point 12c).

        Order numbers are formatted strings (e.g. '000001') and must not be coerced
        into integers or stripped of leading zeros.
        """
        order = self._create_order(order_number="000001")
        refetched = self.order_model.objects.get(pk=order.pk)
        self.assertEqual(
            refetched.order_number,
            "000001",
            "Order.order_number must preserve leading zeros as exact string.",
        )
        self.assertIsInstance(
            refetched.order_number,
            str,
            "Order.order_number must be stored and returned as a string.",
        )


class OrderTimestampBehaviorTests(BaseOrderModelTestCase):
    """Verifies timestamp initialization and auto-updating behavior (Point 14)."""

    def test_created_at_and_updated_at_populated_on_insert(self):
        """Asserts created_at and updated_at are populated datetime instances on creation."""
        before_create = timezone.now()
        order = self._create_order()

        self.assertIsNotNone(order.created_at)
        self.assertIsNotNone(order.updated_at)
        self.assertIsInstance(order.created_at, datetime)
        self.assertIsInstance(order.updated_at, datetime)
        self.assertGreaterEqual(
            order.created_at,
            before_create,
            "created_at must be greater than or equal to timestamp captured before creation.",
        )
        self.assertGreaterEqual(
            order.updated_at,
            before_create,
            "updated_at must be greater than or equal to timestamp captured before creation.",
        )

    def test_updated_at_advances_on_save_while_created_at_is_preserved(self):
        """Asserts updated_at advances on subsequent save while created_at remains constant."""
        order = self._create_order(amount=Decimal("100.00"))
        initial_created_at = order.created_at
        initial_updated_at = order.updated_at

        time.sleep(0.01)
        order.amount = Decimal("200.00")
        order.save()
        order.refresh_from_db()

        self.assertEqual(
            order.created_at,
            initial_created_at,
            "created_at must remain constant across subsequent updates.",
        )
        self.assertGreater(
            order.updated_at,
            initial_updated_at,
            "updated_at must advance to a later timestamp on subsequent save.",
        )


class OrderArchitectureGuardTests(TestCase):
    """Verifies architectural boundaries across commerce and applications apps (Point 15)."""

    def test_commerce_app_exposes_exactly_order_model(self):
        """Guards architectural boundary: commerce app must define only Order (Point 15).

        Story 8.1 introduces only the Order model; downstream models like Payment or
        Subscription (Stories 8.3+) must not leak early into the commerce app.
        """
        commerce_app = apps.get_app_config("commerce")
        concrete_model_names = {model._meta.object_name for model in commerce_app.get_models()}
        self.assertSetEqual(
            concrete_model_names,
            {"Order"},
            "commerce app must define exactly {'Order'}; no Payment or Subscription models.",
        )

    def test_applications_app_still_exposes_only_application_model(self):
        """Guards architectural boundary: applications app must still define only Application.

        Cross-app workflows must not accidentally register Order or other models under
        applications app (Point 15).
        """
        applications_app = apps.get_app_config("applications")
        concrete_model_names = {model._meta.object_name for model in applications_app.get_models()}
        self.assertSetEqual(
            concrete_model_names,
            {"Application"},
            "applications app must define exactly {'Application'}.",
        )
