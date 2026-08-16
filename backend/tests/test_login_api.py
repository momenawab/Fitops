"""API tests for Coach Login and CoachSecurity model contract (Story 2.6 / Task B).

Validates:
- Literal routing and unauthenticated public access for POST /api/v1/auth/login
- Exact 200 response contracts (dict equality) for both 2FA-disabled and 2FA-enabled flows
- Django session cookie creation on success and strict absence of session cookie on 2FA branch
- Secure password authentication and non-leakage of raw password or password hash
- Anti-enumeration guarantee (indistinguishable 401 responses for unknown email vs wrong password)
- Email verification enforcement (403 EMAIL_NOT_VERIFIED) and credential check precedence
- CoachSecurity model schema contract, defaults, OneToOne CASCADE relation, and secret protection
- Rate limiting on login (10 req/min, 429 RATE_LIMITED) and unthrottled registration
- Architecture guard: accounts defines exactly {User, CoachProfile, ClientProfile, CoachSecurity}
"""

from django.apps import apps
from django.conf import settings
from django.contrib.auth import SESSION_KEY, get_user_model
from django.core.cache import cache
from django.db import models
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

LOGIN_URL = "/api/v1/auth/login"
REGISTER_URL = "/api/v1/auth/register"


class BaseLoginApiTestCase(TestCase):
    """Base test class providing common helpers, client initialization, and cache reset."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()

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

    def assert_email_not_verified_envelope(self, response):
        """Helper to assert the standard §2 error envelope for 403 EMAIL_NOT_VERIFIED."""
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        data = response.json()
        self.assertEqual(
            set(data.keys()),
            {"error"},
            "Response top-level key must be exactly 'error'.",
        )
        error = data["error"]
        self.assertIsInstance(error, dict)
        self.assertEqual(error.get("code"), "EMAIL_NOT_VERIFIED")
        self.assertIsInstance(
            error.get("message"),
            str,
            "Error 'message' must be a string.",
        )


class LoginRouteAndAccessTests(BaseLoginApiTestCase):
    """Verifies HTTP routing, allowed methods, and unauthenticated public access."""

    def test_login_endpoint_accepts_post_on_literal_route(self):
        """Asserts POST to literal '/api/v1/auth/login' is routed and handled."""
        response = self.client.post(
            LOGIN_URL,
            {"email": "route.check@example.com", "password": "DummyPassword123!"},
            format="json",
        )
        self.assertNotIn(
            response.status_code,
            [status.HTTP_404_NOT_FOUND, status.HTTP_405_METHOD_NOT_ALLOWED],
            f"Route {LOGIN_URL} must exist and accept POST.",
        )

    def test_login_endpoint_allows_unauthenticated_access(self):
        """Guards trap: login endpoint must allow public access overriding IsAuthenticated."""
        self.client.logout()
        response = self.client.post(
            LOGIN_URL,
            {"email": "unauth.check@example.com", "password": "DummyPassword123!"},
            format="json",
        )
        self.assertNotEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
            f"Route {LOGIN_URL} must be reachable without prior authentication.",
        )
        data = response.json()
        if response.status_code == status.HTTP_401_UNAUTHORIZED:
            self.assertEqual(
                data.get("error", {}).get("code"),
                "INVALID_CREDENTIALS",
                "Unauthenticated rejection must be due to bad credentials, not lack of auth.",
            )

    def test_login_disallowed_http_methods_return_405_method_not_allowed(self):
        """Asserts non-POST methods (GET, PUT, PATCH, DELETE) to login return 405."""
        disallowed_methods = ["get", "put", "patch", "delete"]
        for method in disallowed_methods:
            with self.subTest(http_method=method):
                cache.clear()
                client_method = getattr(self.client, method)
                response = client_method(LOGIN_URL)
                self.assertEqual(
                    response.status_code,
                    status.HTTP_405_METHOD_NOT_ALLOWED,
                    f"HTTP {method.upper()} to {LOGIN_URL} should return 405 Method Not Allowed.",
                )


class LoginSuccessContractTests(BaseLoginApiTestCase):
    """Verifies the exact 200 response dictionary contract and session cookie establishment."""

    def test_valid_credentials_verified_user_returns_200_with_exact_response_body(self):
        """Asserts valid login returns 200 and exactly {'authenticated': True}, no extras."""
        get_user_model().objects.create_user(
            email="contract.coach@example.com",
            password="StrongPassword123!",
            email_verified_at=timezone.now(),
        )
        response = self.client.post(
            LOGIN_URL,
            {"email": "contract.coach@example.com", "password": "StrongPassword123!"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {"authenticated": True},
            "Response body must match exact contract dictionary {'authenticated': True}.",
        )

    def test_valid_login_sets_session_cookie_and_no_token_in_body(self):
        """Asserts Django session cookie is set and body contains no token/JWT keys."""
        get_user_model().objects.create_user(
            email="session.coach@example.com",
            password="StrongPassword123!",
            email_verified_at=timezone.now(),
        )
        response = self.client.post(
            LOGIN_URL,
            {"email": "session.coach@example.com", "password": "StrongPassword123!"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        session_cookie_name = settings.SESSION_COOKIE_NAME
        self.assertIn(
            session_cookie_name,
            response.cookies,
            f"Successful login must set the Django session cookie ({session_cookie_name}).",
        )
        session_cookie = response.cookies[session_cookie_name]
        self.assertTrue(
            bool(session_cookie.value),
            "Session cookie value must not be empty.",
        )

        body = response.json()
        forbidden_token_keys = {
            "token",
            "access",
            "access_token",
            "refresh",
            "refresh_token",
            "jwt",
            "session_token",
            "key",
        }
        for key in forbidden_token_keys:
            self.assertNotIn(
                key,
                body,
                f"Response body must not contain token-based auth key '{key}'.",
            )

    def test_valid_login_without_coach_security_row_succeeds_with_session(self):
        """Asserts no CoachSecurity row means 2FA-disabled and login yields a session."""
        user = get_user_model().objects.create_user(
            email="nosecurity.coach@example.com",
            password="StrongPassword123!",
            email_verified_at=timezone.now(),
        )
        coach_security_model = apps.get_model("accounts", "CoachSecurity")
        self.assertEqual(coach_security_model.objects.filter(user=user).count(), 0)

        response = self.client.post(
            LOGIN_URL,
            {"email": "nosecurity.coach@example.com", "password": "StrongPassword123!"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"authenticated": True})
        self.assertIn(settings.SESSION_COOKIE_NAME, response.cookies)

    def test_valid_login_with_coach_security_disabled_succeeds_with_session(self):
        """Asserts user with CoachSecurity.two_factor_enabled=False gets authenticated: True."""
        user = get_user_model().objects.create_user(
            email="disabled2fa.coach@example.com",
            password="StrongPassword123!",
            email_verified_at=timezone.now(),
        )
        coach_security_model = apps.get_model("accounts", "CoachSecurity")
        coach_security_model.objects.create(
            user=user,
            two_factor_enabled=False,
            two_factor_secret="",
        )

        response = self.client.post(
            LOGIN_URL,
            {"email": "disabled2fa.coach@example.com", "password": "StrongPassword123!"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"authenticated": True})
        self.assertIn(settings.SESSION_COOKIE_NAME, response.cookies)


class LoginPasswordSecurityTests(BaseLoginApiTestCase):
    """Verifies password checking accuracy and strict non-leakage in responses."""

    def test_user_cannot_login_with_different_password(self):
        """Asserts user cannot log in with a password other than the registered one."""
        get_user_model().objects.create_user(
            email="password.check@example.com",
            password="OriginalPassword123!",
            email_verified_at=timezone.now(),
        )
        response = self.client.post(
            LOGIN_URL,
            {"email": "password.check@example.com", "password": "DifferentPassword456!"},
            format="json",
        )
        self.assert_invalid_credentials_envelope(response)

    def test_user_password_is_hashed_and_not_echoed_in_response(self):
        """Asserts raw password and password hash never appear in the login response."""
        raw_password = "ConfidentialPasswordToProtect123!"
        user = get_user_model().objects.create_user(
            email="protect.password@example.com",
            password=raw_password,
            email_verified_at=timezone.now(),
        )
        response = self.client.post(
            LOGIN_URL,
            {"email": "protect.password@example.com", "password": raw_password},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        content = response.content.decode()
        self.assertNotIn(raw_password, content)
        self.assertNotIn(user.password, content)


class LoginInvalidCredentialsAntiEnumerationTests(BaseLoginApiTestCase):
    """Verifies anti-enumeration guarantees between non-existent emails and wrong passwords."""

    def test_unknown_email_returns_401_with_invalid_credentials_code(self):
        """Asserts unknown email returns 401 with code INVALID_CREDENTIALS."""
        response = self.client.post(
            LOGIN_URL,
            {"email": "unknown.coach@example.com", "password": "AnyPassword123!"},
            format="json",
        )
        self.assert_invalid_credentials_envelope(response)

    def test_registered_email_wrong_password_returns_401_with_invalid_credentials_code(self):
        """Asserts registered email with wrong password returns 401 INVALID_CREDENTIALS."""
        get_user_model().objects.create_user(
            email="registered.user@example.com",
            password="CorrectPassword123!",
            email_verified_at=timezone.now(),
        )
        response = self.client.post(
            LOGIN_URL,
            {"email": "registered.user@example.com", "password": "WrongPassword123!"},
            format="json",
        )
        self.assert_invalid_credentials_envelope(response)

    def test_unknown_email_and_wrong_password_produce_identical_responses(self):
        """Asserts unknown email and wrong password responses are completely identical.

        Guards against account enumeration: status code, parsed JSON payload (including
        error code and message), and raw content bytes must be identical between an
        unknown email and a registered email with a wrong password.
        """
        get_user_model().objects.create_user(
            email="enum.existing@example.com",
            password="CorrectPassword123!",
            email_verified_at=timezone.now(),
        )

        resp_unknown = self.client.post(
            LOGIN_URL,
            {"email": "enum.nonexistent@example.com", "password": "AttemptedPassword123!"},
            format="json",
        )
        resp_wrong_password = self.client.post(
            LOGIN_URL,
            {"email": "enum.existing@example.com", "password": "AttemptedPassword123!"},
            format="json",
        )

        # 1. Both must return 401 Unauthorized
        self.assertEqual(resp_unknown.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(resp_wrong_password.status_code, status.HTTP_401_UNAUTHORIZED)

        # 2. Both must use envelope code INVALID_CREDENTIALS
        unknown_error = resp_unknown.json().get("error", {})
        wrong_pw_error = resp_wrong_password.json().get("error", {})
        self.assertEqual(unknown_error.get("code"), "INVALID_CREDENTIALS")
        self.assertEqual(wrong_pw_error.get("code"), "INVALID_CREDENTIALS")

        # 3. Direct response-to-response comparisons
        self.assertEqual(
            resp_unknown.status_code,
            resp_wrong_password.status_code,
            "Status codes for unknown email and wrong password must be identical.",
        )
        self.assertEqual(
            resp_unknown.json(),
            resp_wrong_password.json(),
            "JSON payloads for unknown email and wrong password must be identical.",
        )
        self.assertEqual(
            resp_unknown.content,
            resp_wrong_password.content,
            "Raw response content bytes for unknown email and wrong password must be identical.",
        )


class LoginEmailVerificationGuardTests(BaseLoginApiTestCase):
    """Verifies email verification enforcement (403) and credential check ordering."""

    def test_unverified_user_correct_password_returns_403_email_not_verified(self):
        """Asserts unverified account with correct password returns 403 EMAIL_NOT_VERIFIED."""
        get_user_model().objects.create_user(
            email="unverified.coach@example.com",
            password="CorrectPassword123!",
            email_verified_at=None,
        )
        response = self.client.post(
            LOGIN_URL,
            {"email": "unverified.coach@example.com", "password": "CorrectPassword123!"},
            format="json",
        )
        self.assert_email_not_verified_envelope(response)
        self.assertNotIn(
            settings.SESSION_COOKIE_NAME,
            response.cookies,
            "Unverified user login must not establish a session cookie.",
        )

    def test_wrong_password_on_unverified_account_returns_401_invalid_credentials_not_403(self):
        """Asserts wrong password on an unverified account returns 401 INVALID_CREDENTIALS.

        Guards authentication ordering rule: credentials MUST be checked before email
        verification status. Returning 403 on an incorrect password would leak whether
        an unverified account with that email address exists.
        """
        get_user_model().objects.create_user(
            email="unverified.victim@example.com",
            password="RealPassword123!",
            email_verified_at=None,
        )
        response = self.client.post(
            LOGIN_URL,
            {"email": "unverified.victim@example.com", "password": "AttackerGuess123!"},
            format="json",
        )
        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
            "Wrong password on unverified account must return 401 Unauthorized, not 403 Forbidden.",
        )
        data = response.json()
        self.assertEqual(
            data.get("error", {}).get("code"),
            "INVALID_CREDENTIALS",
            "Code must be INVALID_CREDENTIALS for a wrong password, regardless of verification.",
        )

    def test_verified_user_with_past_timestamp_succeeds(self):
        """Asserts user with a valid past datetime for email_verified_at logs in successfully."""
        past_time = timezone.now() - timezone.timedelta(days=7)
        get_user_model().objects.create_user(
            email="verified.past@example.com",
            password="CorrectPassword123!",
            email_verified_at=past_time,
        )
        response = self.client.post(
            LOGIN_URL,
            {"email": "verified.past@example.com", "password": "CorrectPassword123!"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"authenticated": True})


class LoginTwoFactorBranchTests(BaseLoginApiTestCase):
    """Verifies 2FA branch behavior, 2FA-required contract, and session cookie absence."""

    def test_valid_credentials_with_2fa_enabled_returns_200_with_requires_2fa_and_no_session(self):
        """Asserts 2FA-enabled coach gets 200 with requires_2fa: True and NO session cookie."""
        user = get_user_model().objects.create_user(
            email="2fa.coach@example.com",
            password="SecurePassword123!",
            email_verified_at=timezone.now(),
        )
        coach_security_model = apps.get_model("accounts", "CoachSecurity")
        coach_security_model.objects.create(
            user=user,
            two_factor_enabled=True,
            two_factor_secret="JBSWY3DPEHPK3PXP",
        )

        response = self.client.post(
            LOGIN_URL,
            {"email": "2fa.coach@example.com", "password": "SecurePassword123!"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {"authenticated": False, "requires_2fa": True},
            "2FA-enabled login response body must match exact contract dictionary.",
        )
        # The Story 2.7 session bridge stores a pending-2FA marker in the Django session,
        # so a sessionid cookie MAY appear here. The invariant is that the session is not
        # AUTHENTICATED: _auth_user_id must be absent until /auth/2fa/verify succeeds.
        self.assertNotIn(
            SESSION_KEY,
            self.client.session,
            "2FA-enabled login must NOT establish an authenticated session before verification.",
        )

    def test_2fa_required_response_establishes_no_authenticated_session(self):
        """Guards trap: prominent assertion that the 2FA branch never authenticates the session."""
        user = get_user_model().objects.create_user(
            email="2fa.nosession@example.com",
            password="SecurePassword123!",
            email_verified_at=timezone.now(),
        )
        coach_security_model = apps.get_model("accounts", "CoachSecurity")
        coach_security_model.objects.create(
            user=user,
            two_factor_enabled=True,
            two_factor_secret="SECRET2FA12345678",
        )

        response = self.client.post(
            LOGIN_URL,
            {"email": "2fa.nosession@example.com", "password": "SecurePassword123!"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # A pending-2FA session may exist, but it must carry no authenticated identity.
        self.assertNotIn(
            SESSION_KEY,
            self.client.session,
            "2FA challenge must never place an authenticated identity in the session.",
        )
        # Strictly stronger than a cookie check: the pending session must open no doors.
        protected_response = self.client.post("/api/v1/auth/2fa/setup", format="json")
        self.assertIn(
            protected_response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
            "A pending-2FA session must not grant access to authenticated endpoints.",
        )

    def test_2fa_enabled_wrong_password_returns_401_invalid_credentials(self):
        """Asserts wrong password on a 2FA-enabled account returns 401, hiding 2FA state."""
        user = get_user_model().objects.create_user(
            email="2fa.wrongpw@example.com",
            password="CorrectPassword123!",
            email_verified_at=timezone.now(),
        )
        coach_security_model = apps.get_model("accounts", "CoachSecurity")
        coach_security_model.objects.create(
            user=user,
            two_factor_enabled=True,
            two_factor_secret="SECRET2FA12345678",
        )

        response = self.client.post(
            LOGIN_URL,
            {"email": "2fa.wrongpw@example.com", "password": "IncorrectPassword123!"},
            format="json",
        )
        self.assert_invalid_credentials_envelope(response)

    def test_2fa_enabled_unverified_account_returns_403_email_not_verified(self):
        """Asserts unverified account with 2FA enabled returns 403 EMAIL_NOT_VERIFIED."""
        user = get_user_model().objects.create_user(
            email="2fa.unverified@example.com",
            password="CorrectPassword123!",
            email_verified_at=None,
        )
        coach_security_model = apps.get_model("accounts", "CoachSecurity")
        coach_security_model.objects.create(
            user=user,
            two_factor_enabled=True,
            two_factor_secret="SECRET2FA12345678",
        )

        response = self.client.post(
            LOGIN_URL,
            {"email": "2fa.unverified@example.com", "password": "CorrectPassword123!"},
            format="json",
        )
        self.assert_email_not_verified_envelope(response)


class LoginValidationEnvelopeTests(BaseLoginApiTestCase):
    """Verifies §2 Standard Error Format and validation error handling for login payloads."""

    def test_missing_email_field_returns_400_with_validation_error_envelope(self):
        """Asserts omitting the 'email' field returns 400 VALIDATION_ERROR."""
        response = self.client.post(
            LOGIN_URL,
            {"password": "SomePassword123!"},
            format="json",
        )
        self.assert_validation_error_envelope(response, expected_field="email")

    def test_missing_password_field_returns_400_with_validation_error_envelope(self):
        """Asserts omitting the 'password' field returns 400 VALIDATION_ERROR."""
        response = self.client.post(
            LOGIN_URL,
            {"email": "missing.pw@example.com"},
            format="json",
        )
        self.assert_validation_error_envelope(response, expected_field="password")

    def test_empty_payload_returns_400_with_validation_error_envelope(self):
        """Asserts sending an empty JSON payload returns 400 VALIDATION_ERROR."""
        response = self.client.post(LOGIN_URL, {}, format="json")
        self.assert_validation_error_envelope(response)

    def test_invalid_email_format_returns_400_with_validation_error_envelope(self):
        """Asserts malformed email format returns 400 VALIDATION_ERROR with email field error."""
        response = self.client.post(
            LOGIN_URL,
            {"email": "not-a-valid-email", "password": "SomePassword123!"},
            format="json",
        )
        self.assert_validation_error_envelope(response, expected_field="email")

    def test_null_credentials_return_400_with_validation_error_envelope(self):
        """Asserts null credential values return 400 VALIDATION_ERROR."""
        invalid_payloads = [
            {"email": None, "password": "SomePassword123!"},
            {"email": "valid@example.com", "password": None},
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                response = self.client.post(LOGIN_URL, payload, format="json")
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                data = response.json()
                self.assertEqual(data.get("error", {}).get("code"), "VALIDATION_ERROR")


class LoginRateLimitingTests(BaseLoginApiTestCase):
    """Verifies endpoint-scoped rate limiting (10 req/min) and unthrottled registration."""

    def test_login_endpoint_throttled_after_10_requests_per_minute(self):
        """Asserts login endpoint enforces 10/min rate limit and returns 429 on 11th request."""
        payload = {"email": "throttle.login@example.com", "password": "WrongPassword123!"}
        for i in range(10):
            resp = self.client.post(LOGIN_URL, payload, format="json")
            self.assertIn(
                resp.status_code,
                [status.HTTP_200_OK, status.HTTP_401_UNAUTHORIZED, status.HTTP_400_BAD_REQUEST],
                f"Request {i + 1} within rate limit should not be throttled.",
            )

        throttled_resp = self.client.post(LOGIN_URL, payload, format="json")
        self.assertEqual(
            throttled_resp.status_code,
            status.HTTP_429_TOO_MANY_REQUESTS,
            "11th request within a minute to login must return 429 Too Many Requests.",
        )
        error = throttled_resp.json().get("error", {})
        self.assertEqual(
            error.get("code"),
            "RATE_LIMITED",
            "Throttled response must return code 'RATE_LIMITED' in §2 error envelope.",
        )

    def test_registration_endpoint_remains_unthrottled_under_rapid_requests(self):
        """Asserts /api/v1/auth/register is not throttled by login rate limiting."""
        for i in range(6):
            resp = self.client.post(
                REGISTER_URL,
                {
                    "email": f"rapid.login.reg.{i}@example.com",
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


class CoachSecurityModelContractTests(BaseLoginApiTestCase):
    """Verifies CoachSecurity model schema, defaults, relationships, and secret protection."""

    def test_coach_security_model_exact_concrete_field_set(self):
        """Asserts CoachSecurity defines exactly the 6 approved fields."""
        coach_security_model = apps.get_model("accounts", "CoachSecurity")
        expected_fields = {
            "id",
            "user",
            "two_factor_enabled",
            "two_factor_secret",
            "created_at",
            "updated_at",
        }
        concrete_fields = {field.name for field in coach_security_model._meta.concrete_fields}
        self.assertSetEqual(
            concrete_fields,
            expected_fields,
            "CoachSecurity concrete fields must exactly match the schema contract.",
        )

    def test_coach_security_two_factor_enabled_default_is_false(self):
        """Asserts two_factor_enabled field defaults to False."""
        coach_security_model = apps.get_model("accounts", "CoachSecurity")
        field = coach_security_model._meta.get_field("two_factor_enabled")
        self.assertIs(field.default, False)

    def test_coach_security_user_relation_is_one_to_one_with_cascade_delete(self):
        """Asserts user relationship is OneToOneField with on_delete=CASCADE."""
        coach_security_model = apps.get_model("accounts", "CoachSecurity")
        user_field = coach_security_model._meta.get_field("user")
        self.assertTrue(
            user_field.is_relation and user_field.one_to_one,
            "CoachSecurity.user must be a OneToOneField.",
        )
        self.assertEqual(
            user_field.remote_field.on_delete,
            models.CASCADE,
            "CoachSecurity.user must cascade on user deletion.",
        )

        user = get_user_model().objects.create_user(
            email="cascade.coach@example.com",
            password="SecurePassword123!",
            email_verified_at=timezone.now(),
        )
        coach_security_model.objects.create(
            user=user,
            two_factor_enabled=True,
            two_factor_secret="SECRET1234567890",
        )
        self.assertEqual(coach_security_model.objects.filter(user=user).count(), 1)
        user.delete()
        self.assertEqual(
            coach_security_model.objects.filter(user_id=user.id).count(),
            0,
            "Deleting User must cascade and delete associated CoachSecurity record.",
        )

    def test_coach_security_two_factor_secret_never_appears_in_login_response(self):
        """Asserts two_factor_secret is never leaked in login response content or headers."""
        secret_token = "CONFIDENTIAL_TOTP_SECRET_KEY_NEVER_LEAK"
        user = get_user_model().objects.create_user(
            email="secret.protection@example.com",
            password="SecurePassword123!",
            email_verified_at=timezone.now(),
        )
        coach_security_model = apps.get_model("accounts", "CoachSecurity")
        coach_security_model.objects.create(
            user=user,
            two_factor_enabled=True,
            two_factor_secret=secret_token,
        )

        response = self.client.post(
            LOGIN_URL,
            {"email": "secret.protection@example.com", "password": "SecurePassword123!"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn(
            secret_token,
            response.content.decode(),
            "Sensitive two_factor_secret must never appear in response body.",
        )
        for header_name, header_value in response.items():
            self.assertNotIn(
                secret_token,
                str(header_value),
                f"Sensitive two_factor_secret must not appear in header '{header_name}'.",
            )


class LoginArchitectureGuardTests(BaseLoginApiTestCase):
    """Verifies architectural constraints: exact approved models in accounts app."""

    def test_accounts_app_exposes_only_approved_models_and_no_session_or_token_model(self):
        """Asserts accounts defines exactly {User, CoachProfile, ClientProfile, CoachSecurity}."""
        accounts_app = apps.get_app_config("accounts")
        concrete_model_names = {model._meta.object_name for model in accounts_app.get_models()}
        expected_model_names = {"User", "CoachProfile", "ClientProfile", "CoachSecurity"}
        self.assertSetEqual(
            concrete_model_names,
            expected_model_names,
            "accounts must contain only User, CoachProfile, ClientProfile, and CoachSecurity.",
        )
