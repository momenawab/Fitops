"""Tests for the Membership model schema contract, constraints, and behavior (Story 3.2).

Validates:
- Exact concrete field set specification (8 fields, set equality)
- UUID primary key typing and uniqueness
- Role choices ({"OWNER", "COACH", "CLIENT"}) and explicit absence of default value
- Architectural absence of future-only "ASSISTANT_COACH" role
- Status choices ({"ACTIVE", "INACTIVE"}) and default ("ACTIVE")
- Required foreign keys for user (AUTH_USER_MODEL) and workspace (Workspace) with CASCADE on delete
- Database enforcement of UNIQUE(user, workspace) constraint (IntegrityError)
- Multi-tenant flexibility: same user in different workspaces, different users in same workspace
- Architectural capability: same user holding different roles across different workspaces
- Cascade deletion behavior when User or Workspace is deleted
- Automatic population of timestamps: joined_at, created_at, updated_at
- Non-empty string representation
- Architecture guards: accounts exposes 5 models, workspaces defines {Workspace},
  Workspace has no owner field, ClientProfile/CoachProfile remain un-scoped global identities
"""

import time
import uuid
from datetime import datetime

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import IntegrityError, models, transaction
from django.test import TestCase

EXPECTED_MEMBERSHIP_FIELDS = {
    "id",
    "workspace",
    "user",
    "role",
    "status",
    "joined_at",
    "created_at",
    "updated_at",
}

EXPECTED_ROLE_CHOICES = {"OWNER", "COACH", "CLIENT"}
EXPECTED_STATUS_CHOICES = {"ACTIVE", "INACTIVE"}


