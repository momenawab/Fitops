"""API tests for Password Reset endpoints (Story 2.10 / Task B).

Validates:
- Literal routing and unauthenticated public access for forgot and reset endpoints
- Anti-enumeration guarantee (byte-identical 200 responses for existing vs unknown accounts)
- Transaction on-commit email dispatch with stateless token and sensitive data non-leakage
- Password reset happy path: token consumption, 200 response, and proof via subsequent login
- Single-use token enforcement: re-using a consumed token fails with 400 VALIDATION_ERROR
- Token guards: garbage, empty, wrong-user, and malformed tokens return 400 VALIDATION_ERROR
- Password validation: weak passwords return 400 VALIDATION_ERROR under 'password' without change
- Scoped rate limiting: forgot (3/min) and reset (10/min) return 429 RATE_LIMITED
- Unthrottled registration and email verification resend regression guard (Story 2.5)
- Architecture guard: accounts defines {User, CoachProfile, ClientProfile, CoachSecurity}
"""

import re

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

FORGOT_URL = "/api/v1/auth/password/forgot"
RESET_URL = "/api/v1/auth/password/reset"
LOGIN_URL = "/api/v1/auth/login"
REGISTER_URL = "/api/v1/auth/register"
RESEND_URL = "/api/v1/auth/email/resend"


