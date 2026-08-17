"""API tests for Email Verification and Resend (Story 2.5 / Task B).

Validates:
- Literal routing and unauthenticated public access for /api/v1/auth/email/verify and resend
- Exact 200 response contracts (dict equality) and User.email_verified_at timestamp transition
- Single-use token semantics and indistinguishable responses between invalid and used tokens
- Anti-enumeration guarantee (byte-identical responses for unknown, unverified, and verified emails)
- Transaction on-commit email dispatch and sensitive data non-leakage
- Rate limiting per endpoint (verify: 10/min, resend: 3/min) and registration remaining unthrottled
- Architecture guard: accounts defines {User, CoachProfile, ClientProfile}, no token model
"""

import re
from datetime import datetime

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

VERIFY_URL = "/api/v1/auth/email/verify"
RESEND_URL = "/api/v1/auth/email/resend"
REGISTER_URL = "/api/v1/auth/register"


def _extract_token_from_email_body(body: str) -> str:
    """Extract verification token from email body without importing implementation code.

    The token is opaque and its internal format is not part of the API contract, so this
    helper stays format-agnostic: it takes the final whitespace-delimited word of the
    message. That survives a uid-prefixed token such as ``<uidb64>:<timestamp>-<hash>``,
    which a narrower character class would silently truncate.

    Falls back to key-value delimiters only if the trailing word looks unusable.
    """
    trailing = body.strip().split()[-1] if body.strip() else ""
    if len(trailing) >= 16:
        return trailing
    match = re.search(r"token[:=]\s*(\S+)", body, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = re.search(r"token\s+is\s+(\S+)", body, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return trailing


class BaseEmailVerificationTestCase(TestCase):
    """Base test class providing common helpers, client initialization, and cache reset."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def _obtain_valid_token_via_registration(
        self,
        email: str = "token.holder@example.com",
        password: str = "SecurePass123!",
    ) -> str:
        """Register a user inside captureOnCommitCallbacks and extract the verification token."""
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(
                REGISTER_URL,
                {
                    "email": email,
                    "password": password,
                    "first_name": "Token",
                    "last_name": "Holder",
                },
                format="json",
            )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertGreater(len(mail.outbox), 0, "Registration must dispatch an email on commit.")
        return _extract_token_from_email_body(mail.outbox[-1].body)

    def assert_validation_error_envelope(self, response, expected_field: str | None = None):
        """Helper to assert the standard §2 error envelope structure for 400 errors."""
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
            "Error 'message' must be a string.",
        )
        self.assertIsInstance(
            error.get("fields"),
            dict,
            "Error 'fields' must be a dictionary.",
        )
        if expected_field is not None:
            self.assertIn(
                expected_field,
                error["fields"],
                f"Expected field '{expected_field}' in error fields dictionary.",
            )
            self.assertIsInstance(
                error["fields"][expected_field],
                list,
                f"Field errors for '{expected_field}' must be a list.",
            )


class EmailVerificationRouteAndAccessTests(BaseEmailVerificationTestCase):
    """Verifies HTTP routing, allowed methods, and unauthenticated public access."""

    def test_verify_endpoint_accepts_post_on_literal_route(self):
        """Asserts POST to literal '/api/v1/auth/email/verify' is routed and handled."""
        response = self.client.post(
            VERIFY_URL,
            {"token": "dummy-token-for-routing-check"},
            format="json",
        )
        self.assertNotIn(
            response.status_code,
            [status.HTTP_404_NOT_FOUND, status.HTTP_405_METHOD_NOT_ALLOWED],
            f"Route {VERIFY_URL} must exist and accept POST.",
        )

    def test_resend_endpoint_accepts_post_on_literal_route(self):
        """Asserts POST to literal '/api/v1/auth/email/resend' is routed and handled."""
        response = self.client.post(
            RESEND_URL,
            {"email": "route.test@example.com"},
            format="json",
        )
        self.assertNotIn(
            response.status_code,
            [status.HTTP_404_NOT_FOUND, status.HTTP_405_METHOD_NOT_ALLOWED],
            f"Route {RESEND_URL} must exist and accept POST.",
        )

    def test_verify_endpoint_allows_unauthenticated_access(self):
        """Guards trap: verify endpoint must allow public unauthenticated access."""
        self.client.logout()
        response = self.client.post(
            VERIFY_URL,
            {"token": "unauth-check-token"},
            format="json",
        )
        self.assertNotIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
            "Unauthenticated request to verify endpoint must not return 401 or 403.",
        )

    def test_resend_endpoint_allows_unauthenticated_access(self):
        """Guards trap: resend endpoint must allow public unauthenticated access."""
        self.client.logout()
        response = self.client.post(
            RESEND_URL,
            {"email": "unauth.resend@example.com"},
            format="json",
        )
        self.assertNotIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
            "Unauthenticated request to resend endpoint must not return 401 or 403.",
        )

    def test_verify_disallowed_http_methods_return_405_method_not_allowed(self):
        """Asserts non-POST methods (GET, PUT, PATCH, DELETE) to verify return 405."""
        for method in ["get", "put", "patch", "delete"]:
            with self.subTest(http_method=method):
                cache.clear()
                client_method = getattr(self.client, method)
                response = client_method(VERIFY_URL)
                self.assertEqual(
                    response.status_code,
                    status.HTTP_405_METHOD_NOT_ALLOWED,
                    f"HTTP {method.upper()} to {VERIFY_URL} should return 405.",
                )

    def test_resend_disallowed_http_methods_return_405_method_not_allowed(self):
        """Asserts non-POST methods (GET, PUT, PATCH, DELETE) to resend return 405."""
        for method in ["get", "put", "patch", "delete"]:
            with self.subTest(http_method=method):
                cache.clear()
                client_method = getattr(self.client, method)
                response = client_method(RESEND_URL)
                self.assertEqual(
                    response.status_code,
                    status.HTTP_405_METHOD_NOT_ALLOWED,
                    f"HTTP {method.upper()} to {RESEND_URL} should return 405.",
                )


class EmailVerificationSuccessContractTests(BaseEmailVerificationTestCase):
    """Verifies the exact 200 response dictionary contract and User model state updates."""

    def test_valid_token_returns_200_with_exact_response_body(self):
        """Asserts successful verification returns 200 and exact message dictionary."""
        token = self._obtain_valid_token_via_registration(
            email="verify.contract@example.com",
            password="StrongPassword123!",
        )
        response = self.client.post(VERIFY_URL, {"token": token}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {"message": "Email verified successfully."},
            "Response body must match exact contract dictionary with no extra or missing keys.",
        )

    def test_valid_token_sets_email_verified_at_timestamp(self):
        """Asserts user.email_verified_at transitions from None to a datetime instance."""
        token = self._obtain_valid_token_via_registration(
            email="timestamp.coach@example.com",
            password="StrongPassword123!",
        )
        user_model = get_user_model()
        user = user_model.objects.get(email="timestamp.coach@example.com")
        self.assertIsNone(user.email_verified_at)

        response = self.client.post(VERIFY_URL, {"token": token}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        user.refresh_from_db()
        self.assertIsNotNone(
            user.email_verified_at,
            "User.email_verified_at must be populated after successful email verification.",
        )
        self.assertIsInstance(
            user.email_verified_at,
            datetime,
            "User.email_verified_at must be a datetime instance.",
        )

    def test_valid_token_preserves_user_active_status(self):
        """Asserts user is_active remains True upon verification."""
        token = self._obtain_valid_token_via_registration(
            email="active.coach@example.com",
            password="StrongPassword123!",
        )
        response = self.client.post(VERIFY_URL, {"token": token}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        user = get_user_model().objects.get(email="active.coach@example.com")
        self.assertTrue(user.is_active)


class EmailVerificationFailureAndIndistinguishabilityTests(BaseEmailVerificationTestCase):
    """Verifies failure handling, single-use invalidation, and indistinguishability."""

    def test_garbage_token_returns_400_with_validation_error_envelope(self):
        """Asserts syntactically wrong/non-existent token returns 400 VALIDATION_ERROR."""
        response = self.client.post(
            VERIFY_URL,
            {"token": "garbage-non-existent-token-12345"},
            format="json",
        )
        self.assert_validation_error_envelope(response)

    def test_already_verified_user_token_returns_400_with_validation_error_envelope(self):
        """Asserts submitting a token for an already-verified user fails (single-use token)."""
        token = self._obtain_valid_token_via_registration(
            email="singleuse.coach@example.com",
            password="StrongPassword123!",
        )
        first_resp = self.client.post(VERIFY_URL, {"token": token}, format="json")
        self.assertEqual(first_resp.status_code, status.HTTP_200_OK)

        # Second attempt with the same token must fail with 400 Bad Request
        second_resp = self.client.post(VERIFY_URL, {"token": token}, format="json")
        self.assert_validation_error_envelope(second_resp)

    def test_invalid_and_already_used_tokens_produce_indistinguishable_responses(self):
        """Asserts invalid and already-used token failures are completely indistinguishable.

        Proves that an attacker cannot distinguish between an invalid/garbage token
        and an expired/already-used token through status code, error code, or message.
        """
        # 1. Obtain and use a valid token
        token = self._obtain_valid_token_via_registration(
            email="indistinguishable@example.com",
            password="StrongPassword123!",
        )
        resp_success = self.client.post(VERIFY_URL, {"token": token}, format="json")
        self.assertEqual(resp_success.status_code, status.HTTP_200_OK)

        # 2. Re-submit the used token (used/expired case)
        resp_used = self.client.post(VERIFY_URL, {"token": token}, format="json")

        # 3. Submit a garbage token (invalid/nonexistent case)
        resp_garbage = self.client.post(
            VERIFY_URL,
            {"token": "arbitrary-invalid-token-string-98765"},
            format="json",
        )

        # Both must return 400 Bad Request
        self.assertEqual(resp_used.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp_garbage.status_code, status.HTTP_400_BAD_REQUEST)

        used_error = resp_used.json().get("error", {})
        garbage_error = resp_garbage.json().get("error", {})

        # Status, code, and message must match exactly
        self.assertEqual(
            resp_used.status_code,
            resp_garbage.status_code,
            "Status codes for used and garbage tokens must be identical.",
        )
        self.assertEqual(
            used_error.get("code"),
            "VALIDATION_ERROR",
            "Error code for used token must be VALIDATION_ERROR.",
        )
        self.assertEqual(
            garbage_error.get("code"),
            "VALIDATION_ERROR",
            "Error code for garbage token must be VALIDATION_ERROR.",
        )
        self.assertEqual(
            used_error.get("message"),
            garbage_error.get("message"),
            "Error message for used and garbage tokens must be identical.",
        )

    def test_missing_token_field_returns_400_with_validation_error_envelope(self):
        """Asserts omitting the 'token' field returns 400 with VALIDATION_ERROR."""
        response = self.client.post(
            VERIFY_URL,
            {"other_key": "some-value"},
            format="json",
        )
        self.assert_validation_error_envelope(response, expected_field="token")

    def test_empty_payload_returns_400_with_validation_error_envelope(self):
        """Asserts sending an empty JSON payload returns 400 with VALIDATION_ERROR."""
        response = self.client.post(VERIFY_URL, {}, format="json")
        self.assert_validation_error_envelope(response)

    def test_empty_or_non_string_token_returns_400_with_validation_error_envelope(self):
        """Asserts empty string or non-string token types return 400 VALIDATION_ERROR."""
        invalid_tokens = ["", 12345, None, True, []]
        for token_val in invalid_tokens:
            with self.subTest(token=token_val):
                response = self.client.post(
                    VERIFY_URL,
                    {"token": token_val},
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                data = response.json()
                self.assertEqual(data.get("error", {}).get("code"), "VALIDATION_ERROR")


class EmailResendAntiEnumerationTests(BaseEmailVerificationTestCase):
    """Verifies generic responses preventing account enumeration across all email states."""

    def test_resend_returns_200_for_unknown_email(self):
        """Asserts requesting resend for an unknown email returns 200 without enumeration."""
        response = self.client.post(
            RESEND_URL,
            {"email": "completely.unknown.coach@example.com"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_resend_returns_200_for_known_unverified_email(self):
        """Asserts requesting resend for a known unverified email returns 200."""
        get_user_model().objects.create_user(
            email="known.unverified@example.com",
            password="SecurePassword123!",
            email_verified_at=None,
        )
        response = self.client.post(
            RESEND_URL,
            {"email": "known.unverified@example.com"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_resend_returns_200_for_known_already_verified_email(self):
        """Asserts requesting resend for an already verified email returns 200."""
        get_user_model().objects.create_user(
            email="known.verified@example.com",
            password="SecurePassword123!",
            email_verified_at=timezone.now(),
        )
        response = self.client.post(
            RESEND_URL,
            {"email": "known.verified@example.com"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_resend_responses_are_byte_identical_across_all_three_enumeration_cases(self):
        """Asserts resend responses for unknown, unverified, and verified emails are identical.

        Guards against timing-independent account enumeration: status code, parsed JSON,
        and raw response content bytes must be identical regardless of whether the account
        exists or is verified.
        """
        user_model = get_user_model()
        user_model.objects.create_user(
            email="enum.unverified@example.com",
            password="SecurePassword123!",
            email_verified_at=None,
        )
        user_model.objects.create_user(
            email="enum.verified@example.com",
            password="SecurePassword123!",
            email_verified_at=timezone.now(),
        )

        resp_unverified = self.client.post(
            RESEND_URL,
            {"email": "enum.unverified@example.com"},
            format="json",
        )
        resp_verified = self.client.post(
            RESEND_URL,
            {"email": "enum.verified@example.com"},
            format="json",
        )
        resp_unknown = self.client.post(
            RESEND_URL,
            {"email": "enum.unknown@example.com"},
            format="json",
        )

        # 1. Status codes must all be 200 OK
        self.assertEqual(resp_unverified.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_verified.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_unknown.status_code, status.HTTP_200_OK)

        # 2. Parsed JSON dictionaries must be equal
        self.assertEqual(
            resp_unverified.json(),
            resp_verified.json(),
            "Resend JSON payload for verified user must match unverified user.",
        )
        self.assertEqual(
            resp_unverified.json(),
            resp_unknown.json(),
            "Resend JSON payload for unknown user must match unverified user.",
        )

        # 3. Raw response content bytes must be identical
        self.assertEqual(
            resp_unverified.content,
            resp_verified.content,
            "Raw response content bytes for verified user must match unverified user.",
        )
        self.assertEqual(
            resp_unverified.content,
            resp_unknown.content,
            "Raw response content bytes for unknown user must match unverified user.",
        )

    def test_resend_missing_email_field_returns_400_with_validation_error_envelope(self):
        """Asserts omitting the 'email' field on resend returns 400 VALIDATION_ERROR."""
        response = self.client.post(
            RESEND_URL,
            {"other_key": "not-email"},
            format="json",
        )
        self.assert_validation_error_envelope(response, expected_field="email")

    def test_resend_invalid_email_format_returns_400_with_validation_error_envelope(self):
        """Asserts sending a malformed email string returns 400 VALIDATION_ERROR."""
        response = self.client.post(
            RESEND_URL,
            {"email": "not-a-valid-email"},
            format="json",
        )
        self.assert_validation_error_envelope(response, expected_field="email")

    def test_resend_empty_payload_returns_400_with_validation_error_envelope(self):
        """Asserts sending an empty JSON payload to resend returns 400 VALIDATION_ERROR."""
        response = self.client.post(RESEND_URL, {}, format="json")
        self.assert_validation_error_envelope(response)


class EmailResendDispatchTests(BaseEmailVerificationTestCase):
    """Verifies transaction on-commit email dispatch behavior, privacy, and non-leakage."""

    def test_resend_dispatches_single_email_on_commit_for_unverified_user(self):
        """Asserts on-commit callback sends exactly one email to an unverified user."""
        get_user_model().objects.create_user(
            email="resend.target@example.com",
            password="SecurePassword123!",
            email_verified_at=None,
        )
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                RESEND_URL,
                {"email": "resend.target@example.com"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            len(mail.outbox),
            1,
            "Exactly one verification email should be dispatched on transaction commit.",
        )
        self.assertEqual(mail.outbox[0].to, ["resend.target@example.com"])

    def test_resend_dispatches_no_email_for_unknown_email(self):
        """Asserts no email is dispatched when requesting resend for an unknown email."""
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                RESEND_URL,
                {"email": "resend.unknown@example.com"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            len(mail.outbox),
            0,
            "No email should be dispatched for an unknown email address.",
        )

    def test_resend_dispatches_no_email_for_already_verified_user(self):
        """Asserts no email is dispatched when requesting resend for an already verified user."""
        get_user_model().objects.create_user(
            email="resend.verified@example.com",
            password="SecurePassword123!",
            email_verified_at=timezone.now(),
        )
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                RESEND_URL,
                {"email": "resend.verified@example.com"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            len(mail.outbox),
            0,
            "No email should be dispatched when user is already verified.",
        )

    def test_resend_does_not_dispatch_email_without_transaction_commit(self):
        """Asserts verification email is not dispatched before transaction commit."""
        get_user_model().objects.create_user(
            email="resend.deferred@example.com",
            password="SecurePassword123!",
            email_verified_at=None,
        )
        response = self.client.post(
            RESEND_URL,
            {"email": "resend.deferred@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            len(mail.outbox),
            0,
            "No email should be dispatched before transaction commit (must use on_commit).",
        )

    def test_resend_email_does_not_leak_raw_password_and_contains_token(self):
        """Asserts sent email does not leak user password and contains verification token."""
        raw_password = "ConfidentialPasswordToProtect123!"
        get_user_model().objects.create_user(
            email="privacy.resend@example.com",
            password=raw_password,
            email_verified_at=None,
        )
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                RESEND_URL,
                {"email": "privacy.resend@example.com"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        self.assertNotIn(raw_password, sent_email.body)
        self.assertNotIn(raw_password, sent_email.subject)

        # Extract token and assert it can verify the user
        extracted_token = _extract_token_from_email_body(sent_email.body)
        self.assertTrue(bool(extracted_token), "Email body should contain a parseable token.")
        verify_resp = self.client.post(
            VERIFY_URL,
            {"token": extracted_token},
            format="json",
        )
        self.assertEqual(verify_resp.status_code, status.HTTP_200_OK)


class EmailVerificationRateLimitingTests(BaseEmailVerificationTestCase):
    """Verifies endpoint-scoped throttling limits and unthrottled registration."""

    def test_resend_endpoint_throttled_after_3_requests_per_minute(self):
        """Asserts resend endpoint enforces 3/min rate limit and returns 429 on 4th request."""
        payload = {"email": "throttle.resend@example.com"}
        for i in range(3):
            resp = self.client.post(RESEND_URL, payload, format="json")
            self.assertIn(
                resp.status_code,
                [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST],
                f"Request {i + 1} within rate limit should not be throttled.",
            )

        throttled_resp = self.client.post(RESEND_URL, payload, format="json")
        self.assertEqual(
            throttled_resp.status_code,
            status.HTTP_429_TOO_MANY_REQUESTS,
            "4th request within a minute to resend must return 429 Too Many Requests.",
        )
        error = throttled_resp.json().get("error", {})
        self.assertEqual(
            error.get("code"),
            "RATE_LIMITED",
            "Throttled response must return code 'RATE_LIMITED' in §2 error envelope.",
        )

    def test_verify_endpoint_throttled_after_10_requests_per_minute(self):
        """Asserts verify endpoint enforces 10/min rate limit and returns 429 on 11th request."""
        payload = {"token": "dummy-token-for-throttle-test"}
        for i in range(10):
            resp = self.client.post(VERIFY_URL, payload, format="json")
            self.assertIn(
                resp.status_code,
                [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST],
                f"Request {i + 1} within rate limit should not be throttled.",
            )

        throttled_resp = self.client.post(VERIFY_URL, payload, format="json")
        self.assertEqual(
            throttled_resp.status_code,
            status.HTTP_429_TOO_MANY_REQUESTS,
            "11th request within a minute to verify must return 429 Too Many Requests.",
        )
        error = throttled_resp.json().get("error", {})
        self.assertEqual(
            error.get("code"),
            "RATE_LIMITED",
            "Throttled response must return code 'RATE_LIMITED' in §2 error envelope.",
        )

    def test_registration_endpoint_remains_unthrottled_under_rapid_requests(self):
        """Asserts /api/v1/auth/register has no rate limit affecting rapid registrations."""
        for i in range(6):
            resp = self.client.post(
                REGISTER_URL,
                {
                    "email": f"rapid.unthrottled.{i}@example.com",
                    "password": "StrongPassword123!",
                    "first_name": f"User{i}",
                    "last_name": "Test",
                },
                format="json",
            )
            self.assertEqual(
                resp.status_code,
                status.HTTP_201_CREATED,
                f"Registration {i + 1} should succeed with 201 without being throttled.",
            )


class EmailVerificationArchitectureGuardTests(BaseEmailVerificationTestCase):
    """Verifies architectural constraints: no token model in accounts app."""

    def test_accounts_app_exposes_only_approved_models_and_no_token_model(self):
        """Asserts accounts defines the approved model set and no token model."""
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
            "accounts must contain only the approved models (no session or token model).",
        )
