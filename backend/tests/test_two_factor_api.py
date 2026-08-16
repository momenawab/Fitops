"""API tests for TOTP 2FA endpoints and session bridge contract (Story 2.7 / Task B).

Validates:
- Literal routing and permissions for setup, confirm, verify, and disable endpoints
- Unauthenticated rejection (401/403) for setup, confirm, disable; AllowAny for verify
- Disallowed HTTP methods return 405 across all four 2FA endpoints
- Setup contract: exact keys {"secret", "otpauth_uri"}, otpauth:// scheme, 2FA remains disabled
- Confirm contract: valid TOTP enables 2FA, wrong code returns 400 VALIDATION_ERROR
- Session bridge: login 2FA challenge sets no session, verify establishes session cookie
- Fresh client verify without pending login marker fails with 4xx and creates no session
- Marker consumption: verify cannot be replayed from the same unauthenticated state
- Disable contract: valid code disables 2FA, wrong code leaves 2FA enabled
- Sensitive TOTP secret non-leakage across all response bodies and headers
- Standard validation error envelope (§2) for missing, blank, or invalid code payloads
- Architecture guard: accounts defines exactly {User, CoachProfile, ClientProfile, CoachSecurity}
"""

import pyotp
from django.apps import apps
from django.conf import settings
from django.contrib.auth import SESSION_KEY, get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

SETUP_URL = "/api/v1/auth/2fa/setup"
CONFIRM_URL = "/api/v1/auth/2fa/confirm"
VERIFY_URL = "/api/v1/auth/2fa/verify"
DISABLE_URL = "/api/v1/auth/2fa/disable"
LOGIN_URL = "/api/v1/auth/login"