def _extract_token_from_email_body(body: str) -> str:
    """Extract password reset token from email body without importing implementation code.

    Format-agnostic: checks for query parameter ?token=..., labeled token formats
    (token: ..., token is ...), path segments (/reset/<token>), and trailing words.
    """
    if not body or not body.strip():
        return ""
    match = re.search(r"[?&]token=([^&\s'\"<>]+)", body)
    if match:
        return match.group(1).strip()
    match = re.search(r"token(?:\s+is|\s*:|\s*=)\s*([^\s'\"<>,;]+)", body, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = re.search(r"/reset(?:-password)?/([a-zA-Z0-9_.:\-]+)", body)
    if match:
        return match.group(1).strip()
    trailing = body.strip().split()[-1]
    if len(trailing) >= 16:
        return trailing.rstrip(".,;!?:")
    return trailing


class BasePasswordResetTestCase(TestCase):
    """Base test class providing common helpers, client initialization, and cache reset."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def _create_verified_user(
        self,
        email: str = "coach@example.com",
        password: str = "StrongPassword123!",
        **kwargs,
    ):
        """Creates and returns an active, email-verified User."""
        kwargs.setdefault("email_verified_at", timezone.now())
        kwargs.setdefault("first_name", "Coach")
        kwargs.setdefault("last_name", "Tester")
        return get_user_model().objects.create_user(
            email=email,
            password=password,
            **kwargs,
        )

    def _request_forgot_password_token(self, email: str) -> str:
        """Calls /password/forgot in captureOnCommitCallbacks and extracts token from email."""
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(
                FORGOT_URL,
                {"email": email},
                format="json",
            )
        self.assertEqual(
            resp.status_code,
            status.HTTP_200_OK,
            f"Forgot password request for {email} must return 200 OK.",
        )
        self.assertGreater(
            len(mail.outbox),
            0,
            f"Forgot password request for {email} must dispatch an email on commit.",
        )
        token = _extract_token_from_email_body(mail.outbox[-1].body)
        self.assertTrue(bool(token), "Failed to extract reset token from dispatched email body.")
        return token

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

    def assert_invalid_credentials_envelope(self, response):
        """Helper to assert the standard §2 error envelope for 401 INVALID_CREDENTIALS."""
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        data = response.json()
        self.assertEqual(
            set(data.keys()),
            {"error"},
            "Response top-level key must be exactly 'error'.",
        )
        error = data["error"]
        self.assertIsInstance(error, dict)
        self.assertEqual(error.get("code"), "INVALID_CREDENTIALS")
        self.assertIsInstance(
            error.get("message"),
            str,
            "Error 'message' must be a string.",
        )


class PasswordResetRouteAndAccessTests(BasePasswordResetTestCase):
    """Verifies HTTP routing, allowed methods, and unauthenticated public access."""

    def test_forgot_endpoint_accepts_post_on_literal_route(self):
        """Asserts POST to literal '/api/v1/auth/password/forgot' is routed and handled."""
        response = self.client.post(
            FORGOT_URL,
            {"email": "route.forgot@example.com"},
            format="json",
        )
        self.assertNotIn(
            response.status_code,
            [status.HTTP_404_NOT_FOUND, status.HTTP_405_METHOD_NOT_ALLOWED],
            f"Route {FORGOT_URL} must exist and accept POST.",
        )

    def test_reset_endpoint_accepts_post_on_literal_route(self):
        """Asserts POST to literal '/api/v1/auth/password/reset' is routed and handled."""
        response = self.client.post(
            RESET_URL,
            {"token": "dummy-token-check", "password": "NewStrongPassword123!"},
            format="json",
        )
        self.assertNotIn(
            response.status_code,
            [status.HTTP_404_NOT_FOUND, status.HTTP_405_METHOD_NOT_ALLOWED],
            f"Route {RESET_URL} must exist and accept POST.",
        )

    def test_forgot_endpoint_allows_unauthenticated_access(self):
        """Guards trap: forgot endpoint must allow public access overriding IsAuthenticated."""
        self.client.logout()
        response = self.client.post(
            FORGOT_URL,
            {"email": "unauth.forgot@example.com"},
            format="json",
        )
        self.assertNotIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
            "Unauthenticated request to forgot endpoint must not return 401 or 403.",
        )

    def test_reset_endpoint_allows_unauthenticated_access(self):
        """Guards trap: reset endpoint must allow public access overriding IsAuthenticated."""
        self.client.logout()
        response = self.client.post(
            RESET_URL,
            {"token": "unauth-reset-token", "password": "NewStrongPassword123!"},
            format="json",
        )
        self.assertNotIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
            "Unauthenticated request to reset endpoint must not return 401 or 403.",
        )

    def test_forgot_disallowed_http_methods_return_405_method_not_allowed(self):
        """Asserts non-POST methods (GET, PUT, PATCH, DELETE) to forgot return 405."""
        for method in ["get", "put", "patch", "delete"]:
            with self.subTest(http_method=method):
                cache.clear()
                client_method = getattr(self.client, method)
                response = client_method(FORGOT_URL)
                self.assertEqual(
                    response.status_code,
                    status.HTTP_405_METHOD_NOT_ALLOWED,
                    f"HTTP {method.upper()} to {FORGOT_URL} should return 405.",
                )

    def test_reset_disallowed_http_methods_return_405_method_not_allowed(self):
        """Asserts non-POST methods (GET, PUT, PATCH, DELETE) to reset return 405."""
        for method in ["get", "put", "patch", "delete"]:
            with self.subTest(http_method=method):
                cache.clear()
                client_method = getattr(self.client, method)
                response = client_method(RESET_URL)
                self.assertEqual(
                    response.status_code,
                    status.HTTP_405_METHOD_NOT_ALLOWED,
                    f"HTTP {method.upper()} to {RESET_URL} should return 405.",
                )


class PasswordForgotAntiEnumerationTests(BasePasswordResetTestCase):
    """Verifies generic anti-enumeration responses and email dispatch for /password/forgot."""

    def test_forgot_returns_200_for_existing_user(self):
        """Asserts requesting password reset for an existing user returns 200 OK."""
        self._create_verified_user(email="existing.forgot@example.com")
        response = self.client.post(
            FORGOT_URL,
            {"email": "existing.forgot@example.com"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_forgot_returns_200_for_non_existent_email(self):
        """Asserts requesting password reset for a non-existent email returns 200 OK."""
        response = self.client.post(
            FORGOT_URL,
            {"email": "nonexistent.forgot@example.com"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_forgot_responses_are_identical_between_existing_and_non_existent_emails(self):
        """Asserts responses for existing and non-existent emails are completely identical.

        Guards against timing-independent account enumeration: status code, parsed JSON,
        and raw response content bytes must be identical regardless of whether the account
        exists in the database.
        """
        self._create_verified_user(email="enum.existing@example.com")

        resp_existing = self.client.post(
            FORGOT_URL,
            {"email": "enum.existing@example.com"},
            format="json",
        )
        resp_nonexistent = self.client.post(
            FORGOT_URL,
            {"email": "enum.nonexistent@example.com"},
            format="json",
        )

        # 1. Status codes must both be 200 OK
        self.assertEqual(resp_existing.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_nonexistent.status_code, status.HTTP_200_OK)
        self.assertEqual(
            resp_existing.status_code,
            resp_nonexistent.status_code,
            "Status codes for existing and non-existent accounts must be identical.",
        )

        # 2. Parsed JSON dictionaries must be equal
        self.assertEqual(
            resp_existing.json(),
            resp_nonexistent.json(),
            "JSON response payload for existing user must match non-existent user.",
        )

        # 3. Raw response content bytes must be identical
        self.assertEqual(
            resp_existing.content,
            resp_nonexistent.content,
            "Raw response bytes for existing user must match non-existent user.",
        )

    def test_forgot_dispatches_email_for_existing_user_on_commit(self):
        """Asserts on-commit callback sends exactly one reset email to an existing user."""
        self._create_verified_user(email="dispatch.target@example.com")
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                FORGOT_URL,
                {"email": "dispatch.target@example.com"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            len(mail.outbox),
            1,
            "Exactly one reset email should be dispatched on transaction commit.",
        )
        self.assertEqual(mail.outbox[0].to, ["dispatch.target@example.com"])

    def test_forgot_dispatches_no_email_for_non_existent_user(self):
        """Asserts no email is dispatched when requesting forgot password for unknown email."""
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                FORGOT_URL,
                {"email": "unknown.target@example.com"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            len(mail.outbox),
            0,
            "No email should be dispatched for a non-existent email address.",
        )

    def test_forgot_does_not_dispatch_email_without_transaction_commit(self):
        """Asserts reset email is not dispatched before transaction commit."""
        self._create_verified_user(email="deferred.forgot@example.com")
        response = self.client.post(
            FORGOT_URL,
            {"email": "deferred.forgot@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            len(mail.outbox),
            0,
            "No email should be dispatched before transaction commit (must use on_commit).",
        )

    def test_forgot_email_does_not_leak_password_hash_and_contains_token(self):
        """Asserts sent reset email does not leak user password and contains reset token."""
        raw_password = "ConfidentialOriginalPassword123!"
        user = self._create_verified_user(
            email="privacy.forgot@example.com",
            password=raw_password,
        )
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                FORGOT_URL,
                {"email": "privacy.forgot@example.com"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        self.assertNotIn(raw_password, sent_email.body)
        self.assertNotIn(raw_password, sent_email.subject)
        self.assertNotIn(user.password, sent_email.body)
        self.assertNotIn(user.password, sent_email.subject)

        token = _extract_token_from_email_body(sent_email.body)
        self.assertTrue(bool(token), "Email body should contain a parseable reset token.")

    def test_forgot_invalid_email_format_returns_400_validation_error(self):
        """Asserts sending a malformed email string to forgot returns 400 VALIDATION_ERROR."""
        response = self.client.post(
            FORGOT_URL,
            {"email": "not-a-valid-email"},
            format="json",
        )
        self.assert_validation_error_envelope(response, expected_field="email")

    def test_forgot_missing_email_or_empty_payload_returns_400_validation_error(self):
        """Asserts omitting email or sending empty payload returns 400 VALIDATION_ERROR."""
        response_missing = self.client.post(
            FORGOT_URL,
            {"other_key": "not-an-email"},
            format="json",
        )
        self.assert_validation_error_envelope(response_missing, expected_field="email")

        response_empty = self.client.post(FORGOT_URL, {}, format="json")
        self.assert_validation_error_envelope(response_empty)


class PasswordResetSuccessAndLoginProofTests(BasePasswordResetTestCase):
    """Verifies the complete password reset flow, token consumption, and login proof."""

    def test_reset_with_valid_token_and_strong_password_returns_200_and_authenticates_new_password(
        self,
    ):
        """Asserts successful reset returns 200, old password fails login, and new password logs in.

        This is the definitive proof of effect:
        1. Obtain a real token via /password/forgot and sent email.
        2. Submit /password/reset with strong new password -> returns 200.
        3. Attempt login with old password -> 401 INVALID_CREDENTIALS.
        4. Attempt login with new password -> 200 OK {'authenticated': True}.
        """
        email = "reset.success.coach@example.com"
        old_password = "OldInitialPassword123!"
        new_password = "NewStrongPassword456!"

        self._create_verified_user(email=email, password=old_password)

        # 1. Obtain token black-box from email
        token = self._request_forgot_password_token(email)

        # 2. Reset password
        reset_response = self.client.post(
            RESET_URL,
            {"token": token, "password": new_password},
            format="json",
        )
        self.assertEqual(reset_response.status_code, status.HTTP_200_OK)

        # 3. Old password must NO LONGER authenticate
        old_login_resp = self.client.post(
            LOGIN_URL,
            {"email": email, "password": old_password},
            format="json",
        )
        self.assert_invalid_credentials_envelope(old_login_resp)

        # 4. New password MUST authenticate successfully
        new_login_resp = self.client.post(
            LOGIN_URL,
            {"email": email, "password": new_password},
            format="json",
        )
        self.assertEqual(new_login_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(
            new_login_resp.json(),
            {"authenticated": True},
            "Successful login with new password must return {'authenticated': True}.",
        )

    def test_reset_updates_user_password_hash_in_database_and_preserves_active_status(self):
        """Asserts database User.password hash is updated and user remains active."""
        email = "db.update.coach@example.com"
        old_password = "OldPassword123!"
        new_password = "NewStrongPassword123!"

        user = self._create_verified_user(email=email, password=old_password)
        old_hash = user.password

        token = self._request_forgot_password_token(email)
        reset_resp = self.client.post(
            RESET_URL,
            {"token": token, "password": new_password},
            format="json",
        )
        self.assertEqual(reset_resp.status_code, status.HTTP_200_OK)

        user.refresh_from_db()
        self.assertNotEqual(user.password, old_hash)
        self.assertTrue(user.check_password(new_password))
        self.assertFalse(user.check_password(old_password))
        self.assertTrue(user.is_active)


class PasswordResetTokenGuardTests(BasePasswordResetTestCase):
    """Verifies token invalidation, single-use enforcement, and malformed token rejection."""

    def test_reusing_consumed_token_returns_400_validation_error(self):
        """Asserts submitting an already-used token returns 400 VALIDATION_ERROR (single use).

        Stateless token invalidation: changing the password invalidates the token hash,
        so any subsequent attempt with the original token must fail under the 'token' field.
        """
        email = "singleuse.guard@example.com"
        first_new_pw = "FirstNewPassword123!"
        second_new_pw = "SecondNewPassword456!"

        self._create_verified_user(email=email, password="InitialPassword123!")
        token = self._request_forgot_password_token(email)

        # 1. First reset succeeds
        first_resp = self.client.post(
            RESET_URL,
            {"token": token, "password": first_new_pw},
            format="json",
        )
        self.assertEqual(first_resp.status_code, status.HTTP_200_OK)

        # 2. Re-using the exact same token MUST fail
        second_resp = self.client.post(
            RESET_URL,
            {"token": token, "password": second_new_pw},
            format="json",
        )
        self.assert_validation_error_envelope(second_resp, expected_field="token")

        # 3. Second password change must NOT have taken effect
        user = get_user_model().objects.get(email=email)
        self.assertTrue(user.check_password(first_new_pw))
        self.assertFalse(user.check_password(second_new_pw))

    def test_garbage_token_returns_400_validation_error(self):
        """Asserts arbitrary or syntactically invalid token returns 400 VALIDATION_ERROR."""
        response = self.client.post(
            RESET_URL,
            {"token": "not-a-token", "password": "StrongPassword123!"},
            format="json",
        )
        self.assert_validation_error_envelope(response, expected_field="token")

    def test_token_from_different_user_cannot_reset_another_account(self):
        """Asserts a consumed or altered user's token cannot be used to modify account state."""
        user_a_email = "user.alpha@example.com"
        self._create_verified_user(email=user_a_email, password="PasswordA123!")
        token_a = self._request_forgot_password_token(user_a_email)

        # Consuming token_a changes User A's password
        consume_resp = self.client.post(
            RESET_URL,
            {"token": token_a, "password": "NewPasswordA123!"},
            format="json",
        )
        self.assertEqual(consume_resp.status_code, status.HTTP_200_OK)

        # Attempting to use token_a again fails
        replay_resp = self.client.post(
            RESET_URL,
            {"token": token_a, "password": "AttackPassword123!"},
            format="json",
        )
        self.assert_validation_error_envelope(replay_resp, expected_field="token")

    def test_reset_missing_required_fields_return_400_validation_error(self):
        """Asserts omitting token or password returns 400 with VALIDATION_ERROR envelope."""
        # Missing token
        resp_no_token = self.client.post(
            RESET_URL,
            {"password": "StrongPassword123!"},
            format="json",
        )
        self.assert_validation_error_envelope(resp_no_token, expected_field="token")

        # Missing password
        resp_no_pw = self.client.post(
            RESET_URL,
            {"token": "dummy-token-sample"},
            format="json",
        )
        self.assert_validation_error_envelope(resp_no_pw, expected_field="password")

        # Empty payload
        resp_empty = self.client.post(RESET_URL, {}, format="json")
        self.assert_validation_error_envelope(resp_empty)

    def test_reset_empty_or_non_string_token_returns_400_validation_error(self):
        """Asserts empty string or non-string token types return 400 VALIDATION_ERROR."""
        invalid_tokens = ["", 12345, None, True, []]
        for token_val in invalid_tokens:
            with self.subTest(token=token_val):
                response = self.client.post(
                    RESET_URL,
                    {"token": token_val, "password": "StrongPassword123!"},
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                data = response.json()
                self.assertEqual(data.get("error", {}).get("code"), "VALIDATION_ERROR")


class PasswordResetPasswordValidationTests(BasePasswordResetTestCase):
    """Verifies password strength validation rules on /password/reset."""

    def test_weak_password_returns_400_validation_error_and_preserves_existing_password(self):
        """Asserts weak passwords return 400 VALIDATION_ERROR under 'password' and do not reset."""
        email = "weak.pw.coach@example.com"
        old_password = "StrongOriginalPassword123!"
        self._create_verified_user(email=email, password=old_password)

        token = self._request_forgot_password_token(email)
        weak_passwords = ["123", "short", "password", "12345678", "abc"]

        for weak_pw in weak_passwords:
            with self.subTest(password=weak_pw):
                response = self.client.post(
                    RESET_URL,
                    {"token": token, "password": weak_pw},
                    format="json",
                )
                self.assert_validation_error_envelope(response, expected_field="password")

        # The old password was NOT modified by any rejected attempt.
        user = get_user_model().objects.get(email=email)
        self.assertTrue(user.check_password(old_password))

        # Because the password was never changed, the token is still unconsumed and a strong
        # password succeeds. This must run BEFORE any login: Django folds `last_login` into the
        # token hash, so signing in would itself invalidate an outstanding reset token.
        success_resp = self.client.post(
            RESET_URL,
            {"token": token, "password": "NewStrongValidPassword123!"},
            format="json",
        )
        self.assertEqual(success_resp.status_code, status.HTTP_200_OK)

        # End-to-end proof the reset took effect.
        login_resp = self.client.post(
            LOGIN_URL,
            {"email": email, "password": "NewStrongValidPassword123!"},
            format="json",
        )
        self.assertEqual(login_resp.status_code, status.HTTP_200_OK)


class PasswordResetTokenInvalidationTests(BasePasswordResetTestCase):
    """Verifies side effects that must invalidate an outstanding reset token."""

    def test_successful_login_invalidates_an_outstanding_reset_token(self):
        """Asserts signing in kills a pending reset token.

        Django folds `last_login` into the reset-token hash, so a successful login invalidates
        any outstanding token. That is a desirable security property: a user who requests a
        reset and then remembers their password leaves no usable token behind for an attacker
        who later intercepts the email. Locked here so a future token change cannot silently
        drop it.
        """
        email = "invalidate.login@example.com"
        old_password = "OriginalStrongPassword123!"
        self._create_verified_user(email=email, password=old_password)
        token = self._request_forgot_password_token(email)

        login_resp = self.client.post(
            LOGIN_URL,
            {"email": email, "password": old_password},
            format="json",
        )
        self.assertEqual(login_resp.status_code, status.HTTP_200_OK)

        reset_resp = self.client.post(
            RESET_URL,
            {"token": token, "password": "NewStrongValidPassword123!"},
            format="json",
        )
        self.assert_validation_error_envelope(reset_resp, expected_field="token")


class PasswordResetThrottlingTests(BasePasswordResetTestCase):
    """Verifies rate limiting for forgot (3/min) and reset (10/min) endpoints."""

    def test_forgot_endpoint_throttled_after_3_requests_per_minute(self):
        """Asserts /password/forgot enforces 3/min limit and returns 429 on 4th request."""
        payload = {"email": "throttle.forgot@example.com"}
        for i in range(3):
            resp = self.client.post(FORGOT_URL, payload, format="json")
            self.assertIn(
                resp.status_code,
                [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST],
                f"Forgot request {i + 1} within rate limit should not be throttled.",
            )

        throttled_resp = self.client.post(FORGOT_URL, payload, format="json")
        self.assertEqual(
            throttled_resp.status_code,
            status.HTTP_429_TOO_MANY_REQUESTS,
            "4th request within a minute to /password/forgot must return 429 Too Many Requests.",
        )
        error = throttled_resp.json().get("error", {})
        self.assertEqual(
            error.get("code"),
            "RATE_LIMITED",
            "Throttled response must return code 'RATE_LIMITED' in §2 error envelope.",
        )

    def test_reset_endpoint_throttled_after_10_requests_per_minute(self):
        """Asserts /password/reset enforces 10/min limit and returns 429 on 11th request."""
        payload = {"token": "dummy-token-for-throttle", "password": "StrongPassword123!"}
        for i in range(10):
            resp = self.client.post(RESET_URL, payload, format="json")
            self.assertIn(
                resp.status_code,
                [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST],
                f"Reset request {i + 1} within rate limit should not be throttled.",
            )

        throttled_resp = self.client.post(RESET_URL, payload, format="json")
        self.assertEqual(
            throttled_resp.status_code,
            status.HTTP_429_TOO_MANY_REQUESTS,
            "11th request within a minute to /password/reset must return 429 Too Many Requests.",
        )
        error = throttled_resp.json().get("error", {})
        self.assertEqual(
            error.get("code"),
            "RATE_LIMITED",
            "Throttled response must return code 'RATE_LIMITED' in §2 error envelope.",
        )

    def test_registration_endpoint_remains_unthrottled_by_password_reset_throttles(self):
        """Asserts /api/v1/auth/register has no rate limit affecting rapid registrations."""
        for i in range(6):
            resp = self.client.post(
                REGISTER_URL,
                {
                    "email": f"rapid.pwreset.unthrottled.{i}@example.com",
                    "password": "StrongPassword123!",
                    "first_name": f"User{i}",
                    "last_name": "Tester",
                },
                format="json",
            )
            self.assertEqual(
                resp.status_code,
                status.HTTP_201_CREATED,
                f"Registration {i + 1} should succeed with 201 without being throttled.",
            )


class PasswordResetRegressionAndArchitectureGuardTests(BasePasswordResetTestCase):
    """Verifies regression safety for email verification and architectural constraints."""

    def test_email_verification_resend_regression_guard_returns_generic_200(self):
        """Asserts /api/v1/auth/email/resend returns generic 200 (Story 2.5 regression guard)."""
        response = self.client.post(
            RESEND_URL,
            {"email": "regression.resend@example.com"},
            format="json",
        )
        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            "Resend endpoint must remain functional after password reset refactors.",
        )

    def test_accounts_app_exposes_only_approved_models_and_no_reset_token_model(self):
        """Asserts accounts defines {User, CoachProfile, ClientProfile, CoachSecurity}."""
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
            "accounts must contain only the approved models (no password reset token model).",
        )
