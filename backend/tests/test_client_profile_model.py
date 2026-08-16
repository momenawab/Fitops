"""Tests for the ClientProfile model (Story 2.3).

Validates the ClientProfile field contract, absence of workspace scoping, relationship
to User, DecimalField/DateField typing, one-to-one enforcement, cascade deletion,
coexistence with CoachProfile, optional fields, decimal round-trips, and timestamp behavior.
"""

import time
from datetime import date, datetime
from decimal import Decimal

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import IntegrityError, models, transaction
from django.test import SimpleTestCase, TestCase


class ClientProfileFieldContractTests(SimpleTestCase):
    """Verifies schema specification, field types, relationship attributes, and column names."""

    def test_exact_concrete_field_set(self):
        expected_fields = {
            "id",
            "user",
            "date_of_birth",
            "gender",
            "height",
            "current_weight",
            "goal",
            "training_experience",
            "notes",
            "created_at",
            "updated_at",
        }
        client_profile_model = apps.get_model("accounts", "ClientProfile")
        concrete_fields = {field.name for field in client_profile_model._meta.concrete_fields}
        self.assertSetEqual(concrete_fields, expected_fields)

    def test_client_profile_has_no_workspace_scoping_fields_or_columns(self):
        """Guards architectural rule: ClientProfile is global and MUST NOT contain workspace_id.

        Client identity is global and is not owned by a single Workspace. Workspace
        relationships are represented exclusively through Membership. This test strictly
        verifies that no workspace-scoping fields, relations, or database columns exist
        on ClientProfile.
        """
        client_profile_model = apps.get_model("accounts", "ClientProfile")
        forbidden_terms = {"workspace_id", "workspace", "membership", "membership_id"}

        all_meta_field_names = {field.name for field in client_profile_model._meta.get_fields()}
        for term in forbidden_terms:
            with self.subTest(forbidden_field=term):
                self.assertNotIn(
                    term,
                    all_meta_field_names,
                    f"Forbidden workspace-scoping field '{term}' must not exist on ClientProfile.",
                )
                self.assertFalse(
                    hasattr(client_profile_model, term),
                    f"Forbidden attribute '{term}' must not exist on ClientProfile.",
                )

        all_column_names = {
            field.column
            for field in client_profile_model._meta.concrete_fields
            if hasattr(field, "column") and field.column
        }
        for term in forbidden_terms:
            with self.subTest(forbidden_column=term):
                self.assertNotIn(
                    term,
                    all_column_names,
                    f"Forbidden database column '{term}' must not exist on ClientProfile.",
                )

    def test_id_field_is_uuid_primary_key(self):
        id_field = apps.get_model("accounts", "ClientProfile")._meta.get_field("id")
        self.assertTrue(id_field.primary_key)
        self.assertEqual(id_field.get_internal_type(), "UUIDField")

    def test_date_of_birth_field_is_date_field(self):
        dob_field = apps.get_model("accounts", "ClientProfile")._meta.get_field("date_of_birth")
        self.assertEqual(dob_field.get_internal_type(), "DateField")

    def test_gender_field_is_char_field_with_no_choices(self):
        gender_field = apps.get_model("accounts", "ClientProfile")._meta.get_field("gender")
        self.assertEqual(gender_field.get_internal_type(), "CharField")
        self.assertFalse(
            gender_field.choices,
            "gender field must not define choices or enums; choices must be empty or None.",
        )

    def test_height_field_is_decimal_field(self):
        height_field = apps.get_model("accounts", "ClientProfile")._meta.get_field("height")
        self.assertEqual(height_field.get_internal_type(), "DecimalField")

    def test_current_weight_field_is_decimal_field(self):
        client_profile_model = apps.get_model("accounts", "ClientProfile")
        weight_field = client_profile_model._meta.get_field("current_weight")
        self.assertEqual(weight_field.get_internal_type(), "DecimalField")

    def test_user_field_is_one_to_one_relationship(self):
        user_field = apps.get_model("accounts", "ClientProfile")._meta.get_field("user")
        self.assertEqual(user_field.get_internal_type(), "OneToOneField")
        self.assertTrue(user_field.unique)
        self.assertTrue(user_field.one_to_one)

    def test_user_field_targets_auth_user_model(self):
        user_field = apps.get_model("accounts", "ClientProfile")._meta.get_field("user")
        self.assertEqual(user_field.related_model, get_user_model())

    def test_user_field_related_name(self):
        user_field = apps.get_model("accounts", "ClientProfile")._meta.get_field("user")
        self.assertEqual(user_field.remote_field.related_name, "client_profile")

    def test_user_field_on_delete_is_cascade(self):
        user_field = apps.get_model("accounts", "ClientProfile")._meta.get_field("user")
        self.assertEqual(user_field.remote_field.on_delete, models.CASCADE)

    def test_user_field_database_column(self):
        user_field = apps.get_model("accounts", "ClientProfile")._meta.get_field("user")
        self.assertEqual(user_field.column, "user_id")