class BaseMembershipTestCase(TestCase):
    """Base test case providing model resolution and entity creation helpers."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.membership_model = apps.get_model("accounts", "Membership")
        cls.workspace_model = apps.get_model("workspaces", "Workspace")
        cls.user_model = get_user_model()

    def _create_user(self, email=None, password="SecurePassword123!", **kwargs):
        """Helper to create a User instance with a unique default email."""
        if email is None:
            email = f"user-{uuid.uuid4().hex[:8]}@example.com"
        return self.user_model.objects.create_user(email=email, password=password, **kwargs)

    def _create_workspace(self, name=None, slug=None, **kwargs):
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
        }
        defaults.update(kwargs)
        return self.workspace_model.objects.create(**defaults)

    def _create_membership(self, user=None, workspace=None, role="COACH", **kwargs):
        """Helper to create a Membership instance with valid foreign key relationships."""
        if user is None:
            user = self._create_user()
        if workspace is None:
            workspace = self._create_workspace()
        defaults = {
            "user": user,
            "workspace": workspace,
            "role": role,
        }
        defaults.update(kwargs)
        return self.membership_model.objects.create(**defaults)


class MembershipSchemaContractTests(BaseMembershipTestCase):
    """Verifies schema specification, field typing, choices, and absence of forbidden values."""

    def test_exact_concrete_field_set(self):
        """Asserts Membership defines exactly the eight approved concrete fields."""
        concrete_fields = {field.name for field in self.membership_model._meta.concrete_fields}
        self.assertSetEqual(
            concrete_fields,
            EXPECTED_MEMBERSHIP_FIELDS,
            "Membership concrete fields must exactly match the authoritative schema contract.",
        )

    def test_id_field_is_uuid_primary_key(self):
        """Asserts the id field is configured as a UUID primary key."""
        id_field = self.membership_model._meta.get_field("id")
        self.assertTrue(id_field.primary_key, "Membership.id must be a primary key.")
        self.assertEqual(
            id_field.get_internal_type(),
            "UUIDField",
            "Membership.id must report internal type 'UUIDField'.",
        )

    def test_role_choices_exact_set_and_has_no_default(self):
        """Asserts role choices are exactly OWNER, COACH, CLIENT, and has no default value."""
        role_field = self.membership_model._meta.get_field("role")
        stored_choices = {
            choice[0] if isinstance(choice, (list, tuple)) else choice
            for choice in role_field.choices
        }
        self.assertSetEqual(
            stored_choices,
            EXPECTED_ROLE_CHOICES,
            "Membership.role choices must be exactly {'OWNER', 'COACH', 'CLIENT'}.",
        )
        self.assertIn(
            role_field.default,
            (models.NOT_PROVIDED, None),
            "Membership.role must not have a default value; role must always be explicit.",
        )
        self.assertFalse(
            role_field.has_default(),
            "Membership.role has_default() must return False.",
        )

    def test_assistant_coach_role_is_absent_from_role_choices(self):
        """Guards architectural rule: ASSISTANT_COACH is a future-only role and must not exist."""
        role_field = self.membership_model._meta.get_field("role")
        stored_choices = {
            choice[0] if isinstance(choice, (list, tuple)) else choice
            for choice in role_field.choices
        }
        self.assertNotIn(
            "ASSISTANT_COACH",
            stored_choices,
            "ASSISTANT_COACH is documented as future-only and must NOT exist in Story 3.2.",
        )
        if hasattr(self.membership_model, "Role"):
            self.assertFalse(
                hasattr(self.membership_model.Role, "ASSISTANT_COACH"),
                "ASSISTANT_COACH must not exist as an attribute on Membership.Role.",
            )

    def test_status_choices_and_default_value(self):
        """Asserts status choices are exactly ACTIVE and INACTIVE, defaulting to ACTIVE."""
        status_field = self.membership_model._meta.get_field("status")
        stored_choices = {
            choice[0] if isinstance(choice, (list, tuple)) else choice
            for choice in status_field.choices
        }
        self.assertSetEqual(
            stored_choices,
            EXPECTED_STATUS_CHOICES,
            "Membership.status choices must be exactly {'ACTIVE', 'INACTIVE'}.",
        )
        self.assertEqual(
            status_field.default,
            "ACTIVE",
            "Membership.status field must default to 'ACTIVE'.",
        )

    def test_user_field_is_non_null_foreign_key_with_cascade_delete(self):
        """Asserts user field is a non-null ForeignKey configured with on_delete=CASCADE."""
        user_field = self.membership_model._meta.get_field("user")
        self.assertEqual(
            user_field.get_internal_type(),
            "ForeignKey",
            "Membership.user must report internal type 'ForeignKey'.",
        )
        self.assertFalse(
            user_field.null,
            "Membership.user must be required (null=False).",
        )
        self.assertEqual(
            user_field.remote_field.on_delete,
            models.CASCADE,
            "Membership.user on_delete must be models.CASCADE.",
        )

    def test_user_field_targets_auth_user_model(self):
        """Asserts user field targets the active AUTH_USER_MODEL."""
        user_field = self.membership_model._meta.get_field("user")
        self.assertEqual(
            user_field.related_model,
            self.user_model,
            "Membership.user must target the User model (AUTH_USER_MODEL).",
        )

    def test_workspace_field_is_non_null_foreign_key_with_cascade_delete(self):
        """Asserts workspace field is a non-null ForeignKey configured with on_delete=CASCADE."""
        workspace_field = self.membership_model._meta.get_field("workspace")
        self.assertEqual(
            workspace_field.get_internal_type(),
            "ForeignKey",
            "Membership.workspace must report internal type 'ForeignKey'.",
        )
        self.assertFalse(
            workspace_field.null,
            "Membership.workspace must be required (null=False).",
        )
        self.assertEqual(
            workspace_field.remote_field.on_delete,
            models.CASCADE,
            "Membership.workspace on_delete must be models.CASCADE.",
        )

    def test_workspace_field_targets_workspace_model(self):
        """Asserts workspace field targets the Workspace model."""
        workspace_field = self.membership_model._meta.get_field("workspace")
        self.assertEqual(
            workspace_field.related_model,
            self.workspace_model,
            "Membership.workspace must target the Workspace model.",
        )


class MembershipConstraintBehaviorTests(BaseMembershipTestCase):
    """Verifies UNIQUE(user, workspace) constraint and multi-tenant flexibility."""

    def test_duplicate_membership_for_same_user_and_workspace_raises_integrity_error(self):
        """Asserts creating a second Membership for same (user, workspace) raises IntegrityError."""
        user = self._create_user(email="unique.member@example.com")
        workspace = self._create_workspace(slug="unique-member-ws")
        self._create_membership(user=user, workspace=workspace, role="COACH")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._create_membership(user=user, workspace=workspace, role="CLIENT")

    def test_same_user_can_have_memberships_in_different_workspaces(self):
        """Asserts the same user can belong to multiple distinct workspaces."""
        user = self._create_user(email="multi.workspace.user@example.com")
        workspace_1 = self._create_workspace(slug="user-workspace-one")
        workspace_2 = self._create_workspace(slug="user-workspace-two")

        membership_1 = self._create_membership(user=user, workspace=workspace_1, role="COACH")
        membership_2 = self._create_membership(user=user, workspace=workspace_2, role="COACH")

        self.assertIsNotNone(membership_1.pk)
        self.assertIsNotNone(membership_2.pk)
        self.assertNotEqual(membership_1.pk, membership_2.pk)
        self.assertEqual(
            self.membership_model.objects.filter(user=user).count(),
            2,
            "The same user must be allowed to have memberships in multiple workspaces.",
        )

    def test_different_users_can_have_memberships_in_same_workspace(self):
        """Asserts multiple distinct users can belong to the same workspace."""
        workspace = self._create_workspace(slug="shared-coaching-ws")
        user_1 = self._create_user(email="coach.alpha@example.com")
        user_2 = self._create_user(email="coach.beta@example.com")

        membership_1 = self._create_membership(user=user_1, workspace=workspace, role="COACH")
        membership_2 = self._create_membership(user=user_2, workspace=workspace, role="COACH")

        self.assertIsNotNone(membership_1.pk)
        self.assertIsNotNone(membership_2.pk)
        self.assertNotEqual(membership_1.pk, membership_2.pk)
        self.assertEqual(
            self.membership_model.objects.filter(workspace=workspace).count(),
            2,
            "Different users must be allowed to have memberships in the same workspace.",
        )

    def test_same_user_can_hold_different_roles_in_different_workspaces(self):
        """Guards architectural property: role is strictly workspace-scoped.

        A single global User may be an OWNER in one Workspace and a CLIENT in another.
        """
        user = self._create_user(email="dual.role.user@example.com")
        owned_workspace = self._create_workspace(name="Apex Gym", slug="apex-gym")
        client_workspace = self._create_workspace(name="Zen Yoga", slug="zen-yoga")

        owner_membership = self._create_membership(
            user=user,
            workspace=owned_workspace,
            role="OWNER",
        )
        client_membership = self._create_membership(
            user=user,
            workspace=client_workspace,
            role="CLIENT",
        )

        self.assertNotEqual(owner_membership.pk, client_membership.pk)
        self.assertEqual(owner_membership.role, "OWNER")
        self.assertEqual(client_membership.role, "CLIENT")

        refetched_owner = self.membership_model.objects.get(pk=owner_membership.pk)
        refetched_client = self.membership_model.objects.get(pk=client_membership.pk)
        self.assertEqual(refetched_owner.role, "OWNER")
        self.assertEqual(refetched_client.role, "CLIENT")


class MembershipCascadeBehaviorTests(BaseMembershipTestCase):
    """Verifies CASCADE deletion behavior on related User and Workspace models."""

    def test_deleting_user_cascades_and_deletes_membership(self):
        """Asserts deleting a User deletes all associated Membership records."""
        user = self._create_user(email="user.cascade@example.com")
        workspace = self._create_workspace(slug="user-cascade-ws")
        membership = self._create_membership(user=user, workspace=workspace, role="COACH")
        membership_pk = membership.pk

        user.delete()

        self.assertFalse(
            self.membership_model.objects.filter(pk=membership_pk).exists(),
            "Deleting a User must cascade and delete associated Membership records.",
        )
        self.assertTrue(
            self.workspace_model.objects.filter(pk=workspace.pk).exists(),
            "Deleting a User must not delete the Workspace.",
        )

    def test_deleting_workspace_cascades_and_deletes_membership(self):
        """Asserts deleting a Workspace deletes all associated Membership records."""
        user = self._create_user(email="workspace.cascade@example.com")
        workspace = self._create_workspace(slug="workspace-cascade-ws")
        membership = self._create_membership(user=user, workspace=workspace, role="COACH")
        membership_pk = membership.pk

        workspace.delete()

        self.assertFalse(
            self.membership_model.objects.filter(pk=membership_pk).exists(),
            "Deleting a Workspace must cascade and delete associated Membership records.",
        )
        self.assertTrue(
            self.user_model.objects.filter(pk=user.pk).exists(),
            "Deleting a Workspace must not delete the User.",
        )


class MembershipDefaultsAndTimestampsTests(BaseMembershipTestCase):
    """Verifies default values, UUID uniqueness, timestamp management, and str representation."""

    def test_create_membership_without_explicit_status_defaults_to_active(self):
        """Asserts creating a Membership without explicit status defaults to ACTIVE."""
        user = self._create_user(email="default.status@example.com")
        workspace = self._create_workspace(slug="default-status-ws")
        membership = self.membership_model.objects.create(
            user=user,
            workspace=workspace,
            role="OWNER",
        )
        self.assertIsNotNone(membership.pk)
        self.assertEqual(
            membership.status,
            "ACTIVE",
            "Membership created without explicit status must default to 'ACTIVE'.",
        )
        refetched = self.membership_model.objects.get(pk=membership.pk)
        self.assertEqual(refetched.status, "ACTIVE")

    def test_two_saved_memberships_receive_distinct_uuid_primary_keys(self):
        """Asserts each newly created Membership receives a distinct UUID primary key."""
        user_1 = self._create_user(email="uuid.one@example.com")
        user_2 = self._create_user(email="uuid.two@example.com")
        workspace = self._create_workspace(slug="distinct-uuid-ws")

        membership_1 = self._create_membership(user=user_1, workspace=workspace, role="OWNER")
        membership_2 = self._create_membership(user=user_2, workspace=workspace, role="COACH")

        self.assertNotEqual(membership_1.id, membership_2.id)
        self.assertIsInstance(membership_1.id, uuid.UUID)
        self.assertIsInstance(membership_2.id, uuid.UUID)

    def test_joined_at_created_at_and_updated_at_are_populated_on_save(self):
        """Asserts joined_at, created_at, and updated_at are populated datetime instances."""
        membership = self._create_membership(role="COACH")

        self.assertIsNotNone(membership.joined_at)
        self.assertIsNotNone(membership.created_at)
        self.assertIsNotNone(membership.updated_at)
        self.assertIsInstance(membership.joined_at, datetime)
        self.assertIsInstance(membership.created_at, datetime)
        self.assertIsInstance(membership.updated_at, datetime)

    def test_updated_at_advances_on_save_while_created_at_and_joined_at_remain_constant(self):
        """Asserts updated_at advances on subsequent saves while created_at/joined_at stay fixed."""
        membership = self._create_membership(role="COACH")
        initial_joined_at = membership.joined_at
        initial_created_at = membership.created_at
        initial_updated_at = membership.updated_at

        time.sleep(0.01)
        membership.status = "INACTIVE"
        membership.save()
        membership.refresh_from_db()

        self.assertEqual(
            membership.joined_at,
            initial_joined_at,
            "joined_at must remain constant across subsequent saves.",
        )
        self.assertEqual(
            membership.created_at,
            initial_created_at,
            "created_at must remain constant across subsequent saves.",
        )
        self.assertGreater(
            membership.updated_at,
            initial_updated_at,
            "updated_at must advance on subsequent saves.",
        )

    def test_status_can_be_explicitly_set_to_inactive(self):
        """Asserts a Membership can be created with or transitioned to INACTIVE status."""
        membership = self._create_membership(role="CLIENT", status="INACTIVE")
        membership.refresh_from_db()
        self.assertEqual(membership.status, "INACTIVE")

    def test_str_representation_returns_non_empty_string(self):
        """Asserts str(membership) returns a non-empty string."""
        user = self._create_user(email="str.check@example.com")
        workspace = self._create_workspace(name="Str Test Gym", slug="str-test-gym")
        membership = self._create_membership(user=user, workspace=workspace, role="COACH")

        str_repr = str(membership)
        self.assertTrue(bool(str_repr), "str(membership) must return a non-empty string.")
        self.assertIsInstance(str_repr, str)


class MembershipArchitectureGuardTests(TestCase):
    """Verifies architectural boundaries across accounts and workspaces apps."""

    def test_accounts_app_exposes_exactly_approved_five_models(self):
        """Asserts accounts defines exactly the five approved models for Story 3.2.

        Guards that LoginOTP was NOT created early (deferred to Story 2.8).
        """
        accounts_app = apps.get_app_config("accounts")
        concrete_model_names = {model._meta.object_name for model in accounts_app.get_models()}
        expected_model_names = {
            "User",
            "CoachProfile",
            "ClientProfile",
            "CoachSecurity",
            "Membership",
        }
        self.assertSetEqual(
            concrete_model_names,
            expected_model_names,
            "accounts app must define exactly the five approved models for Story 3.2.",
        )

    def test_workspaces_app_still_exposes_only_workspace_model(self):
        """Asserts workspaces defines exactly {Workspace}, guarding against premature models."""
        workspaces_app = apps.get_app_config("workspaces")
        concrete_model_names = {model._meta.object_name for model in workspaces_app.get_models()}
        self.assertSetEqual(
            concrete_model_names,
            {"Workspace"},
            "workspaces app must expose only the 'Workspace' model in Story 3.2.",
        )

    def test_workspace_model_has_no_owner_field_or_user_relations(self):
        """Asserts Workspace has no owner field and no concrete relation to AUTH_USER_MODEL.

        Ownership is managed exclusively through Membership(role=OWNER).
        """
        workspace_model = apps.get_model("workspaces", "Workspace")
        user_model = get_user_model()

        for forbidden in ("owner", "owner_id"):
            with self.subTest(forbidden_field=forbidden):
                self.assertNotIn(
                    forbidden,
                    {field.name for field in workspace_model._meta.concrete_fields},
                    f"Forbidden field '{forbidden}' must not be a concrete field on Workspace.",
                )
                self.assertFalse(
                    hasattr(workspace_model, forbidden),
                    f"Forbidden attribute '{forbidden}' must not exist on Workspace class.",
                )

        for field in workspace_model._meta.concrete_fields:
            with self.subTest(field_name=field.name):
                related_model = getattr(field, "related_model", None)
                self.assertNotEqual(
                    related_model,
                    user_model,
                    f"Workspace.{field.name} must not relate to the User model.",
                )

    def test_client_profile_and_coach_profile_have_no_workspace_scoping_fields(self):
        """Guards the rule that profiles are global identity, never workspace-scoped."""
        client_profile_model = apps.get_model("accounts", "ClientProfile")
        coach_profile_model = apps.get_model("accounts", "CoachProfile")

        forbidden_fields = {"workspace", "workspace_id"}
        for model in (client_profile_model, coach_profile_model):
            model_name = model._meta.object_name
            all_meta_field_names = {field.name for field in model._meta.get_fields()}
            concrete_field_names = {field.name for field in model._meta.concrete_fields}

            for forbidden in forbidden_fields:
                with self.subTest(model=model_name, forbidden_field=forbidden):
                    self.assertNotIn(
                        forbidden,
                        concrete_field_names,
                        f"'{forbidden}' must not be a concrete field on {model_name}.",
                    )
                    self.assertNotIn(
                        forbidden,
                        all_meta_field_names,
                        f"'{forbidden}' must not exist in {model_name}._meta.get_fields().",
                    )
                    self.assertFalse(
                        hasattr(model, forbidden),
                        f"Forbidden attribute '{forbidden}' must not exist on {model_name}.",
                    )