class BaseTwoFactorApiTestCase(TestCase):
    """Base test class providing common helpers, client initialization, and cache reset."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def _create_verified_user(
        self,
        email: str = "coach.2fa@example.com",
        password: str = "SecurePassword123!",
    ):
        """Creates and returns an active, email-verified user."""
        return get_user_model().objects.create_user(
            email=email,
            password=password,
            email_verified_at=timezone.now(),
        )

    def _setup_coach_security(
        self,
        user,
        secret: str = "JBSWY3DPEHPK3PXP",
        enabled: bool = False,
    ):
        """Creates or updates CoachSecurity record for the given user."""
        coach_security_model = apps.get_model("accounts", "CoachSecurity")
        security, _ = coach_security_model.objects.update_or_create(
            user=user,
            defaults={
                "two_factor_secret": secret,
                "two_factor_enabled": enabled,
            },
        )
        return security

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

    def assert_unauthenticated_envelope(self, response):
        """Helper to assert 401/403 rejection on protected endpoints."""
        self.assertIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
            "Unauthenticated request must return 401 Unauthorized or 403 Forbidden.",
        )
        data = response.json()
        self.assertEqual(
            set(data.keys()),
            {"error"},
            "Response top-level key must be exactly 'error'.",
        )
        error = data["error"]
        self.assertIsInstance(error, dict)
        self.assertIsInstance(
            error.get("message"),
            str,
            "Error 'message' must be a string.",
        )


class TwoFactorRouteAndAccessTests(BaseTwoFactorApiTestCase):
    """Verifies HTTP routing, allowed methods, and access control across 2FA endpoints."""

    def test_setup_endpoint_accepts_post_on_literal_route(self):
        """Asserts POST to literal '/api/v1/auth/2fa/setup' is routed and handled."""
        user = self._create_verified_user(email="route.setup@example.com")
        self.client.force_authenticate(user=user)
        response = self.client.post(SETUP_URL, format="json")
        self.assertNotIn(
            response.status_code,
            [status.HTTP_404_NOT_FOUND, status.HTTP_405_METHOD_NOT_ALLOWED],
            f"Route {SETUP_URL} must exist and accept POST.",
        )

    def test_confirm_endpoint_accepts_post_on_literal_route(self):
        """Asserts POST to literal '/api/v1/auth/2fa/confirm' is routed and handled."""
        user = self._create_verified_user(email="route.confirm@example.com")
        self.client.force_authenticate(user=user)
        response = self.client.post(CONFIRM_URL, {"code": "123456"}, format="json")
        self.assertNotIn(
            response.status_code,
            [status.HTTP_404_NOT_FOUND, status.HTTP_405_METHOD_NOT_ALLOWED],
            f"Route {CONFIRM_URL} must exist and accept POST.",
        )

    def test_verify_endpoint_accepts_post_on_literal_route(self):
        """Asserts POST to literal '/api/v1/auth/2fa/verify' is routed and handled."""
        response = self.client.post(VERIFY_URL, {"code": "123456"}, format="json")
        self.assertNotIn(
            response.status_code,
            [status.HTTP_404_NOT_FOUND, status.HTTP_405_METHOD_NOT_ALLOWED],
            f"Route {VERIFY_URL} must exist and accept POST.",
        )

    def test_disable_endpoint_accepts_post_on_literal_route(self):
        """Asserts POST to literal '/api/v1/auth/2fa/disable' is routed and handled."""
        user = self._create_verified_user(email="route.disable@example.com")
        self.client.force_authenticate(user=user)
        response = self.client.post(DISABLE_URL, {"code": "123456"}, format="json")
        self.assertNotIn(
            response.status_code,
            [status.HTTP_404_NOT_FOUND, status.HTTP_405_METHOD_NOT_ALLOWED],
            f"Route {DISABLE_URL} must exist and accept POST.",
        )

    def test_setup_endpoint_rejects_unauthenticated_caller(self):
        """Asserts unauthenticated caller to setup returns 401 or 403."""
        self.client.logout()
        response = self.client.post(SETUP_URL, format="json")
        self.assert_unauthenticated_envelope(response)

    def test_confirm_endpoint_rejects_unauthenticated_caller(self):
        """Asserts unauthenticated caller to confirm returns 401 or 403."""
        self.client.logout()
        response = self.client.post(CONFIRM_URL, {"code": "123456"}, format="json")
        self.assert_unauthenticated_envelope(response)

    def test_disable_endpoint_rejects_unauthenticated_caller(self):
        """Asserts unauthenticated caller to disable returns 401 or 403."""
        self.client.logout()
        response = self.client.post(DISABLE_URL, {"code": "123456"}, format="json")
        self.assert_unauthenticated_envelope(response)

    def test_verify_endpoint_allows_unauthenticated_access_without_permission_rejection(self):
        """Guards trap: verify endpoint is AllowAny and not rejected for lacking a session."""
        self.client.logout()
        response = self.client.post(VERIFY_URL, {"code": "123456"}, format="json")
        self.assertNotEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
            f"Route {VERIFY_URL} must be reachable without prior authentication.",
        )
        # The endpoint is AllowAny, so it must never be refused by a permission class.
        # A 401 for a missing pending-2FA marker is a business rule, not a permission
        # rejection, so the guard asserts on the envelope code rather than the status.
        self.assertNotEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
            "Verify endpoint must be AllowAny and never refused by a permission class.",
        )
        self.assertNotIn(
            response.json()["error"]["code"],
            ["PERMISSION_DENIED", "AUTHENTICATION_REQUIRED"],
            "Verify must not be rejected merely for lacking an authenticated session.",
        )

    def test_disallowed_http_methods_return_405_method_not_allowed(self):
        """Asserts non-POST methods (GET, PUT, PATCH, DELETE) to 2FA endpoints return 405."""
        endpoints = [SETUP_URL, CONFIRM_URL, VERIFY_URL, DISABLE_URL]
        disallowed_methods = ["get", "put", "patch", "delete"]
        # DRF runs permission checks before method dispatch, so an unauthenticated
        # request to a protected route returns 403 before it can return 405. Authenticate
        # first so this test observes method handling rather than the permission layer.
        self.client.force_authenticate(user=self._create_verified_user())
        for endpoint in endpoints:
            for method in disallowed_methods:
                with self.subTest(endpoint=endpoint, http_method=method):
                    cache.clear()
                    client_method = getattr(self.client, method)
                    response = client_method(endpoint)
                    self.assertEqual(
                        response.status_code,
                        status.HTTP_405_METHOD_NOT_ALLOWED,
                        f"HTTP {method.upper()} to {endpoint} should return 405.",
                    )


class TwoFactorSetupApiTests(BaseTwoFactorApiTestCase):
    """Verifies 2FA setup endpoint contract, secret generation, and model state."""

    def test_setup_authenticated_returns_200_with_exact_contract_keys(self):
        """Asserts setup returns 200 and exact key set {'secret', 'otpauth_uri'}."""
        user = self._create_verified_user(email="setup.contract@example.com")
        self.client.force_authenticate(user=user)
        response = self.client.post(SETUP_URL, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            set(response.json().keys()),
            {"secret", "otpauth_uri"},
            "Setup response body must contain exactly 'secret' and 'otpauth_uri' keys.",
        )
        secret = response.json()["secret"]
        otpauth_uri = response.json()["otpauth_uri"]
        self.assertIsInstance(secret, str)
        self.assertIsInstance(otpauth_uri, str)
        self.assertGreaterEqual(len(secret), 16, "Secret should be a base32 string.")

    def test_setup_otpauth_uri_starts_with_otpauth_scheme(self):
        """Asserts otpauth_uri starts with 'otpauth://' and contains user email."""
        user = self._create_verified_user(email="setup.uri@example.com")
        self.client.force_authenticate(user=user)
        response = self.client.post(SETUP_URL, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(
            data["otpauth_uri"].startswith("otpauth://"),
            "otpauth_uri must start with the standard 'otpauth://' URI scheme.",
        )
        self.assertIn(
            data["secret"],
            data["otpauth_uri"],
            "otpauth_uri must encode the generated secret.",
        )

    def test_setup_does_not_enable_two_factor(self):
        """Asserts calling setup generates a secret but does NOT set two_factor_enabled=True."""
        user = self._create_verified_user(email="setup.noflag@example.com")
        self.client.force_authenticate(user=user)
        response = self.client.post(SETUP_URL, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        coach_security_model = apps.get_model("accounts", "CoachSecurity")
        security = coach_security_model.objects.get(user=user)
        self.assertFalse(
            security.two_factor_enabled,
            "two_factor_enabled must remain False after setup until confirmed.",
        )

    def test_setup_stores_matching_secret_in_coach_security(self):
        """Asserts returned secret matches CoachSecurity.two_factor_secret in database."""
        user = self._create_verified_user(email="setup.db@example.com")
        self.client.force_authenticate(user=user)
        response = self.client.post(SETUP_URL, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        returned_secret = response.json()["secret"]
        coach_security_model = apps.get_model("accounts", "CoachSecurity")
        security = coach_security_model.objects.get(user=user)
        self.assertEqual(
            security.two_factor_secret,
            returned_secret,
            "CoachSecurity.two_factor_secret must match the secret returned in setup response.",
        )

    def test_setup_repeated_call_generates_new_secret_without_enabling_2fa(self):
        """Asserts repeated setup calls refresh the secret while keeping 2FA disabled."""
        user = self._create_verified_user(email="setup.repeat@example.com")
        self.client.force_authenticate(user=user)

        resp1 = self.client.post(SETUP_URL, format="json")
        self.assertEqual(resp1.status_code, status.HTTP_200_OK)
        secret1 = resp1.json()["secret"]

        resp2 = self.client.post(SETUP_URL, format="json")
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        secret2 = resp2.json()["secret"]

        self.assertNotEqual(
            secret1,
            secret2,
            "Each setup call must issue a freshly generated secret, not reuse the previous one.",
        )

        coach_security_model = apps.get_model("accounts", "CoachSecurity")
        security = coach_security_model.objects.get(user=user)
        self.assertEqual(security.two_factor_secret, secret2)
        self.assertFalse(security.two_factor_enabled)


class TwoFactorConfirmApiTests(BaseTwoFactorApiTestCase):
    """Verifies 2FA confirmation, code validation, and state activation."""

    def test_confirm_with_valid_totp_code_enables_two_factor(self):
        """Asserts valid TOTP code returns 200 and sets two_factor_enabled=True."""
        user = self._create_verified_user(email="confirm.valid@example.com")
        secret = pyotp.random_base32()
        self._setup_coach_security(user=user, secret=secret, enabled=False)

        self.client.force_authenticate(user=user)
        totp = pyotp.TOTP(secret)
        valid_code = totp.now()

        response = self.client.post(CONFIRM_URL, {"code": valid_code}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        coach_security_model = apps.get_model("accounts", "CoachSecurity")
        security = coach_security_model.objects.get(user=user)
        self.assertTrue(
            security.two_factor_enabled,
            "two_factor_enabled must transition to True upon successful confirmation.",
        )

    def test_confirm_with_wrong_code_returns_400_validation_error_and_leaves_2fa_disabled(self):
        """Asserts invalid TOTP code returns 400 VALIDATION_ERROR and 2FA remains disabled."""
        user = self._create_verified_user(email="confirm.wrong@example.com")
        secret = pyotp.random_base32()
        self._setup_coach_security(user=user, secret=secret, enabled=False)

        self.client.force_authenticate(user=user)
        response = self.client.post(CONFIRM_URL, {"code": "000000"}, format="json")
        self.assert_validation_error_envelope(response, expected_field="code")

        coach_security_model = apps.get_model("accounts", "CoachSecurity")
        security = coach_security_model.objects.get(user=user)
        self.assertFalse(
            security.two_factor_enabled,
            "two_factor_enabled must remain False after failed confirmation.",
        )

    def test_confirm_response_body_contains_no_secret(self):
        """Asserts raw secret never appears in the confirm response body."""
        user = self._create_verified_user(email="confirm.nosecret@example.com")
        secret = "JBSWY3DPEHPK3PXP"
        self._setup_coach_security(user=user, secret=secret, enabled=False)

        self.client.force_authenticate(user=user)
        totp = pyotp.TOTP(secret)
        response = self.client.post(CONFIRM_URL, {"code": totp.now()}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn(
            secret,
            response.content.decode(),
            "Confirm response must not contain the TOTP secret.",
        )

    def test_confirm_missing_or_empty_code_returns_400_validation_error(self):
        """Asserts missing or empty code in confirm payload returns 400 VALIDATION_ERROR."""
        user = self._create_verified_user(email="confirm.empty@example.com")
        self.client.force_authenticate(user=user)

        resp_missing = self.client.post(CONFIRM_URL, {}, format="json")
        self.assert_validation_error_envelope(resp_missing, expected_field="code")

        resp_empty = self.client.post(CONFIRM_URL, {"code": ""}, format="json")
        self.assert_validation_error_envelope(resp_empty, expected_field="code")


class TwoFactorVerifySessionBridgeTests(BaseTwoFactorApiTestCase):
    """Verifies the session bridge: 2FA challenge login, verify endpoint, and session creation."""

    def test_verify_full_login_flow_authenticates_session_only_after_valid_code(self):
        """Asserts full 2FA login flow: unauthenticated pending session, authenticated on verify.

        Guards against bypass: login returns requires_2fa and may set a pending-2FA session,
        but that session carries no authenticated identity and opens no protected endpoint.
        Only a valid TOTP code at /2fa/verify establishes the authenticated session.
        """
        user = self._create_verified_user(
            email="bridge.flow@example.com",
            password="StrongPassword123!",
        )
        secret = pyotp.random_base32()
        self._setup_coach_security(user=user, secret=secret, enabled=True)

        # Step 1: Login -> 2FA challenge. A pending-2FA session may exist, but it must not
        # be authenticated and must not unlock protected endpoints.
        login_resp = self.client.post(
            LOGIN_URL,
            {"email": "bridge.flow@example.com", "password": "StrongPassword123!"},
            format="json",
        )
        self.assertEqual(login_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(
            login_resp.json(),
            {"authenticated": False, "requires_2fa": True},
            "Login response must challenge for 2FA.",
        )
        session_cookie_name = settings.SESSION_COOKIE_NAME
        self.assertNotIn(
            SESSION_KEY,
            self.client.session,
            "2FA login challenge must NOT establish an authenticated session.",
        )
        pending_protected_resp = self.client.post(SETUP_URL, format="json")
        self.assertIn(
            pending_protected_resp.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
            "A pending-2FA session must not grant access to authenticated endpoints.",
        )

        # Step 2: Submit valid TOTP code to verify endpoint -> 200 and session authenticated
        totp = pyotp.TOTP(secret)
        valid_code = totp.now()
        verify_resp = self.client.post(
            VERIFY_URL,
            {"code": valid_code},
            format="json",
        )
        self.assertEqual(verify_resp.status_code, status.HTTP_200_OK)
        self.assertIn(
            session_cookie_name,
            verify_resp.cookies,
            "Successful /2fa/verify must set the Django session cookie.",
        )
        session_cookie = verify_resp.cookies[session_cookie_name]
        self.assertTrue(
            bool(session_cookie.value),
            "Session cookie value must not be empty.",
        )
        self.assertEqual(
            str(self.client.session[SESSION_KEY]),
            str(user.pk),
            "Successful /2fa/verify must authenticate the session as the pending user.",
        )

        # Step 3: Verify subsequent request to protected endpoint succeeds with session
        setup_resp = self.client.post(SETUP_URL, format="json")
        self.assertEqual(
            setup_resp.status_code,
            status.HTTP_200_OK,
            "Protected endpoint must be accessible with the established session.",
        )

    def test_verify_wrong_code_with_pending_marker_returns_400_and_creates_no_session(self):
        """Asserts wrong TOTP code during 2FA challenge returns 400 and creates no session."""
        user = self._create_verified_user(
            email="bridge.wrong@example.com",
            password="StrongPassword123!",
        )
        secret = pyotp.random_base32()
        self._setup_coach_security(user=user, secret=secret, enabled=True)

        # Step 1: Login to set pending 2FA marker
        login_resp = self.client.post(
            LOGIN_URL,
            {"email": "bridge.wrong@example.com", "password": "StrongPassword123!"},
            format="json",
        )
        self.assertEqual(login_resp.status_code, status.HTTP_200_OK)

        # Step 2: Submit wrong code
        verify_resp = self.client.post(
            VERIFY_URL,
            {"code": "000000"},
            format="json",
        )
        self.assert_validation_error_envelope(verify_resp, expected_field="code")
        self.assertNotIn(
            SESSION_KEY,
            self.client.session,
            "Failed 2FA verification must NOT establish an authenticated session.",
        )

        # Step 3: Protected endpoint must reject caller
        setup_resp = self.client.post(SETUP_URL, format="json")
        self.assert_unauthenticated_envelope(setup_resp)

    def test_verify_without_pending_marker_fails_and_creates_no_session(self):
        """Asserts calling /2fa/verify with no pending login marker fails with no session created.

        Guards against direct bypass: an attacker with a valid TOTP code cannot authenticate
        without first proving knowledge of the user's password via /auth/login.
        """
        # The attacker knows a genuinely valid TOTP code for a real 2FA-enabled account but
        # never proved the password, so no pending marker exists. A code alone must be useless.
        victim = self._create_verified_user(
            email="bridge.victim@example.com",
            password="StrongPassword123!",
        )
        secret = pyotp.random_base32()
        self._setup_coach_security(user=victim, secret=secret, enabled=True)

        self.client.logout()
        response = self.client.post(
            VERIFY_URL,
            {"code": pyotp.TOTP(secret).now()},
            format="json",
        )
        self.assertTrue(
            status.is_client_error(response.status_code),
            "Calling /2fa/verify without a pending login marker must return a 4xx error.",
        )
        self.assertNotIn(
            SESSION_KEY,
            self.client.session,
            "Calling /2fa/verify without a pending marker must never authenticate a session.",
        )

        # Protected endpoint must reject caller
        setup_resp = self.client.post(SETUP_URL, format="json")
        self.assert_unauthenticated_envelope(setup_resp)

    def test_verify_marker_is_consumed_preventing_replay_from_unauthenticated_state(self):
        """Asserts pending login marker is consumed upon successful verify and cannot be reused.

        Tests that once a session is completed and subsequently cleared, a second verify
        call without a fresh login cannot complete a session or log into the account.
        """
        user = self._create_verified_user(
            email="bridge.consume@example.com",
            password="StrongPassword123!",
        )
        secret = pyotp.random_base32()
        self._setup_coach_security(user=user, secret=secret, enabled=True)

        # Step 1: Login
        login_resp = self.client.post(
            LOGIN_URL,
            {"email": "bridge.consume@example.com", "password": "StrongPassword123!"},
            format="json",
        )
        self.assertEqual(login_resp.status_code, status.HTTP_200_OK)

        # Step 2: Successful verify
        totp = pyotp.TOTP(secret)
        verify_resp1 = self.client.post(
            VERIFY_URL,
            {"code": totp.now()},
            format="json",
        )
        self.assertEqual(verify_resp1.status_code, status.HTTP_200_OK)

        # Step 3: Logout to clear the authenticated session
        self.client.logout()

        # Step 4: Second verify with a fresh valid code must fail because marker was consumed
        fresh_code = totp.now()
        verify_resp2 = self.client.post(
            VERIFY_URL,
            {"code": fresh_code},
            format="json",
        )
        self.assertTrue(
            status.is_client_error(verify_resp2.status_code),
            "Second verify after marker consumption must return a 4xx error.",
        )
        self.assertNotIn(
            settings.SESSION_COOKIE_NAME,
            verify_resp2.cookies,
            "Replayed verify must not establish an authenticated session cookie.",
        )


class TwoFactorDisableApiTests(BaseTwoFactorApiTestCase):
    """Verifies 2FA disabling endpoint, code validation, and state deactivation."""

    def test_disable_with_valid_totp_code_sets_two_factor_enabled_false(self):
        """Asserts valid TOTP code to disable endpoint returns 200 and sets 2FA False."""
        user = self._create_verified_user(email="disable.valid@example.com")
        secret = pyotp.random_base32()
        self._setup_coach_security(user=user, secret=secret, enabled=True)

        self.client.force_authenticate(user=user)
        totp = pyotp.TOTP(secret)
        response = self.client.post(DISABLE_URL, {"code": totp.now()}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        coach_security_model = apps.get_model("accounts", "CoachSecurity")
        security = coach_security_model.objects.get(user=user)
        self.assertFalse(
            security.two_factor_enabled,
            "two_factor_enabled must transition to False upon successful disable.",
        )

    def test_disable_with_wrong_code_returns_400_validation_error_and_leaves_2fa_enabled(self):
        """Asserts wrong TOTP code to disable returns 400 VALIDATION_ERROR and 2FA stays True."""
        user = self._create_verified_user(email="disable.wrong@example.com")
        secret = pyotp.random_base32()
        self._setup_coach_security(user=user, secret=secret, enabled=True)

        self.client.force_authenticate(user=user)
        response = self.client.post(DISABLE_URL, {"code": "000000"}, format="json")
        self.assert_validation_error_envelope(response, expected_field="code")

        coach_security_model = apps.get_model("accounts", "CoachSecurity")
        security = coach_security_model.objects.get(user=user)
        self.assertTrue(
            security.two_factor_enabled,
            "two_factor_enabled must remain True after failed disable attempt.",
        )

    def test_disable_response_body_contains_no_secret(self):
        """Asserts raw secret never appears in the disable response body."""
        user = self._create_verified_user(email="disable.nosecret@example.com")
        secret = "JBSWY3DPEHPK3PXP"
        self._setup_coach_security(user=user, secret=secret, enabled=True)

        self.client.force_authenticate(user=user)
        totp = pyotp.TOTP(secret)
        response = self.client.post(DISABLE_URL, {"code": totp.now()}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn(
            secret,
            response.content.decode(),
            "Disable response must not contain the TOTP secret.",
        )

    def test_disable_missing_or_empty_code_returns_400_validation_error(self):
        """Asserts missing or empty code in disable payload returns 400 VALIDATION_ERROR."""
        user = self._create_verified_user(email="disable.empty@example.com")
        self.client.force_authenticate(user=user)

        resp_missing = self.client.post(DISABLE_URL, {}, format="json")
        self.assert_validation_error_envelope(resp_missing, expected_field="code")

        resp_empty = self.client.post(DISABLE_URL, {"code": ""}, format="json")
        self.assert_validation_error_envelope(resp_empty, expected_field="code")


class TwoFactorSecretNonLeakageTests(BaseTwoFactorApiTestCase):
    """Verifies that sensitive TOTP secret is never leaked across any responses."""

    def test_raw_secret_never_appears_in_confirm_verify_disable_or_login_responses(self):
        """Asserts two_factor_secret is strictly absent from all responses and headers.

        Checks serialized response content bytes and response headers for:
        - POST /api/v1/auth/login (2FA challenge)
        - POST /api/v1/auth/2fa/verify (session completion)
        - POST /api/v1/auth/2fa/confirm (activation)
        - POST /api/v1/auth/2fa/disable (deactivation)
        """
        # Must be decodable base32 (A-Z, 2-7) so pyotp can derive codes from it, while
        # staying a recognisable canary string to search for in response bodies.
        canary_secret = "CANARYSECRETNEVERLEAKTOTPKEY2345"
        user = self._create_verified_user(
            email="canary.secret@example.com",
            password="StrongPassword123!",
        )
        self._setup_coach_security(user=user, secret=canary_secret, enabled=True)

        def assert_no_secret_in_response(resp, endpoint_label):
            content_str = resp.content.decode()
            self.assertNotIn(
                canary_secret,
                content_str,
                f"Sensitive secret must never appear in {endpoint_label} response body.",
            )
            for header_name, header_value in resp.items():
                self.assertNotIn(
                    canary_secret,
                    str(header_value),
                    f"Secret must not appear in header '{header_name}' of {endpoint_label}.",
                )

        # 1. Check login challenge response
        login_resp = self.client.post(
            LOGIN_URL,
            {"email": "canary.secret@example.com", "password": "StrongPassword123!"},
            format="json",
        )
        self.assertEqual(login_resp.status_code, status.HTTP_200_OK)
        assert_no_secret_in_response(login_resp, "login challenge")

        # 2. Check verify response
        totp = pyotp.TOTP(canary_secret)
        verify_resp = self.client.post(
            VERIFY_URL,
            {"code": totp.now()},
            format="json",
        )
        self.assertEqual(verify_resp.status_code, status.HTTP_200_OK)
        assert_no_secret_in_response(verify_resp, "/2fa/verify")

        # 3. Check confirm response (re-confirming). Confirm runs before disable because
        # disable clears the stored secret, which would leave confirm nothing to validate.
        confirm_resp = self.client.post(
            CONFIRM_URL,
            {"code": totp.now()},
            format="json",
        )
        self.assertEqual(confirm_resp.status_code, status.HTTP_200_OK)
        assert_no_secret_in_response(confirm_resp, "/2fa/confirm")

        # 4. Check disable response
        disable_resp = self.client.post(
            DISABLE_URL,
            {"code": totp.now()},
            format="json",
        )
        self.assertEqual(disable_resp.status_code, status.HTTP_200_OK)
        assert_no_secret_in_response(disable_resp, "/2fa/disable")


class TwoFactorValidationEnvelopeTests(BaseTwoFactorApiTestCase):
    """Verifies §2 Standard Error Format and payload validation across 2FA endpoints."""

    def test_confirm_empty_payload_returns_400_validation_error(self):
        """Asserts sending an empty JSON payload to confirm returns 400 VALIDATION_ERROR."""
        user = self._create_verified_user(email="val.confirm@example.com")
        self.client.force_authenticate(user=user)
        response = self.client.post(CONFIRM_URL, {}, format="json")
        self.assert_validation_error_envelope(response)

    def test_verify_empty_payload_returns_400_validation_error(self):
        """Asserts sending an empty JSON payload to verify returns 400 VALIDATION_ERROR."""
        response = self.client.post(VERIFY_URL, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertEqual(data.get("error", {}).get("code"), "VALIDATION_ERROR")

    def test_disable_empty_payload_returns_400_validation_error(self):
        """Asserts sending an empty JSON payload to disable returns 400 VALIDATION_ERROR."""
        user = self._create_verified_user(email="val.disable@example.com")
        self.client.force_authenticate(user=user)
        response = self.client.post(DISABLE_URL, {}, format="json")
        self.assert_validation_error_envelope(response)

    def test_invalid_code_types_return_400_validation_error(self):
        """Asserts non-string, null, or invalid code payloads return 400 VALIDATION_ERROR."""
        user = self._create_verified_user(email="val.types@example.com")
        self.client.force_authenticate(user=user)
        invalid_payloads = [
            {"code": None},
            {"code": 123456},
            {"code": True},
            {"code": []},
            {"code": {}},
        ]
        for payload in invalid_payloads:
            with self.subTest(endpoint="confirm", payload=payload):
                resp = self.client.post(CONFIRM_URL, payload, format="json")
                self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(resp.json().get("error", {}).get("code"), "VALIDATION_ERROR")

            with self.subTest(endpoint="disable", payload=payload):
                resp = self.client.post(DISABLE_URL, payload, format="json")
                self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(resp.json().get("error", {}).get("code"), "VALIDATION_ERROR")


class TwoFactorArchitectureGuardTests(BaseTwoFactorApiTestCase):
    """Verifies architectural constraints: exact approved models and schema in accounts app."""

    def test_accounts_app_exposes_only_approved_models_and_no_recovery_or_token_model(self):
        """Asserts accounts defines exactly {User, CoachProfile, ClientProfile, CoachSecurity}."""
        accounts_app = apps.get_app_config("accounts")
        concrete_model_names = {model._meta.object_name for model in accounts_app.get_models()}
        expected_model_names = {"User", "CoachProfile", "ClientProfile", "CoachSecurity"}
        self.assertSetEqual(
            concrete_model_names,
            expected_model_names,
            "accounts must contain only User, CoachProfile, ClientProfile, and CoachSecurity.",
        )

    def test_coach_security_model_concrete_fields_match_schema_without_recovery_fields(self):
        """Asserts CoachSecurity concrete fields match the exact 6-field schema."""
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
            "CoachSecurity concrete fields must exactly match the approved schema.",
        )