class ClientProfileBehaviorTests(TestCase):
    """Verifies persistence, 1:1 uniqueness, cascade delete, coexistence, and timestamps."""

    def test_create_client_profile_persists_and_links_user(self):
        user_model = get_user_model()
        client_profile_model = apps.get_model("accounts", "ClientProfile")
        user = user_model.objects.create_user(
            email="client@example.com",
            password="securepassword123",
        )
        profile = client_profile_model.objects.create(
            user=user,
            date_of_birth=date(1995, 6, 15),
            gender="male",
            height=Decimal("180.0"),
            current_weight=Decimal("82.5"),
            goal="Muscle gain and strength progression",
            training_experience="3 years intermediate lifting",
            notes="No current injuries or medical restrictions.",
        )
        self.assertIsNotNone(profile.pk)
        self.assertEqual(profile.user, user)
        self.assertTrue(client_profile_model.objects.filter(pk=profile.pk).exists())

    def test_reverse_accessor_on_user_returns_client_profile(self):
        user_model = get_user_model()
        client_profile_model = apps.get_model("accounts", "ClientProfile")
        user = user_model.objects.create_user(
            email="reverse.client@example.com",
            password="securepassword123",
        )
        profile = client_profile_model.objects.create(user=user)
        self.assertEqual(user.client_profile, profile)

        refetched_user = user_model.objects.get(pk=user.pk)
        self.assertEqual(refetched_user.client_profile, profile)

    def test_one_to_one_uniqueness_enforced_by_database(self):
        user_model = get_user_model()
        client_profile_model = apps.get_model("accounts", "ClientProfile")
        user = user_model.objects.create_user(
            email="duplicate.client@example.com",
            password="securepassword123",
        )
        client_profile_model.objects.create(user=user)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                client_profile_model.objects.create(user=user)

    def test_multiple_users_can_each_have_distinct_client_profiles(self):
        user_model = get_user_model()
        client_profile_model = apps.get_model("accounts", "ClientProfile")
        user_1 = user_model.objects.create_user(
            email="client1@example.com",
            password="securepassword123",
        )
        user_2 = user_model.objects.create_user(
            email="client2@example.com",
            password="securepassword123",
        )
        profile_1 = client_profile_model.objects.create(user=user_1)
        profile_2 = client_profile_model.objects.create(user=user_2)

        self.assertNotEqual(profile_1.pk, profile_2.pk)
        self.assertEqual(user_1.client_profile, profile_1)
        self.assertEqual(user_2.client_profile, profile_2)

    def test_cascade_delete_user_deletes_client_profile(self):
        user_model = get_user_model()
        client_profile_model = apps.get_model("accounts", "ClientProfile")
        user = user_model.objects.create_user(
            email="cascade.client@example.com",
            password="securepassword123",
        )
        profile = client_profile_model.objects.create(user=user)
        profile_pk = profile.pk

        user.delete()

        self.assertFalse(client_profile_model.objects.filter(pk=profile_pk).exists())

    def test_user_can_have_both_coach_profile_and_client_profile(self):
        user_model = get_user_model()
        coach_profile_model = apps.get_model("accounts", "CoachProfile")
        client_profile_model = apps.get_model("accounts", "ClientProfile")

        user = user_model.objects.create_user(
            email="dual.identity@example.com",
            password="securepassword123",
        )
        coach_profile = coach_profile_model.objects.create(
            user=user,
            bio="Coach in Workspace A",
        )
        client_profile = client_profile_model.objects.create(
            user=user,
            goal="Client in Workspace B",
        )

        self.assertEqual(user.coach_profile, coach_profile)
        self.assertEqual(user.client_profile, client_profile)

        refetched_user = user_model.objects.get(pk=user.pk)
        self.assertEqual(refetched_user.coach_profile, coach_profile)
        self.assertEqual(refetched_user.client_profile, client_profile)

    def test_timestamps_set_automatically_on_creation(self):
        user_model = get_user_model()
        client_profile_model = apps.get_model("accounts", "ClientProfile")
        user = user_model.objects.create_user(
            email="timestamps.client@example.com",
            password="securepassword123",
        )
        profile = client_profile_model.objects.create(user=user)

        self.assertIsNotNone(profile.created_at)
        self.assertIsNotNone(profile.updated_at)
        self.assertIsInstance(profile.created_at, datetime)
        self.assertIsInstance(profile.updated_at, datetime)

    def test_updated_at_changes_on_save_while_created_at_is_preserved(self):
        user_model = get_user_model()
        client_profile_model = apps.get_model("accounts", "ClientProfile")
        user = user_model.objects.create_user(
            email="save.timestamps.client@example.com",
            password="securepassword123",
        )
        profile = client_profile_model.objects.create(user=user, goal="Initial fitness goal")
        initial_created_at = profile.created_at
        initial_updated_at = profile.updated_at

        time.sleep(0.01)
        profile.goal = "Updated fitness goal after second save"
        profile.save()
        profile.refresh_from_db()

        self.assertEqual(profile.created_at, initial_created_at)
        self.assertGreater(profile.updated_at, initial_updated_at)

    def test_optional_fields_can_be_omitted_at_creation(self):
        user_model = get_user_model()
        client_profile_model = apps.get_model("accounts", "ClientProfile")
        user = user_model.objects.create_user(
            email="minimal.client@example.com",
            password="securepassword123",
        )
        profile = client_profile_model.objects.create(user=user)

        self.assertIsNotNone(profile.pk)
        self.assertTrue(client_profile_model.objects.filter(pk=profile.pk).exists())

    def test_decimal_values_round_trip_accurately(self):
        user_model = get_user_model()
        client_profile_model = apps.get_model("accounts", "ClientProfile")
        user = user_model.objects.create_user(
            email="decimal.client@example.com",
            password="securepassword123",
        )
        profile = client_profile_model.objects.create(
            user=user,
            height=Decimal("178.5"),
            current_weight=Decimal("85.5"),
        )
        profile.refresh_from_db()

        self.assertEqual(profile.height, Decimal("178.5"))
        self.assertEqual(profile.current_weight, Decimal("85.5"))
        self.assertIsInstance(profile.height, Decimal)
        self.assertIsInstance(profile.current_weight, Decimal)
