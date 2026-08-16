"""Tests for the custom User model (Story 2.1).

Validates the AUTH_USER_MODEL wiring, exact field contract, absence of
PermissionsMixin/is_staff fields, and user manager creation/password hashing behavior.
"""

from datetime import datetime

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import identify_hasher
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase


class UserModelWiringTests(SimpleTestCase):
    """Verifies settings wiring and user model resolution."""

    def test_auth_user_model_setting(self):
        self.assertEqual(settings.AUTH_USER_MODEL, "accounts.User")

    def test_get_user_model_returns_custom_user(self):
        user_model = get_user_model()
        self.assertEqual(user_model._meta.label, "accounts.User")

    def test_username_and_required_fields(self):
        user_model = get_user_model()
        self.assertEqual(user_model.USERNAME_FIELD, "email")
        self.assertEqual(user_model.REQUIRED_FIELDS, [])


class UserModelFieldContractTests(SimpleTestCase):
    """Verifies schema specification, field types, choices, and absence of forbidden fields."""

    def test_exact_concrete_field_set(self):
        expected_fields = {
            "id",
            "password",
            "last_login",
            "email",
            "first_name",
            "last_name",
            "phone",
            "is_active",
            "email_verified_at",
            "platform_role",
            "created_at",
            "updated_at",
        }
        concrete_fields = {field.name for field in get_user_model()._meta.concrete_fields}
        self.assertSetEqual(concrete_fields, expected_fields)

    def test_forbidden_auth_fields_absent(self):
        user_model = get_user_model()
        forbidden_fields = ["is_staff", "is_superuser", "groups", "user_permissions"]
        all_meta_field_names = {field.name for field in user_model._meta.get_fields()}

        for field_name in forbidden_fields:
            with self.subTest(field=field_name):
                self.assertFalse(
                    hasattr(user_model, field_name),
                    f"Forbidden field '{field_name}' must not exist on the User model.",
                )
                self.assertNotIn(
                    field_name,
                    all_meta_field_names,
                    f"Forbidden field '{field_name}' must not be present in model _meta fields.",
                )

    def test_id_field_is_uuid_primary_key(self):
        id_field = get_user_model()._meta.get_field("id")
        self.assertTrue(id_field.primary_key)
        self.assertEqual(id_field.get_internal_type(), "UUIDField")

    def test_email_field_is_unique(self):
        email_field = get_user_model()._meta.get_field("email")
        self.assertTrue(email_field.unique)

    def test_email_verified_at_is_nullable(self):
        verified_field = get_user_model()._meta.get_field("email_verified_at")
        self.assertTrue(verified_field.null)

    def test_platform_role_choices_and_default(self):
        role_field = get_user_model()._meta.get_field("platform_role")
        stored_choices = {choice[0] for choice in role_field.choices}
        self.assertSetEqual(stored_choices, {"NONE", "ADMIN"})
        self.assertEqual(role_field.default, "NONE")

    def test_is_active_default_is_true(self):
        is_active_field = get_user_model()._meta.get_field("is_active")
        self.assertTrue(is_active_field.default)


class UserModelBehaviorTests(TestCase):
    """Verifies model persistence, manager creation logic, hashing, and database constraints."""

    def test_create_user_persists_and_checks_password(self):
        user_model = get_user_model()
        user = user_model.objects.create_user(
            email="coach@example.com",
            password="securepassword123",
        )
        self.assertIsNotNone(user.pk)
        self.assertTrue(user_model.objects.filter(pk=user.pk).exists())
        self.assertTrue(user.check_password("securepassword123"))
        self.assertFalse(user.check_password("wrongpassword"))

    def test_password_is_securely_hashed(self):
        raw_password = "plain-text-password-456"
        user_model = get_user_model()
        user = user_model.objects.create_user(
            email="user.hashed@example.com",
            password=raw_password,
        )
        self.assertNotEqual(user.password, raw_password)
        self.assertIn("$", user.password)
        hasher = identify_hasher(user.password)
        self.assertIsNotNone(hasher)
        self.assertTrue(user.check_password(raw_password))

    def test_email_uniqueness_enforced_by_database(self):
        user_model = get_user_model()
        user_model.objects.create_user(
            email="duplicate@example.com",
            password="password123",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                user_model.objects.create_user(
                    email="duplicate@example.com",
                    password="differentpassword456",
                )

    def test_create_user_without_email_raises_value_error(self):
        user_model = get_user_model()
        with self.assertRaises(ValueError):
            user_model.objects.create_user(email="", password="password123")
        with self.assertRaises(ValueError):
            user_model.objects.create_user(email=None, password="password123")

    def test_created_user_default_field_values(self):
        user_model = get_user_model()
        user = user_model.objects.create_user(
            email="defaults@example.com",
            password="password123",
        )
        self.assertIs(user.is_active, True)
        self.assertEqual(user.platform_role, "NONE")
        self.assertIsNone(user.email_verified_at)

    def test_timestamps_set_automatically_on_creation(self):
        user_model = get_user_model()
        user = user_model.objects.create_user(
            email="timestamps@example.com",
            password="password123",
        )
        self.assertIsNotNone(user.created_at)
        self.assertIsNotNone(user.updated_at)
        self.assertIsInstance(user.created_at, datetime)
        self.assertIsInstance(user.updated_at, datetime)
