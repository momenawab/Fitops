"""Tests for the Workspace model schema contract and behavior (Story 3.1 / Task B).

Validates:
- Exact concrete field set specification (13 fields, set equality)
- Architectural absence of owner / owner_id field and relations to AUTH_USER_MODEL
- UUID primary key typing and uniqueness
- Platform-wide slug uniqueness enforcement (IntegrityError)
- FileField typing for logo and profile_image (Pillow-free)
- Status choices ({"ACTIVE", "SUSPENDED"}) and default ("ACTIVE")
- Workspace creation with minimal required fields and optional field omission
- String representation containing workspace name
- Auto-managed timestamp behavior (created_at preserved, updated_at advanced on save)
- Architecture guards: workspaces model set is exactly the approved one, accounts unchanged
"""

import time
import uuid
from datetime import datetime

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

EXPECTED_WORKSPACE_FIELDS = {
    "id",
    "name",
    "slug",
    "logo",
    "profile_image",
    "description",
    "brand_color",
    "currency",
    "timezone",
    "whatsapp_number",
    "status",
    "created_at",
    "updated_at",
}


class BaseWorkspaceTestCase(TestCase):
    """Base test case providing model resolution and workspace creation helpers."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.workspace_model = apps.get_model("workspaces", "Workspace")

    def _create_workspace(self, **kwargs):
        """Helper to create a Workspace instance with default required attributes."""
        defaults = {
            "name": "Apex Performance Coaching",
            "slug": f"apex-performance-{uuid.uuid4().hex[:8]}",
            "currency": "USD",
            "timezone": "UTC",
        }
        defaults.update(kwargs)
        return self.workspace_model.objects.create(**defaults)


class WorkspaceSchemaContractTests(BaseWorkspaceTestCase):
    """Verifies schema specification, field typing, choices, and absence of forbidden fields."""

    def test_exact_concrete_field_set(self):
        """Asserts Workspace defines exactly the thirteen approved concrete fields."""
        concrete_fields = {field.name for field in self.workspace_model._meta.concrete_fields}
        self.assertSetEqual(
            concrete_fields,
            EXPECTED_WORKSPACE_FIELDS,
            "Workspace concrete fields must exactly match the authoritative schema contract.",
        )

    def test_no_owner_or_owner_id_field_exists_on_workspace(self):
        """Guards architectural rule: ownership is managed via Membership, not on Workspace.

        Asserts that neither 'owner' nor 'owner_id' exists as a field, property,
        or column on the Workspace model.
        """
        all_meta_field_names = {field.name for field in self.workspace_model._meta.get_fields()}
        concrete_field_names = {field.name for field in self.workspace_model._meta.concrete_fields}

        for forbidden in ("owner", "owner_id"):
            with self.subTest(forbidden_field=forbidden):
                self.assertNotIn(
                    forbidden,
                    concrete_field_names,
                    f"Forbidden field '{forbidden}' must not be a concrete field on Workspace.",
                )
                self.assertNotIn(
                    forbidden,
                    all_meta_field_names,
                    f"Forbidden field '{forbidden}' must not exist in _meta.get_fields().",
                )
                self.assertFalse(
                    hasattr(self.workspace_model, forbidden),
                    f"Forbidden attribute '{forbidden}' must not exist on Workspace class.",
                )

    def test_id_field_is_uuid_primary_key(self):
        """Asserts the id field is configured as a UUID primary key."""
        id_field = self.workspace_model._meta.get_field("id")
        self.assertTrue(id_field.primary_key, "Workspace.id must be a primary key.")
        self.assertEqual(
            id_field.get_internal_type(),
            "UUIDField",
            "Workspace.id must be a UUIDField.",
        )

    def test_slug_field_is_marked_unique(self):
        """Asserts the slug field is defined with unique=True."""
        slug_field = self.workspace_model._meta.get_field("slug")
        self.assertTrue(slug_field.unique, "Workspace.slug must have unique=True.")

    def test_logo_is_file_field_and_not_image_field(self):
        """Asserts logo uses FileField so Pillow is not required as a dependency."""
        logo_field = self.workspace_model._meta.get_field("logo")
        self.assertEqual(
            logo_field.get_internal_type(),
            "FileField",
            "Workspace.logo must report internal type 'FileField', never 'ImageField'.",
        )

    def test_profile_image_is_file_field_and_not_image_field(self):
        """Asserts profile_image uses FileField so Pillow is not required as a dependency."""
        profile_image_field = self.workspace_model._meta.get_field("profile_image")
        self.assertEqual(
            profile_image_field.get_internal_type(),
            "FileField",
            "Workspace.profile_image must report internal type 'FileField', never 'ImageField'.",
        )

    def test_status_choices_and_default_value(self):
        """Asserts status choices are exactly ACTIVE and SUSPENDED, defaulting to ACTIVE."""
        status_field = self.workspace_model._meta.get_field("status")
        stored_choices = {
            choice[0] if isinstance(choice, (list, tuple)) else choice
            for choice in status_field.choices
        }
        self.assertSetEqual(
            stored_choices,
            {"ACTIVE", "SUSPENDED"},
            "Workspace.status choices must be exactly {'ACTIVE', 'SUSPENDED'}.",
        )
        self.assertEqual(
            status_field.default,
            "ACTIVE",
            "Workspace.status field must default to 'ACTIVE'.",
        )


class WorkspaceBehaviorTests(BaseWorkspaceTestCase):
    """Verifies persistence, uniqueness constraints, optional field omission, and timestamps."""

    def test_create_workspace_with_minimal_required_fields_defaults_to_active(self):
        """Asserts a Workspace can be created with required fields and defaults to ACTIVE."""
        workspace = self._create_workspace(
            name="Iron Core Fitness",
            slug="iron-core-fitness",
        )
        self.assertIsNotNone(workspace.pk)
        self.assertEqual(workspace.status, "ACTIVE")
        self.assertTrue(self.workspace_model.objects.filter(pk=workspace.pk).exists())

    def test_two_saved_workspaces_receive_distinct_uuid_primary_keys(self):
        """Asserts each newly created Workspace is assigned a distinct UUID primary key."""
        workspace_1 = self._create_workspace(
            name="Alpha Coaching",
            slug="alpha-coaching",
        )
        workspace_2 = self._create_workspace(
            name="Beta Coaching",
            slug="beta-coaching",
        )
        self.assertNotEqual(workspace_1.id, workspace_2.id)
        self.assertIsInstance(workspace_1.id, uuid.UUID)
        self.assertIsInstance(workspace_2.id, uuid.UUID)

    def test_slug_uniqueness_enforced_by_database(self):
        """Asserts creating a second Workspace with an existing slug raises IntegrityError."""
        self._create_workspace(
            name="Original Fitness Hub",
            slug="duplicate-slug-check",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._create_workspace(
                    name="Imposter Fitness Hub",
                    slug="duplicate-slug-check",
                )

    def test_optional_fields_can_be_omitted_at_creation(self):
        """Asserts optional fields can be omitted during Workspace creation."""
        workspace = self._create_workspace(
            name="Minimalist Athletics",
            slug="minimalist-athletics",
        )
        self.assertIsNotNone(workspace.pk)
        self.assertTrue(self.workspace_model.objects.filter(pk=workspace.pk).exists())
        self.assertFalse(workspace.description)
        self.assertFalse(workspace.brand_color)
        self.assertFalse(workspace.whatsapp_number)
        self.assertFalse(workspace.logo)
        self.assertFalse(workspace.profile_image)

    def test_str_representation_contains_workspace_name(self):
        """Asserts str(workspace) returns a non-empty string containing the workspace name."""
        workspace_name = "Hypertrophy Headquarters"
        workspace = self._create_workspace(
            name=workspace_name,
            slug="hypertrophy-headquarters",
        )
        str_repr = str(workspace)
        self.assertTrue(bool(str_repr), "str(workspace) must return a non-empty string.")
        self.assertIn(
            workspace_name,
            str_repr,
            f"str(workspace) must contain the workspace name '{workspace_name}'.",
        )

    def test_timestamps_set_automatically_on_creation(self):
        """Asserts created_at and updated_at are automatically populated datetime instances."""
        workspace = self._create_workspace(
            name="Timestamp Verification Gym",
            slug="timestamp-verification-gym",
        )
        self.assertIsNotNone(workspace.created_at)
        self.assertIsNotNone(workspace.updated_at)
        self.assertIsInstance(workspace.created_at, datetime)
        self.assertIsInstance(workspace.updated_at, datetime)

    def test_updated_at_advances_on_save_while_created_at_is_preserved(self):
        """Asserts saving changes advances updated_at while created_at remains unchanged."""
        workspace = self._create_workspace(
            name="Evolution Athletics",
            slug="evolution-athletics",
            description="Initial description",
        )
        initial_created_at = workspace.created_at
        initial_updated_at = workspace.updated_at

        time.sleep(0.01)
        workspace.description = "Updated description after modification"
        workspace.save()
        workspace.refresh_from_db()

        self.assertEqual(
            workspace.created_at,
            initial_created_at,
            "created_at must remain constant across subsequent saves.",
        )
        self.assertGreater(
            workspace.updated_at,
            initial_updated_at,
            "updated_at must advance on subsequent saves.",
        )

    def test_status_can_be_explicitly_set_to_suspended(self):
        """Asserts a Workspace can be created with or transitioned to SUSPENDED status."""
        workspace = self._create_workspace(
            name="Suspended Athletics",
            slug="suspended-athletics",
            status="SUSPENDED",
        )
        workspace.refresh_from_db()
        self.assertEqual(workspace.status, "SUSPENDED")


class WorkspaceArchitectureGuardTests(TestCase):
    """Verifies architectural boundaries across workspaces and accounts apps."""

    def test_workspaces_app_exposes_only_workspace_model(self):
        """Asserts workspaces defines exactly {Workspace}, guarding against premature models.

        Guards that Membership, WorkspaceArchive, PaymentMethod, and CheckInSchedule
        were not created prematurely before their respective Stories.
        """
        workspaces_app = apps.get_app_config("workspaces")
        concrete_model_names = {model._meta.object_name for model in workspaces_app.get_models()}
        self.assertSetEqual(
            concrete_model_names,
            {"Workspace", "PaymentMethod"},
            "workspaces app must expose only the 'Workspace' model in Story 3.1.",
        )

    def test_accounts_app_still_exposes_exactly_approved_models(self):
        """Asserts accounts app remains untouched and exposes only its approved four models."""
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
            "accounts app models must remain exactly approved model set.",
        )

    def test_workspace_has_no_relation_field_pointing_to_user_model(self):
        """Asserts Workspace has no ForeignKey, OneToOne, or relation to AUTH_USER_MODEL.

        This is the strongest architectural guard ensuring ownership and user ties
        are decoupled from the Workspace model and deferred to the Membership model.
        """
        workspace_model = apps.get_model("workspaces", "Workspace")
        user_model = get_user_model()

        for field in workspace_model._meta.get_fields():
            with self.subTest(field_name=field.name):
                related_model = getattr(field, "related_model", None)
                self.assertNotEqual(
                    related_model,
                    user_model,
                    f"Workspace.{field.name} must not relate to the User model ({user_model}).",
                )
                if hasattr(field, "remote_field") and field.remote_field:
                    self.assertNotEqual(
                        field.remote_field.model,
                        user_model,
                        f"Workspace.{field.name}.remote_field must not target User model.",
                    )
