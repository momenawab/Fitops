"""Tests for the CoachProfile model (Story 2.2).

Validates the CoachProfile field contract, relationship to User, FileField typing,
one-to-one enforcement, cascade deletion, optional fields, and timestamp behavior.
"""

import time
from datetime import datetime

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import IntegrityError, models, transaction
from django.test import SimpleTestCase, TestCase


class CoachProfileFieldContractTests(SimpleTestCase):
    """Verifies schema specification, field types, relationship attributes, and column names."""

    def test_exact_concrete_field_set(self):
        expected_fields = {
            "id",
            "user",
            "bio",
            "profile_image",
            "website_url",
            "instagram_url",
            "created_at",
            "updated_at",
        }
        coach_profile_model = apps.get_model("accounts", "CoachProfile")
        concrete_fields = {field.name for field in coach_profile_model._meta.concrete_fields}
        self.assertSetEqual(concrete_fields, expected_fields)

    def test_id_field_is_uuid_primary_key(self):
        id_field = apps.get_model("accounts", "CoachProfile")._meta.get_field("id")
        self.assertTrue(id_field.primary_key)
        self.assertEqual(id_field.get_internal_type(), "UUIDField")

    def test_profile_image_is_file_field_and_not_image_field(self):
        field = apps.get_model("accounts", "CoachProfile")._meta.get_field("profile_image")
        self.assertEqual(field.get_internal_type(), "FileField")

    def test_user_field_is_one_to_one_relationship(self):
        user_field = apps.get_model("accounts", "CoachProfile")._meta.get_field("user")
        self.assertEqual(user_field.get_internal_type(), "OneToOneField")
        self.assertTrue(user_field.unique)
        self.assertTrue(user_field.one_to_one)

    def test_user_field_targets_auth_user_model(self):
        user_field = apps.get_model("accounts", "CoachProfile")._meta.get_field("user")
        self.assertEqual(user_field.related_model, get_user_model())

    def test_user_field_related_name(self):
        user_field = apps.get_model("accounts", "CoachProfile")._meta.get_field("user")
        self.assertEqual(user_field.remote_field.related_name, "coach_profile")

    def test_user_field_on_delete_is_cascade(self):
        user_field = apps.get_model("accounts", "CoachProfile")._meta.get_field("user")
        self.assertEqual(user_field.remote_field.on_delete, models.CASCADE)

    def test_user_field_database_column(self):
        user_field = apps.get_model("accounts", "CoachProfile")._meta.get_field("user")
        self.assertEqual(user_field.column, "user_id")


class CoachProfileBehaviorTests(TestCase):
    """Verifies persistence, one-to-one enforcement, cascade delete, and timestamp tracking."""

    def test_create_coach_profile_persists_and_links_user(self):
        user_model = get_user_model()
        coach_profile_model = apps.get_model("accounts", "CoachProfile")
        user = user_model.objects.create_user(
            email="coach@example.com",
            password="securepassword123",
        )
        profile = coach_profile_model.objects.create(
            user=user,
            bio="Certified fitness and nutrition coach.",
            website_url="https://coach.example.com",
            instagram_url="https://instagram.com/fitcoach",
        )
        self.assertIsNotNone(profile.pk)
        self.assertEqual(profile.user, user)
        self.assertTrue(coach_profile_model.objects.filter(pk=profile.pk).exists())

    def test_reverse_accessor_on_user_returns_coach_profile(self):
        user_model = get_user_model()
        coach_profile_model = apps.get_model("accounts", "CoachProfile")
        user = user_model.objects.create_user(
            email="reverse.accessor@example.com",
            password="securepassword123",
        )
        profile = coach_profile_model.objects.create(user=user)
        self.assertEqual(user.coach_profile, profile)

        refetched_user = user_model.objects.get(pk=user.pk)
        self.assertEqual(refetched_user.coach_profile, profile)

    def test_one_to_one_uniqueness_enforced_by_database(self):
        user_model = get_user_model()
        coach_profile_model = apps.get_model("accounts", "CoachProfile")
        user = user_model.objects.create_user(
            email="duplicate.profile@example.com",
            password="securepassword123",
        )
        coach_profile_model.objects.create(user=user)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                coach_profile_model.objects.create(user=user)

    def test_multiple_users_can_each_have_distinct_coach_profiles(self):
        user_model = get_user_model()
        coach_profile_model = apps.get_model("accounts", "CoachProfile")
        user_1 = user_model.objects.create_user(
            email="coach1@example.com",
            password="securepassword123",
        )
        user_2 = user_model.objects.create_user(
            email="coach2@example.com",
            password="securepassword123",
        )
        profile_1 = coach_profile_model.objects.create(user=user_1)
        profile_2 = coach_profile_model.objects.create(user=user_2)

        self.assertNotEqual(profile_1.pk, profile_2.pk)
        self.assertEqual(user_1.coach_profile, profile_1)
        self.assertEqual(user_2.coach_profile, profile_2)

    def test_cascade_delete_user_deletes_coach_profile(self):
        user_model = get_user_model()
        coach_profile_model = apps.get_model("accounts", "CoachProfile")
        user = user_model.objects.create_user(
            email="cascade.delete@example.com",
            password="securepassword123",
        )
        profile = coach_profile_model.objects.create(user=user)
        profile_pk = profile.pk

        user.delete()

        self.assertFalse(coach_profile_model.objects.filter(pk=profile_pk).exists())

    def test_timestamps_set_automatically_on_creation(self):
        user_model = get_user_model()
        coach_profile_model = apps.get_model("accounts", "CoachProfile")
        user = user_model.objects.create_user(
            email="timestamps@example.com",
            password="securepassword123",
        )
        profile = coach_profile_model.objects.create(user=user)

        self.assertIsNotNone(profile.created_at)
        self.assertIsNotNone(profile.updated_at)
        self.assertIsInstance(profile.created_at, datetime)
        self.assertIsInstance(profile.updated_at, datetime)

    def test_updated_at_changes_on_save_while_created_at_is_preserved(self):
        user_model = get_user_model()
        coach_profile_model = apps.get_model("accounts", "CoachProfile")
        user = user_model.objects.create_user(
            email="save.timestamps@example.com",
            password="securepassword123",
        )
        profile = coach_profile_model.objects.create(user=user, bio="Initial bio")
        initial_created_at = profile.created_at
        initial_updated_at = profile.updated_at

        time.sleep(0.01)
        profile.bio = "Updated bio after second save"
        profile.save()
        profile.refresh_from_db()

        self.assertEqual(profile.created_at, initial_created_at)
        self.assertGreater(profile.updated_at, initial_updated_at)

    def test_optional_fields_can_be_omitted_at_creation(self):
        user_model = get_user_model()
        coach_profile_model = apps.get_model("accounts", "CoachProfile")
        user = user_model.objects.create_user(
            email="minimal.coach@example.com",
            password="securepassword123",
        )
        profile = coach_profile_model.objects.create(user=user)

        self.assertIsNotNone(profile.pk)
        self.assertFalse(profile.bio)
        self.assertFalse(profile.profile_image)
        self.assertFalse(profile.website_url)
        self.assertFalse(profile.instagram_url)
