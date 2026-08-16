"""API tests for Coach Registration (Story 2.4 / Task B).

Validates route routing, public access override of DEFAULT_PERMISSION_CLASSES,
exact 201 response contract, User model creation, password hashing and non-leakage,
anti-enumeration for duplicate registrations, standard validation error envelope (§2),
transaction on-commit email dispatch, and architecture constraints.
"""

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

REGISTER_URL = "/api/v1/auth/register"


class RegistrationRouteAndAccessTests(TestCase):
    """Verifies HTTP routing, allowed methods, and unauthenticated public access."""

    def setUp(self):
        self.client = APIClient()

    def test_registration_endpoint_accepts_post_on_literal_route(self):
        """Asserts POST to literal '/api/v1/auth/register' succeeds with 201."""
        response = self.client.post(
            REGISTER_URL,
            {
                "email": "route.test@example.com",
                "password": "SecurePassword123!",
                "first_name": "Route",
                "last_name": "Tester",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_unauthenticated_client_allowed_despite_global_is_authenticated_permission(self):
        """Guards trap: DEFAULT_PERMISSION_CLASSES is IsAuthenticated, so public access must work.

        The global setting requires authentication by default. This test explicitly
        verifies that an anonymous, unauthenticated client is NOT rejected with 401
        or 403 when calling the registration endpoint.
        """
        self.client.logout()
        response = self.client.post(
            REGISTER_URL,
            {
                "email": "public.access@example.com",
                "password": "SecurePassword123!",
                "first_name": "Public",
                "last_name": "User",
            },
            format="json",
        )
        self.assertNotIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
            "Unauthenticated request must not be rejected with 401 Unauthorized or 403 Forbidden.",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_disallowed_http_methods_return_405_method_not_allowed(self):
        """Asserts non-POST HTTP methods (GET, PUT, PATCH, DELETE) are rejected with 405."""
        disallowed_methods = ["get", "put", "patch", "delete"]
        for method in disallowed_methods:
            with self.subTest(http_method=method):
                client_method = getattr(self.client, method)
                response = client_method(REGISTER_URL)
                self.assertEqual(
                    response.status_code,
                    status.HTTP_405_METHOD_NOT_ALLOWED,
                    f"HTTP {method.upper()} to {REGISTER_URL} should return "
                    "405 Method Not Allowed.",
                )


class RegistrationSuccessContractTests(TestCase):
    """Verifies the exact 201 response dictionary contract and User model persistence."""

    def setUp(self):
        self.client = APIClient()

    def test_valid_registration_returns_201_with_exact_response_body(self):
        """Asserts response status is 201 and JSON payload matches the exact contract dictionary."""
        payload = {
            "email": "coach.contract@example.com",
            "password": "StrongPassword123!",
            "first_name": "John",
            "last_name": "Doe",
        }
        response = self.client.post(REGISTER_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.json(),
            {
                "message": "Account created. Please verify your email.",
                "requires_email_verification": True,
            },
            "Response body must match the exact contract dictionary with no extra or missing keys.",
        )

    def test_valid_registration_creates_user_with_submitted_attributes(self):
        """Asserts a User instance is created in the database with matching email and names."""
        payload = {
            "email": "persisted.coach@example.com",
            "password": "StrongPassword123!",
            "first_name": "Jane",
            "last_name": "Smith",
        }
        response = self.client.post(REGISTER_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        user_model = get_user_model()
        user = user_model.objects.filter(email="persisted.coach@example.com").first()
        self.assertIsNotNone(user, "User record should exist in database after registration.")
        self.assertEqual(user.email, "persisted.coach@example.com")
        self.assertEqual(user.first_name, "Jane")
        self.assertEqual(user.last_name, "Smith")

    def test_created_user_default_flags_and_unverified_email_timestamp(self):
        """Asserts newly registered user has active status, default role, and unverified email."""
        payload = {
            "email": "defaults.coach@example.com",
            "password": "StrongPassword123!",
            "first_name": "Default",
            "last_name": "Coach",
        }
        response = self.client.post(REGISTER_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        user = get_user_model().objects.get(email="defaults.coach@example.com")
        self.assertTrue(user.is_active)
        self.assertEqual(user.platform_role, "NONE")
        self.assertIsNone(user.email_verified_at)


class RegistrationPasswordSecurityTests(TestCase):
    """Verifies secure password hashing and strict non-leakage in responses."""

    def setUp(self):
        self.client = APIClient()

    def test_password_is_securely_hashed_and_not_stored_as_raw_text(self):
        """Asserts user password in DB is hashed and check_password succeeds."""
        raw_password = "SuperSecretPassword123!"
        payload = {
            "email": "hashed.coach@example.com",
            "password": raw_password,
            "first_name": "Hash",
            "last_name": "Check",
        }
        response = self.client.post(REGISTER_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        user = get_user_model().objects.get(email="hashed.coach@example.com")
        self.assertNotEqual(user.password, raw_password)
        self.assertTrue(user.check_password(raw_password))
        self.assertFalse(user.check_password("WrongPassword123!"))

    def test_response_content_does_not_leak_raw_password_or_password_hash(self):
        """Asserts raw password and password hash are absent from serialized response content."""
        raw_password = "PlainTextPasswordToProtect123!"
        payload = {
            "email": "leak.prevention@example.com",
            "password": raw_password,
            "first_name": "No",
            "last_name": "Leak",
        }
        response = self.client.post(REGISTER_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        user = get_user_model().objects.get(email="leak.prevention@example.com")
        raw_content = response.content.decode()
        self.assertNotIn(raw_password, raw_content)
        self.assertNotIn(user.password, raw_content)


class RegistrationAntiEnumerationTests(TestCase):
    """Verifies generic anti-enumeration response when registering an already-existing email."""

    def setUp(self):
        self.client = APIClient()
        self.existing_user = get_user_model().objects.create_user(
            email="existing.coach@example.com",
            password="OriginalPassword123!",
            first_name="Original",
            last_name="Owner",
        )

    def test_duplicate_email_registration_returns_identical_201_created_response(self):
        """Asserts registering an existing email returns identical 201 status and body."""
        payload = {
            "email": "existing.coach@example.com",
            "password": "AttackerAttempt456!",
            "first_name": "Impostor",
            "last_name": "User",
        }
        response = self.client.post(REGISTER_URL, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(
            response.json(),
            {
                "message": "Account created. Please verify your email.",
                "requires_email_verification": True,
            },
            "Duplicate email registration must return identical response body "
            "to prevent enumeration.",
        )

    def test_duplicate_email_does_not_create_second_user_or_modify_existing_password(self):
        """Asserts User count for the email remains 1 and existing user data is untouched."""
        initial_user_count = get_user_model().objects.count()
        payload = {
            "email": "existing.coach@example.com",
            "password": "AttackerAttempt456!",
            "first_name": "Impostor",
            "last_name": "User",
        }
        response = self.client.post(REGISTER_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        user_model = get_user_model()
        self.assertEqual(user_model.objects.count(), initial_user_count)
        self.assertEqual(
            user_model.objects.filter(email="existing.coach@example.com").count(),
            1,
        )

        refetched_user = user_model.objects.get(email="existing.coach@example.com")
        self.assertEqual(refetched_user.first_name, "Original")
        self.assertEqual(refetched_user.last_name, "Owner")
        self.assertTrue(refetched_user.check_password("OriginalPassword123!"))
        self.assertFalse(refetched_user.check_password("AttackerAttempt456!"))


class RegistrationValidationEnvelopeTests(TestCase):
    """Verifies §2 Standard Error Format and validation error handling."""

    def setUp(self):
        self.client = APIClient()

    def assert_validation_error_envelope(self, response, expected_field=None):
        """Helper to assert the standard §2 error envelope structure."""
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertEqual(
            set(data.keys()),
            {"error"},
            "Response top-level key must be exactly 'error'.",
        )
        error = data["error"]
        self.assertIsInstance(error, dict)
        self.assertEqual(error.get("code"), "VALIDATION_ERROR")
        self.assertIsInstance(
            error.get("message"),
            str,
            "Error 'message' must be a string, not a list or dict.",
        )
        self.assertIsInstance(
            error.get("fields"),
            dict,
            "Error 'fields' must be a dictionary.",
        )
        if expected_field:
            self.assertIn(
                expected_field,
                error["fields"],
                f"Expected field '{expected_field}' to be present in error fields dictionary.",
            )
            self.assertIsInstance(
                error["fields"][expected_field],
                list,
                f"Field errors for '{expected_field}' must be a list.",
            )

    def test_invalid_email_format_returns_400_with_validation_error_envelope(self):
        """Asserts invalid email format produces 400 Bad Request with VALIDATION_ERROR code."""
        payload = {
            "email": "not-a-valid-email-address",
            "password": "StrongPassword123!",
            "first_name": "Invalid",
            "last_name": "Email",
        }
        response = self.client.post(REGISTER_URL, payload, format="json")
        self.assert_validation_error_envelope(response, expected_field="email")

    def test_weak_password_returns_400_with_validation_error_envelope(self):
        """Asserts weak passwords failing validator rules produce 400 with VALIDATION_ERROR code."""
        weak_passwords = ["short", "12345678", "password", "abc"]
        for weak_pw in weak_passwords:
            with self.subTest(password=weak_pw):
                payload = {
                    "email": f"pw.test.{weak_pw}@example.com",
                    "password": weak_pw,
                    "first_name": "Weak",
                    "last_name": "Password",
                }
                response = self.client.post(REGISTER_URL, payload, format="json")
                self.assert_validation_error_envelope(response, expected_field="password")

    def test_missing_required_fields_return_400_with_validation_error_envelope(self):
        """Asserts omitting any required field returns 400 with VALIDATION_ERROR."""
        required_fields = ["email", "password", "first_name", "last_name"]
        base_payload = {
            "email": "complete.fields@example.com",
            "password": "StrongPassword123!",
            "first_name": "Complete",
            "last_name": "Fields",
        }
        for field in required_fields:
            with self.subTest(missing_field=field):
                payload = base_payload.copy()
                payload.pop(field)
                response = self.client.post(REGISTER_URL, payload, format="json")
                self.assert_validation_error_envelope(response, expected_field=field)

    def test_empty_payload_returns_400_with_validation_error_envelope(self):
        """Asserts sending an empty JSON payload returns 400 with VALIDATION_ERROR."""
        response = self.client.post(REGISTER_URL, {}, format="json")
        self.assert_validation_error_envelope(response)


class RegistrationEmailDispatchTests(TestCase):
    """Verifies transaction on-commit email dispatch behavior and privacy."""

    def setUp(self):
        self.client = APIClient()

    def test_successful_registration_dispatches_single_email_on_commit(self):
        """Asserts executing on-commit callbacks dispatches exactly one verification email."""
        payload = {
            "email": "mail.target@example.com",
            "password": "StrongPassword123!",
            "first_name": "Mail",
            "last_name": "Recipient",
        }
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(REGISTER_URL, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            len(mail.outbox),
            1,
            "Exactly one verification email should be dispatched on transaction commit.",
        )
        self.assertEqual(mail.outbox[0].to, ["mail.target@example.com"])

    def test_verification_email_is_not_dispatched_without_transaction_commit(self):
        """Guards against premature inline email sending prior to transaction commit."""
        payload = {
            "email": "deferred.mail@example.com",
            "password": "StrongPassword123!",
            "first_name": "Deferred",
            "last_name": "Mail",
        }
        response = self.client.post(REGISTER_URL, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            len(mail.outbox),
            0,
            "No email should be dispatched before transaction commit (must use on_commit).",
        )

    def test_outbound_verification_email_does_not_leak_user_password(self):
        """Asserts user's raw password does not appear in the verification email subject or body."""
        raw_password = "ConfidentialPasswordToProtect123!"
        payload = {
            "email": "privacy.check@example.com",
            "password": raw_password,
            "first_name": "Privacy",
            "last_name": "User",
        }
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(REGISTER_URL, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        self.assertNotIn(raw_password, sent_email.body)
        self.assertNotIn(raw_password, sent_email.subject)


class RegistrationArchitectureGuardTests(TestCase):
    """Verifies architectural constraints: no CoachProfile, exact accounts models."""

    def setUp(self):
        self.client = APIClient()

    def test_registration_does_not_create_coach_profile(self):
        """Asserts registration creates User only, and CoachProfile count remains zero."""
        coach_profile_model = apps.get_model("accounts", "CoachProfile")
        self.assertEqual(coach_profile_model.objects.count(), 0)

        payload = {
            "email": "no.profile@example.com",
            "password": "StrongPassword123!",
            "first_name": "No",
            "last_name": "Profile",
        }
        response = self.client.post(REGISTER_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertEqual(
            coach_profile_model.objects.count(),
            0,
            "Registration must NOT create a CoachProfile; it is created during onboarding.",
        )

    def test_accounts_app_exposes_only_approved_models_and_no_token_model(self):
        """Asserts accounts defines exactly {User, CoachProfile, ClientProfile}, no token model."""
        accounts_app = apps.get_app_config("accounts")
        concrete_model_names = {model._meta.object_name for model in accounts_app.get_models()}
        expected_model_names = {"User", "CoachProfile", "ClientProfile"}
        self.assertSetEqual(
            concrete_model_names,
            expected_model_names,
            "accounts must contain only User, CoachProfile, ClientProfile (no token model).",
        )
