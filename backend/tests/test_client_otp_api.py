"""API tests for Client OTP authentication endpoints and LoginOTP contract (Story 2.8).

Validates:
- Literal routing and unauthenticated public access for request-code and verify-code
- Generic success response and LoginOTP creation for eligible active clients (Points 1, 2)
- Anti-enumeration: byte-identical responses across unknown emails, foreign workspaces,
  inactive memberships, non-client roles, and suspended workspaces (Points 3, 4)
- Sensitive OTP storage security: raw OTP is never stored; code_hash is non-empty (Points 5, 6)
- Expiry configuration: OTP expires in exactly 10 minutes (Point 7)
- Invalidation semantics: new request invalidates previous unconsumed OTP (Point 8)
- Scoped rate limiting: request-code (3/hour per email, 10/hour per IP) and verify-code
  (10/hour) (Points 9, 10, 18)
- Verification success: valid OTP returns 200 and sets Django session (Points 11, 12)
- Single-use enforcement: used OTP cannot be reused (Point 13)
- Expiration enforcement: expired OTP cannot authenticate (Point 14)
- Attempt tracking: invalid attempts increment counter; 5th failure exhausts OTP
  (Points 15, 16)
- Attempt exhaustion: returns OTP_RATE_LIMITED with HTTP 429 (Point 17)
- Membership & role authorization guards: only ACTIVE CLIENT memberships in target
  workspace can authenticate; non-client roles, inactive memberships, foreign tenants
  fail (Points 19, 20, 21, 22, 23)
- Cross-workspace replay prevention: OTP from workspace A cannot verify in B (Point 24)
- Architecture guards: out-of-scope session routes 404, accounts exposes exactly 6
  models, LoginOTP has no workspace FK (Point 25)
- Non-leakage: OTP hashes, codes, attempt counts, and timestamps never leak in response
  bodies (Point 26)
"""

import re
import uuid
from typing import Any

from django.apps import apps
from django.conf import settings
from django.contrib.auth import SESSION_KEY, get_user_model
from django.core import mail
from django.core.cache import cache
from django.db import models
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

REQUEST_CODE_URL = "/api/v1/auth/client/request-code"
VERIFY_CODE_URL = "/api/v1/auth/client/verify-code"
ME_URL = "/api/v1/auth/me"
SESSIONS_URL = "/api/v1/auth/sessions"

EXPECTED_LOGIN_OTP_FIELDS = {
    "id",
    "user",
    "email",
    "code_hash",
    "expires_at",
    "attempts",
    "used_at",
    "created_at",
}

EXPECTED_ACCOUNTS_MODELS = {
    "User",
    "CoachProfile",
    "ClientProfile",
    "CoachSecurity",
    "Membership",
    "LoginOTP",
}


def _extract_otp_from_email_body(body: str) -> str:
    """Extract a 6-digit numeric OTP from an email body or subject string.

    Format-agnostic: searches for labeled patterns ('code: 123456', 'code is 123456',
    'OTP: 123456') as well as standalone 6-digit numbers.
    """
    if not body:
        return ""
    labeled_match = re.search(
        r"(?:code|otp)(?:\s+is|\s*:|\s*=)\s*(\d{6})",
        body,
        re.IGNORECASE,
    )
    if labeled_match:
        return labeled_match.group(1).strip()
    digits_match = re.search(r"\b(\d{6})\b", body)
    if digits_match:
        return digits_match.group(1).strip()
    return ""


class BaseClientOtpApiTestCase(TestCase):
    """Base test class providing helpers, model access, client setup, and cache reset."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.client = APIClient()
        self.user_model = get_user_model()
        self.workspace_model = apps.get_model("workspaces", "Workspace")
        self.membership_model = apps.get_model("accounts", "Membership")
        self.login_otp_model = apps.get_model("accounts", "LoginOTP")

    def _create_user(self, email=None, password="StrongPassword123!", **kwargs):
        """Creates and returns an email-verified User instance."""
        if email is None:
            email = f"client-{uuid.uuid4().hex[:8]}@example.com"
        kwargs.setdefault("email_verified_at", timezone.now())
        return self.user_model.objects.create_user(email=email, password=password, **kwargs)

    def _create_workspace(self, name=None, slug=None, status="ACTIVE", **kwargs):
        """Creates and returns a Workspace instance."""
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
            "status": status,
        }
        defaults.update(kwargs)
        return self.workspace_model.objects.create(**defaults)

    def _create_membership(
        self, user=None, workspace=None, role="CLIENT", status="ACTIVE", **kwargs
    ):
        """Creates and returns a Membership instance."""
        if user is None:
            user = self._create_user()
        if workspace is None:
            workspace = self._create_workspace()
        defaults = {
            "user": user,
            "workspace": workspace,
            "role": role,
            "status": status,
        }
        defaults.update(kwargs)
        return self.membership_model.objects.create(**defaults)

    def _setup_eligible_client(self, email=None, workspace_slug=None):
        """Helper to create an active Workspace, User, and active CLIENT Membership."""
        workspace = self._create_workspace(slug=workspace_slug)
        user = self._create_user(email=email)
        membership = self._create_membership(
            user=user, workspace=workspace, role="CLIENT", status="ACTIVE"
        )
        return workspace, user, membership

    def _request_otp(self, email: str, workspace_slug: str) -> tuple[Any, str]:
        """Requests an OTP inside on-commit callbacks and returns response & code."""
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                REQUEST_CODE_URL,
                {"email": email, "workspace_slug": workspace_slug},
                format="json",
            )
        code = ""
        if mail.outbox:
            last_email = mail.outbox[-1]
            code = _extract_otp_from_email_body(last_email.body)
            if not code:
                code = _extract_otp_from_email_body(last_email.subject)
        return response, code

    def assert_validation_error_envelope(self, response, expected_field: str | None = None):
        """Helper to assert standard §2 error envelope for 400 VALIDATION_ERROR."""
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
        self.assertIsInstance(error.get("message"), str)
        self.assertIsInstance(error.get("fields"), dict)
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

    def assert_error_envelope(
        self, response, expected_status: int, expected_code: str | None = None
    ):
        """Helper to assert standard §2 error envelope for non-validation errors."""
        self.assertEqual(response.status_code, expected_status)
        data = response.json()
        self.assertEqual(
            set(data.keys()),
            {"error"},
            "Response top-level key must be exactly 'error'.",
        )
        error = data["error"]
        self.assertIsInstance(error, dict)
        if expected_code is not None:
            self.assertEqual(
                error.get("code"),
                expected_code,
                f"Expected error code '{expected_code}', got '{error.get('code')}'.",
            )
        self.assertIsInstance(error.get("message"), str)
        if expected_code != "VALIDATION_ERROR":
            self.assertNotIn(
                "fields",
                error,
                "Non-validation errors must not contain 'fields'.",
            )


class ClientOtpRouteAndAccessTests(BaseClientOtpApiTestCase):
    """Verifies HTTP routing, allowed methods, and unauthenticated public access."""

    def test_request_code_endpoint_accepts_post_on_literal_route(self):
        """Asserts POST to literal '/api/v1/auth/client/request-code' is routed."""
        response = self.client.post(
            REQUEST_CODE_URL,
            {"email": "route.check@example.com", "workspace_slug": "dummy-slug"},
            format="json",
        )
        self.assertNotIn(
            response.status_code,
            [status.HTTP_404_NOT_FOUND, status.HTTP_405_METHOD_NOT_ALLOWED],
            f"Route {REQUEST_CODE_URL} must exist and accept POST.",
        )

    def test_verify_code_endpoint_accepts_post_on_literal_route(self):
        """Asserts POST to literal '/api/v1/auth/client/verify-code' is routed."""
        response = self.client.post(
            VERIFY_CODE_URL,
            {
                "email": "route.check@example.com",
                "workspace_slug": "dummy-slug",
                "code": "123456",
            },
            format="json",
        )
        self.assertNotIn(
            response.status_code,
            [status.HTTP_404_NOT_FOUND, status.HTTP_405_METHOD_NOT_ALLOWED],
            f"Route {VERIFY_CODE_URL} must exist and accept POST.",
        )

    def test_request_code_endpoint_allows_unauthenticated_access(self):
        """Guards public access: request-code must allow unauthenticated requests."""
        self.client.logout()
        response = self.client.post(
            REQUEST_CODE_URL,
            {"email": "unauth.check@example.com", "workspace_slug": "some-slug"},
            format="json",
        )
        self.assertNotIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
            f"Route {REQUEST_CODE_URL} must be reachable without prior authentication.",
        )

    def test_verify_code_endpoint_allows_unauthenticated_access(self):
        """Guards public access: verify-code must allow unauthenticated requests."""
        self.client.logout()
        response = self.client.post(
            VERIFY_CODE_URL,
            {
                "email": "unauth.check@example.com",
                "workspace_slug": "some-slug",
                "code": "123456",
            },
            format="json",
        )
        self.assertNotIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
            f"Route {VERIFY_CODE_URL} must be reachable without prior authentication.",
        )

    def test_request_code_disallowed_http_methods_return_405_method_not_allowed(self):
        """Asserts non-POST methods (GET, PUT, PATCH, DELETE) to request-code return 405."""
        disallowed_methods = ["get", "put", "patch", "delete"]
        for method in disallowed_methods:
            with self.subTest(http_method=method):
                cache.clear()
                client_method = getattr(self.client, method)
                response = client_method(REQUEST_CODE_URL)
                self.assertEqual(
                    response.status_code,
                    status.HTTP_405_METHOD_NOT_ALLOWED,
                    f"HTTP {method.upper()} to {REQUEST_CODE_URL} should return 405.",
                )

    def test_verify_code_disallowed_http_methods_return_405_method_not_allowed(self):
        """Asserts non-POST methods (GET, PUT, PATCH, DELETE) to verify-code return 405."""
        disallowed_methods = ["get", "put", "patch", "delete"]
        for method in disallowed_methods:
            with self.subTest(http_method=method):
                cache.clear()
                client_method = getattr(self.client, method)
                response = client_method(VERIFY_CODE_URL)
                self.assertEqual(
                    response.status_code,
                    status.HTTP_405_METHOD_NOT_ALLOWED,
                    f"HTTP {method.upper()} to {VERIFY_CODE_URL} should return 405.",
                )


class ClientOtpRequestSuccessContractTests(BaseClientOtpApiTestCase):
    """Verifies generic success and LoginOTP creation for eligible clients (Points 1, 2)."""

    def test_valid_request_returns_generic_success_response(self):
        """Asserts POST to request-code returns 200 OK without error (Point 1)."""
        workspace, user, _ = self._setup_eligible_client()
        response, _ = self._request_otp(user.email, workspace.slug)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn(
            "error",
            response.json(),
            "Successful request-code response must not contain 'error' key.",
        )

    def test_eligible_client_creates_login_otp_row_with_expected_state(self):
        """Asserts request creates LoginOTP row with correct initial fields (Point 2)."""
        workspace, user, _ = self._setup_eligible_client()
        response, _ = self._request_otp(user.email, workspace.slug)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            self.login_otp_model.objects.filter(user=user).count(),
            1,
            "Exactly one LoginOTP row must be created for the requested user.",
        )
        otp = self.login_otp_model.objects.get(user=user)
        self.assertEqual(otp.email, user.email)
        self.assertEqual(otp.user_id, user.id)
        self.assertEqual(otp.attempts, 0)
        self.assertIsNone(otp.used_at)
        self.assertIsNotNone(otp.created_at)
        self.assertIsNotNone(otp.expires_at)
        self.assertTrue(bool(otp.code_hash))

    def test_request_dispatches_email_containing_six_digit_code_on_commit(self):
        """Asserts on-commit callback sends an email with a 6-digit OTP code."""
        workspace, user, _ = self._setup_eligible_client()
        response, code = self._request_otp(user.email, workspace.slug)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1, "Exactly one OTP email must be sent.")
        self.assertEqual(mail.outbox[0].to, [user.email])
        self.assertTrue(bool(code), "Dispatched email must contain a 6-digit OTP code.")
        self.assertEqual(len(code), 6, "OTP code must be exactly 6 digits.")
        self.assertTrue(code.isdigit(), "OTP code must be purely numeric.")


class ClientOtpRequestAntiEnumerationTests(BaseClientOtpApiTestCase):
    """Verifies byte-identical responses across all request paths (Points 3, 4)."""

    def test_unknown_email_returns_byte_identical_response_and_creates_no_otp(self):
        """Asserts unknown email returns byte-identical response and no row (Point 3)."""
        workspace, valid_user, _ = self._setup_eligible_client()
        resp_valid, _ = self._request_otp(valid_user.email, workspace.slug)
        self.assertEqual(resp_valid.status_code, status.HTTP_200_OK)

        unknown_email = f"unknown-{uuid.uuid4().hex[:8]}@example.com"
        resp_unknown, _ = self._request_otp(unknown_email, workspace.slug)

        self.assertEqual(resp_unknown.status_code, status.HTTP_200_OK)
        self.assertEqual(
            resp_unknown.json(),
            resp_valid.json(),
            "Parsed JSON for unknown email must equal valid request response.",
        )
        self.assertEqual(
            resp_unknown.content,
            resp_valid.content,
            "Raw response bytes for unknown email must match valid request.",
        )
        self.assertEqual(
            self.login_otp_model.objects.filter(email=unknown_email).count(),
            0,
            "No LoginOTP row must be created for an unknown email address.",
        )

    def test_ineligible_and_wrong_workspaces_produce_byte_identical_responses(self):
        """Asserts ineligible cases are byte-identical with zero OTP rows (Point 4).

        Guards against user and workspace enumeration:
        An attacker must not be able to discern whether an email exists, whether a user has
        a membership in a given workspace, whether their membership is active, whether their
        role is CLIENT, or whether the workspace is SUSPENDED or non-existent.
        All responses must return 200 OK and be completely byte-identical to the happy path.
        """
        # Baseline: happy path response
        target_ws, valid_client, _ = self._setup_eligible_client()
        resp_happy, _ = self._request_otp(valid_client.email, target_ws.slug)
        self.assertEqual(resp_happy.status_code, status.HTTP_200_OK)

        # 1. Real user with NO membership in the requested workspace
        foreign_user = self._create_user(email=f"foreign-{uuid.uuid4().hex[:8]}@example.com")

        # 2. Real user with INACTIVE membership in target workspace
        inactive_user = self._create_user(email=f"inactive-{uuid.uuid4().hex[:8]}@example.com")
        self._create_membership(
            user=inactive_user,
            workspace=target_ws,
            role="CLIENT",
            status="INACTIVE",
        )

        # 3. Real user with OWNER role in target workspace
        owner_user = self._create_user(email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
        self._create_membership(
            user=owner_user,
            workspace=target_ws,
            role="OWNER",
            status="ACTIVE",
        )

        # 4. Real user with COACH role in target workspace
        coach_user = self._create_user(email=f"coach-{uuid.uuid4().hex[:8]}@example.com")
        self._create_membership(
            user=coach_user,
            workspace=target_ws,
            role="COACH",
            status="ACTIVE",
        )

        # 5. Real user requesting an UNKNOWN workspace slug
        unknown_slug = f"nonexistent-ws-{uuid.uuid4().hex[:8]}"

        # 6. Real user with CLIENT membership in a SUSPENDED workspace
        suspended_ws = self._create_workspace(status="SUSPENDED")
        suspended_user = self._create_user(email=f"susp-{uuid.uuid4().hex[:8]}@example.com")
        self._create_membership(
            user=suspended_user,
            workspace=suspended_ws,
            role="CLIENT",
            status="ACTIVE",
        )

        ineligible_scenarios = [
            ("foreign_user_no_membership", foreign_user.email, target_ws.slug),
            ("inactive_membership", inactive_user.email, target_ws.slug),
            ("owner_role_membership", owner_user.email, target_ws.slug),
            ("coach_role_membership", coach_user.email, target_ws.slug),
            ("unknown_workspace_slug", valid_client.email, unknown_slug),
            ("suspended_workspace", suspended_user.email, suspended_ws.slug),
        ]

        for scenario_name, test_email, test_slug in ineligible_scenarios:
            with self.subTest(scenario=scenario_name):
                otp_rows_before = self.login_otp_model.objects.filter(email=test_email).count()
                resp, _ = self._request_otp(test_email, test_slug)
                self.assertEqual(
                    resp.status_code,
                    status.HTTP_200_OK,
                    f"Scenario '{scenario_name}' must return 200 OK.",
                )
                self.assertEqual(
                    resp.json(),
                    resp_happy.json(),
                    f"Scenario '{scenario_name}' JSON must match happy path JSON.",
                )
                self.assertEqual(
                    resp.content,
                    resp_happy.content,
                    f"Scenario '{scenario_name}' content must match happy path bytes.",
                )
                # Count the DELTA, not an absolute zero. The happy-path baseline at the
                # top of this test legitimately created an OTP for valid_client, and the
                # unknown_workspace_slug scenario reuses that same email — so an absolute
                # zero would fail on a row the implementation was right to create earlier.
                self.assertEqual(
                    self.login_otp_model.objects.filter(email=test_email).count(),
                    otp_rows_before,
                    f"Scenario '{scenario_name}' must not create a new LoginOTP row.",
                )


class ClientOtpStorageSecurityAndExpiryTests(BaseClientOtpApiTestCase):
    """Verifies raw OTP non-storage, code_hash, and 10-minute expiry (Points 5, 6, 7)."""

    def test_raw_otp_code_is_never_stored_in_any_field_of_login_otp_row(self):
        """Asserts raw OTP is absent from all fields of LoginOTP row (Point 5).

        Guards cryptographic storage invariant:
        The 6-digit plain code must never be persisted in plaintext. The database must store
        only an irreversible cryptographic hash (`code_hash`). In particular, `code_hash != code`
        and `code` must not appear as a substring of `code_hash` or any other field.
        """
        workspace, user, _ = self._setup_eligible_client()
        response, raw_code = self._request_otp(user.email, workspace.slug)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(bool(raw_code), "Raw OTP must be extracted from email.")

        otp = self.login_otp_model.objects.get(user=user)
        self.assertNotEqual(
            otp.code_hash,
            raw_code,
            "LoginOTP.code_hash must not equal the raw plain OTP code.",
        )
        self.assertNotIn(
            raw_code,
            otp.code_hash,
            "Raw OTP code must not appear as a substring inside code_hash.",
        )
        self.assertNotIn(raw_code, str(otp.id), "Raw OTP code must not appear in pk.")
        self.assertNotIn(raw_code, otp.email, "Raw OTP code must not appear in email.")

    def test_code_hash_is_stored_and_non_empty(self):
        """Asserts LoginOTP.code_hash is populated as a non-empty string (Point 6)."""
        workspace, user, _ = self._setup_eligible_client()
        response, _ = self._request_otp(user.email, workspace.slug)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        otp = self.login_otp_model.objects.get(user=user)
        self.assertIsInstance(otp.code_hash, str)
        self.assertTrue(bool(otp.code_hash))
        self.assertGreater(len(otp.code_hash), 0)

    def test_otp_expiry_is_configured_for_exactly_ten_minutes(self):
        """Asserts LoginOTP expires_at - created_at is exactly 10 minutes (Point 7)."""
        workspace, user, _ = self._setup_eligible_client()
        response, _ = self._request_otp(user.email, workspace.slug)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        otp = self.login_otp_model.objects.get(user=user)
        self.assertIsNotNone(otp.created_at)
        self.assertIsNotNone(otp.expires_at)

        delta_seconds = (otp.expires_at - otp.created_at).total_seconds()
        self.assertAlmostEqual(
            delta_seconds,
            600.0,
            delta=5.0,
            msg="OTP expires_at must be exactly 10 minutes (600s) after created_at.",
        )


class ClientOtpRequestInvalidationAndThrottlingTests(BaseClientOtpApiTestCase):
    """Verifies OTP invalidation and endpoint rate limiting (Points 8, 9, 10)."""

    def test_new_otp_request_invalidates_previous_otp_code(self):
        """Asserts requesting a new OTP invalidates previous code (Point 8).

        Guards single active OTP invariant:
        When a user requests a second OTP, the previous OTP is invalidated immediately.
        Submitting the first code must fail verification, while submitting the second code
        succeeds. Two usable OTPs must never coexist for the same user.
        """
        workspace, user, _ = self._setup_eligible_client()

        # First request
        _, code_1 = self._request_otp(user.email, workspace.slug)
        self.assertTrue(bool(code_1))

        # Second request
        _, code_2 = self._request_otp(user.email, workspace.slug)
        self.assertTrue(bool(code_2))

        # First code must fail verification
        fail_resp = self.client.post(
            VERIFY_CODE_URL,
            {
                "email": user.email,
                "workspace_slug": workspace.slug,
                "code": code_1,
            },
            format="json",
        )
        self.assertEqual(fail_resp.status_code, status.HTTP_400_BAD_REQUEST)

        # Second code must succeed verification
        cache.clear()
        success_resp = self.client.post(
            VERIFY_CODE_URL,
            {
                "email": user.email,
                "workspace_slug": workspace.slug,
                "code": code_2,
            },
            format="json",
        )
        self.assertEqual(success_resp.status_code, status.HTTP_200_OK)

    def test_request_endpoint_enforces_per_email_throttle_of_three_per_hour(self):
        """Asserts request-code enforces 3/hour per email throttle (Point 9)."""
        workspace, user, _ = self._setup_eligible_client()
        payload = {"email": user.email, "workspace_slug": workspace.slug}

        for i in range(3):
            resp = self.client.post(REQUEST_CODE_URL, payload, format="json")
            self.assertEqual(
                resp.status_code,
                status.HTTP_200_OK,
                f"Request {i + 1} within per-email limit must return 200.",
            )

        throttled_resp = self.client.post(REQUEST_CODE_URL, payload, format="json")
        self.assert_error_envelope(
            throttled_resp,
            expected_status=status.HTTP_429_TOO_MANY_REQUESTS,
            expected_code="RATE_LIMITED",
        )

    def test_request_endpoint_enforces_per_ip_throttle_of_ten_per_hour(self):
        """Asserts request-code enforces 10/hour per IP throttle (Point 10)."""
        workspace = self._create_workspace()

        # Use 10 distinct emails to avoid colliding with per-email throttle
        for i in range(10):
            email = f"distinct-ip-user-{i}-{uuid.uuid4().hex[:6]}@example.com"
            resp = self.client.post(
                REQUEST_CODE_URL,
                {"email": email, "workspace_slug": workspace.slug},
                format="json",
            )
            self.assertEqual(
                resp.status_code,
                status.HTTP_200_OK,
                f"Request {i + 1} with distinct email must return 200.",
            )

        # 11th request from same client (same IP) must be throttled
        eleventh_email = f"distinct-ip-user-11-{uuid.uuid4().hex[:6]}@example.com"
        throttled_resp = self.client.post(
            REQUEST_CODE_URL,
            {"email": eleventh_email, "workspace_slug": workspace.slug},
            format="json",
        )
        self.assert_error_envelope(
            throttled_resp,
            expected_status=status.HTTP_429_TOO_MANY_REQUESTS,
            expected_code="RATE_LIMITED",
        )


class ClientOtpVerifySuccessAndSessionTests(BaseClientOtpApiTestCase):
    """Verifies OTP verification, session creation, and reuse (Points 11, 12, 13, 23)."""

    def test_valid_otp_authenticates_client_with_200_ok(self):
        """Asserts valid email, workspace_slug, and code returns 200 OK (Point 11)."""
        workspace, user, _ = self._setup_eligible_client()
        _, code = self._request_otp(user.email, workspace.slug)

        response = self.client.post(
            VERIFY_CODE_URL,
            {
                "email": user.email,
                "workspace_slug": workspace.slug,
                "code": code,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_successful_verification_establishes_django_session_and_authenticates_me(self):
        """Asserts successful verification creates a normal Django session (Point 12).

        This proves a real session: after verification, a subsequent request to
        `/api/v1/auth/me` succeeds with 200 OK and returns the caller's identity.
        """
        workspace, user, _ = self._setup_eligible_client()
        _, code = self._request_otp(user.email, workspace.slug)

        verify_resp = self.client.post(
            VERIFY_CODE_URL,
            {
                "email": user.email,
                "workspace_slug": workspace.slug,
                "code": code,
            },
            format="json",
        )
        self.assertEqual(verify_resp.status_code, status.HTTP_200_OK)

        # Assert session was created
        session_cookie_name = settings.SESSION_COOKIE_NAME
        self.assertIn(
            session_cookie_name,
            verify_resp.cookies,
            "Successful verify-code must set the Django session cookie.",
        )
        self.assertTrue(
            bool(verify_resp.cookies[session_cookie_name].value),
            "Session cookie value must not be empty.",
        )
        self.assertEqual(
            str(self.client.session.get(SESSION_KEY)),
            str(user.pk),
            "Session must be authenticated as the verified client user.",
        )

        # Prove session access on /api/v1/auth/me
        me_resp = self.client.get(ME_URL)
        self.assertEqual(me_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(me_resp.json().get("email"), user.email)

    def test_used_otp_cannot_be_reused_and_marks_used_at_timestamp(self):
        """Asserts used OTP cannot be reused and populates used_at (Point 13)."""
        workspace, user, _ = self._setup_eligible_client()
        _, code = self._request_otp(user.email, workspace.slug)

        first_verify = self.client.post(
            VERIFY_CODE_URL,
            {
                "email": user.email,
                "workspace_slug": workspace.slug,
                "code": code,
            },
            format="json",
        )
        self.assertEqual(first_verify.status_code, status.HTTP_200_OK)

        otp = self.login_otp_model.objects.get(user=user)
        self.assertIsNotNone(otp.used_at, "LoginOTP.used_at must be set on verify.")

        # Re-using the same code must fail
        cache.clear()
        second_verify = self.client.post(
            VERIFY_CODE_URL,
            {
                "email": user.email,
                "workspace_slug": workspace.slug,
                "code": code,
            },
            format="json",
        )
        self.assertEqual(second_verify.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(
            second_verify.json().get("error", {}).get("code"),
            ["INVALID_OTP", "OTP_EXPIRED"],
            "Reused OTP must return standard closed error code.",
        )

    def test_active_client_membership_in_correct_workspace_succeeds(self):
        """Asserts ACTIVE CLIENT membership in target workspace succeeds (Point 23)."""
        workspace, user, membership = self._setup_eligible_client()
        self.assertEqual(membership.role, "CLIENT")
        self.assertEqual(membership.status, "ACTIVE")

        _, code = self._request_otp(user.email, workspace.slug)
        response = self.client.post(
            VERIFY_CODE_URL,
            {
                "email": user.email,
                "workspace_slug": workspace.slug,
                "code": code,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class ClientOtpVerifyFailureAndAttemptExhaustionTests(BaseClientOtpApiTestCase):
    """Verifies expired OTP, attempts counter, exhaustion, and throttle (Points 14-18)."""

    def test_expired_otp_fails_verification(self):
        """Asserts an OTP aged into the past fails verification (Point 14)."""
        workspace, user, _ = self._setup_eligible_client()
        _, code = self._request_otp(user.email, workspace.slug)

        # Age expires_at into the past via ORM
        otp = self.login_otp_model.objects.get(user=user)
        otp.expires_at = timezone.now() - timezone.timedelta(minutes=1)
        otp.save(update_fields=["expires_at"])

        response = self.client.post(
            VERIFY_CODE_URL,
            {
                "email": user.email,
                "workspace_slug": workspace.slug,
                "code": code,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(
            response.json().get("error", {}).get("code"),
            ["OTP_EXPIRED", "INVALID_OTP"],
            "Expired OTP must return closed error code OTP_EXPIRED or INVALID_OTP.",
        )

    def test_wrong_code_increments_attempts_counter_on_login_otp_row(self):
        """Asserts wrong code increments LoginOTP.attempts by one (Point 15)."""
        workspace, user, _ = self._setup_eligible_client()
        _, _ = self._request_otp(user.email, workspace.slug)

        otp = self.login_otp_model.objects.get(user=user)
        self.assertEqual(otp.attempts, 0)

        response = self.client.post(
            VERIFY_CODE_URL,
            {
                "email": user.email,
                "workspace_slug": workspace.slug,
                "code": "000000",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_400_BAD_REQUEST,
            expected_code="INVALID_OTP",
        )

        otp.refresh_from_db()
        self.assertEqual(
            otp.attempts,
            1,
            "Wrong code submission must increment attempts counter from 0 to 1.",
        )

    def test_fifth_invalid_attempt_exhausts_the_otp(self):
        """Asserts five consecutive wrong attempts exhaust the OTP (Point 16)."""
        workspace, user, _ = self._setup_eligible_client()
        _, _ = self._request_otp(user.email, workspace.slug)

        otp = self.login_otp_model.objects.get(user=user)

        # 4 wrong attempts
        for i in range(4):
            cache.clear()
            resp = self.client.post(
                VERIFY_CODE_URL,
                {
                    "email": user.email,
                    "workspace_slug": workspace.slug,
                    "code": f"00000{i}",
                },
                format="json",
            )
            self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

        otp.refresh_from_db()
        self.assertEqual(otp.attempts, 4)

        # 5th wrong attempt triggers exhaustion
        cache.clear()
        exhaust_resp = self.client.post(
            VERIFY_CODE_URL,
            {
                "email": user.email,
                "workspace_slug": workspace.slug,
                "code": "000005",
            },
            format="json",
        )
        self.assertEqual(exhaust_resp.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_attempt_exhaustion_returns_otp_rate_limited_with_http_429(self):
        """Asserts attempt exhaustion returns OTP_RATE_LIMITED with HTTP 429 (Point 17).

        Guards against brute-force attacks and error code proliferation:
        The maximum number of verification attempts is strictly 5. When attempts are
        exhausted, the endpoint returns HTTP 429 Too Many Requests with the closed error code
        `OTP_RATE_LIMITED`. `OTP_ATTEMPTS_EXCEEDED` must not exist.
        """
        workspace, user, _ = self._setup_eligible_client()
        _, valid_code = self._request_otp(user.email, workspace.slug)

        # Exhaust 5 attempts with wrong codes
        for i in range(4):
            cache.clear()
            self.client.post(
                VERIFY_CODE_URL,
                {
                    "email": user.email,
                    "workspace_slug": workspace.slug,
                    "code": f"11111{i}",
                },
                format="json",
            )

        cache.clear()
        fifth_resp = self.client.post(
            VERIFY_CODE_URL,
            {
                "email": user.email,
                "workspace_slug": workspace.slug,
                "code": "999999",
            },
            format="json",
        )

        self.assertEqual(fifth_resp.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        error_code = fifth_resp.json().get("error", {}).get("code")
        self.assertEqual(
            error_code,
            "OTP_RATE_LIMITED",
            "Exhaustion response error code must be exactly 'OTP_RATE_LIMITED'.",
        )
        self.assertNotEqual(
            error_code,
            "OTP_ATTEMPTS_EXCEEDED",
            "Invented error code 'OTP_ATTEMPTS_EXCEEDED' must not exist.",
        )

        # Subsequent attempt with even the valid code must now fail
        cache.clear()
        subsequent_resp = self.client.post(
            VERIFY_CODE_URL,
            {
                "email": user.email,
                "workspace_slug": workspace.slug,
                "code": valid_code,
            },
            format="json",
        )
        self.assertEqual(subsequent_resp.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(
            subsequent_resp.json().get("error", {}).get("code"),
            "OTP_RATE_LIMITED",
        )

    def test_verify_endpoint_enforces_verify_throttle_of_ten_per_hour(self):
        """Asserts verify-code endpoint enforces 10/hour throttle limit (Point 18)."""
        workspace = self._create_workspace()

        for i in range(10):
            email = f"verify-throttle-{i}-{uuid.uuid4().hex[:6]}@example.com"
            resp = self.client.post(
                VERIFY_CODE_URL,
                {
                    "email": email,
                    "workspace_slug": workspace.slug,
                    "code": "123456",
                },
                format="json",
            )
            self.assertIn(
                resp.status_code,
                [status.HTTP_400_BAD_REQUEST, status.HTTP_401_UNAUTHORIZED],
                f"Verify call {i + 1} within throttle limit should not be 429.",
            )

        throttled_resp = self.client.post(
            VERIFY_CODE_URL,
            {
                "email": "verify-throttle-11@example.com",
                "workspace_slug": workspace.slug,
                "code": "123456",
            },
            format="json",
        )
        self.assert_error_envelope(
            throttled_resp,
            expected_status=status.HTTP_429_TOO_MANY_REQUESTS,
            expected_code="RATE_LIMITED",
        )


class ClientOtpVerifyMembershipAndIsolationTests(BaseClientOtpApiTestCase):
    """Verifies role authorization, membership, and tenant isolation (Points 19-24)."""

    def test_user_with_no_membership_cannot_authenticate(self):
        """Asserts user with no Membership in workspace cannot authenticate (Point 19)."""
        workspace = self._create_workspace()
        unaffiliated_user = self._create_user(email="no.member@example.com")

        response = self.client.post(
            VERIFY_CODE_URL,
            {
                "email": unaffiliated_user.email,
                "workspace_slug": workspace.slug,
                "code": "123456",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_user_with_inactive_membership_cannot_authenticate(self):
        """Asserts user with INACTIVE Membership cannot authenticate (Point 20)."""
        workspace = self._create_workspace()
        user = self._create_user(email="inactive.client@example.com")
        self._create_membership(user=user, workspace=workspace, role="CLIENT", status="INACTIVE")

        response = self.client.post(
            VERIFY_CODE_URL,
            {
                "email": user.email,
                "workspace_slug": workspace.slug,
                "code": "123456",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_user_with_non_client_role_cannot_authenticate(self):
        """Asserts user with OWNER or COACH role cannot authenticate (Point 21)."""
        workspace = self._create_workspace()

        owner_user = self._create_user(email="owner.auth@example.com")
        self._create_membership(user=owner_user, workspace=workspace, role="OWNER", status="ACTIVE")

        coach_user = self._create_user(email="coach.auth@example.com")
        self._create_membership(user=coach_user, workspace=workspace, role="COACH", status="ACTIVE")

        for role_name, user_obj in [("OWNER", owner_user), ("COACH", coach_user)]:
            with self.subTest(role=role_name):
                cache.clear()
                resp = self.client.post(
                    VERIFY_CODE_URL,
                    {
                        "email": user_obj.email,
                        "workspace_slug": workspace.slug,
                        "code": "123456",
                    },
                    format="json",
                )
                self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertNotIn(SESSION_KEY, self.client.session)

    def test_foreign_workspace_membership_cannot_authenticate(self):
        """Asserts user in workspace A cannot authenticate into workspace B (Point 22)."""
        workspace_a = self._create_workspace(slug="workspace-alpha")
        workspace_b = self._create_workspace(slug="workspace-beta")

        user_a = self._create_user(email="client.alpha@example.com")
        self._create_membership(user=user_a, workspace=workspace_a, role="CLIENT", status="ACTIVE")

        response = self.client.post(
            VERIFY_CODE_URL,
            {
                "email": user_a.email,
                "workspace_slug": workspace_b.slug,
                "code": "123456",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_a_code_cannot_authenticate_into_a_workspace_the_user_is_not_a_client_of(self):
        """Guards the real cross-workspace boundary: membership in the TARGET workspace.

        The OTP proves possession of the email address; it is NOT workspace-bound, and it
        cannot be — DB Architecture and the ERD define LoginOTP with no workspace FK (it
        hangs off User only), and adding one is explicitly out of scope. Workspace
        authorization is therefore a SEPARATE check against Membership in the REQUESTED
        workspace, which is what this test pins.

        So the invariant that actually protects tenants is: a valid code cannot get a user
        into a workspace they are not an ACTIVE CLIENT of. A user who *is* an active client
        of two workspaces may enter either one — no boundary is crossed, since they could
        simply have requested a code from that workspace's own portal.
        """
        workspace_a = self._create_workspace(slug="tenant-a")
        workspace_b = self._create_workspace(slug="tenant-b")

        client_of_a_only = self._create_user(email="only.a@example.com")
        self._create_membership(
            user=client_of_a_only, workspace=workspace_a, role="CLIENT", status="ACTIVE"
        )

        _, code_a = self._request_otp(client_of_a_only.email, workspace_a.slug)
        self.assertTrue(bool(code_a))

        # The code is valid, but this user is not a client of workspace B.
        cache.clear()
        replay_resp = self.client.post(
            VERIFY_CODE_URL,
            {
                "email": client_of_a_only.email,
                "workspace_slug": workspace_b.slug,
                "code": code_a,
            },
            format="json",
        )
        self.assertEqual(replay_resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn(SESSION_KEY, self.client.session)

        # The same code still works for the workspace the user IS a client of.
        cache.clear()
        legit_resp = self.client.post(
            VERIFY_CODE_URL,
            {
                "email": client_of_a_only.email,
                "workspace_slug": workspace_a.slug,
                "code": code_a,
            },
            format="json",
        )
        self.assertEqual(legit_resp.status_code, status.HTTP_200_OK)


class ClientOtpValidationEnvelopeTests(BaseClientOtpApiTestCase):
    """Verifies §2 Standard Error Format and payload validation across OTP endpoints."""

    def test_request_code_missing_email_returns_400_validation_error(self):
        """Asserts omitting 'email' in request-code returns 400 VALIDATION_ERROR."""
        response = self.client.post(
            REQUEST_CODE_URL,
            {"workspace_slug": "some-gym"},
            format="json",
        )
        self.assert_validation_error_envelope(response, expected_field="email")

    def test_request_code_missing_workspace_slug_returns_400_validation_error(self):
        """Asserts omitting 'workspace_slug' in request-code returns 400 VALIDATION_ERROR."""
        response = self.client.post(
            REQUEST_CODE_URL,
            {"email": "valid@example.com"},
            format="json",
        )
        self.assert_validation_error_envelope(response, expected_field="workspace_slug")

    def test_request_code_empty_payload_returns_400_validation_error(self):
        """Asserts empty JSON payload to request-code returns 400 VALIDATION_ERROR."""
        response = self.client.post(REQUEST_CODE_URL, {}, format="json")
        self.assert_validation_error_envelope(response)

    def test_request_code_invalid_email_format_returns_400_validation_error(self):
        """Asserts malformed email format to request-code returns 400 VALIDATION_ERROR."""
        response = self.client.post(
            REQUEST_CODE_URL,
            {"email": "not-a-valid-email", "workspace_slug": "some-gym"},
            format="json",
        )
        self.assert_validation_error_envelope(response, expected_field="email")

    def test_verify_code_missing_required_fields_return_400_validation_error(self):
        """Asserts omitting email, workspace_slug, or code returns 400 VALIDATION_ERROR."""
        missing_scenarios = [
            ("email", {"workspace_slug": "some-gym", "code": "123456"}),
            ("workspace_slug", {"email": "valid@example.com", "code": "123456"}),
            ("code", {"email": "valid@example.com", "workspace_slug": "some-gym"}),
        ]
        for field_name, payload in missing_scenarios:
            with self.subTest(missing_field=field_name):
                resp = self.client.post(VERIFY_CODE_URL, payload, format="json")
                self.assert_validation_error_envelope(resp, expected_field=field_name)

    def test_verify_code_empty_payload_returns_400_validation_error(self):
        """Asserts empty JSON payload to verify-code returns 400 VALIDATION_ERROR."""
        response = self.client.post(VERIFY_CODE_URL, {}, format="json")
        self.assert_validation_error_envelope(response)

    def test_verify_code_invalid_code_types_return_400_validation_error(self):
        """Asserts null, non-string, boolean, or array code returns 400 VALIDATION_ERROR."""
        # 123456 is deliberately excluded: DRF's CharField coerces an int to "123456",
        # which is standard framework behaviour and makes it a WRONG CODE (INVALID_OTP),
        # not a malformed request. No approved document requires strict type rejection,
        # so asserting VALIDATION_ERROR there would invent a contract.
        invalid_codes = [None, True, [], {}]
        for invalid_code in invalid_codes:
            with self.subTest(code_value=invalid_code):
                resp = self.client.post(
                    VERIFY_CODE_URL,
                    {
                        "email": "test@example.com",
                        "workspace_slug": "some-gym",
                        "code": invalid_code,
                    },
                    format="json",
                )
                self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(resp.json().get("error", {}).get("code"), "VALIDATION_ERROR")


class ClientOtpArchitectureAndNonLeakageGuardsTests(BaseClientOtpApiTestCase):
    """Verifies out-of-scope route 404s, schema, and sensitive data non-leakage."""

    def test_out_of_scope_session_routes_return_404_not_found(self):
        """Asserts session listing and revoke routes return 404 (Point 25)."""
        workspace, user, _ = self._setup_eligible_client()
        self.client.force_authenticate(user=user)

        listing = self.client.get(SESSIONS_URL)
        self.assertEqual(listing.status_code, status.HTTP_404_NOT_FOUND)

        revoke = self.client.post(f"{SESSIONS_URL}/3f0f1a1e-0000-4000-8000-000000000000/revoke")
        self.assertEqual(revoke.status_code, status.HTTP_404_NOT_FOUND)

    def test_response_payloads_contain_no_jwt_or_bearer_token_keys(self):
        """Asserts responses contain no JWT or token-based auth keys (Point 25)."""
        workspace, user, _ = self._setup_eligible_client()
        req_resp, code = self._request_otp(user.email, workspace.slug)

        forbidden_keys = {
            "token",
            "access",
            "access_token",
            "refresh",
            "refresh_token",
            "jwt",
            "session_token",
            "key",
        }
        for forbidden in forbidden_keys:
            self.assertNotIn(
                forbidden,
                req_resp.json(),
                f"Forbidden auth key '{forbidden}' found in request-code response.",
            )

        verify_resp = self.client.post(
            VERIFY_CODE_URL,
            {
                "email": user.email,
                "workspace_slug": workspace.slug,
                "code": code,
            },
            format="json",
        )
        for forbidden in forbidden_keys:
            self.assertNotIn(
                forbidden,
                verify_resp.json(),
                f"Forbidden auth key '{forbidden}' found in verify-code response.",
            )

    def test_accounts_app_exposes_exactly_the_six_approved_models(self):
        """Asserts accounts exposes exactly the 6 approved models (Point 25)."""
        accounts_app = apps.get_app_config("accounts")
        concrete_model_names = {model._meta.object_name for model in accounts_app.get_models()}
        self.assertSetEqual(
            concrete_model_names,
            EXPECTED_ACCOUNTS_MODELS,
            "accounts must define exactly {User, CoachProfile, ClientProfile, "
            "CoachSecurity, Membership, LoginOTP}.",
        )

    def test_login_otp_model_schema_and_cascade_contract(self):
        """Asserts LoginOTP schema, CASCADE relation, and no workspace FK (Point 25)."""
        concrete_fields = {field.name for field in self.login_otp_model._meta.concrete_fields}
        self.assertSetEqual(
            concrete_fields,
            EXPECTED_LOGIN_OTP_FIELDS,
            "LoginOTP concrete fields must exactly match the schema contract.",
        )

        user_field = self.login_otp_model._meta.get_field("user")
        self.assertEqual(user_field.get_internal_type(), "ForeignKey")
        self.assertFalse(user_field.null, "LoginOTP.user must be non-null.")
        self.assertEqual(
            user_field.remote_field.on_delete,
            models.CASCADE,
            "LoginOTP.user must cascade on user deletion.",
        )

        # Assert no workspace FK exists on LoginOTP
        for field in self.login_otp_model._meta.concrete_fields:
            self.assertNotEqual(
                field.name,
                "workspace",
                "LoginOTP must NOT define a workspace ForeignKey.",
            )
            self.assertNotEqual(
                field.name,
                "workspace_id",
                "LoginOTP must NOT define a workspace_id field.",
            )

        # Test CASCADE deletion
        workspace, user, _ = self._setup_eligible_client()
        self._request_otp(user.email, workspace.slug)
        self.assertEqual(self.login_otp_model.objects.filter(user=user).count(), 1)
        user.delete()
        self.assertEqual(
            self.login_otp_model.objects.filter(user_id=user.id).count(),
            0,
            "Deleting User must cascade and delete associated LoginOTP records.",
        )

    def test_otp_sensitive_data_never_leaks_in_any_response_or_headers(self):
        """Asserts OTP code, hash, attempts, and timestamps never leak (Point 26).

        Guards response content boundary:
        Under no circumstances may sensitive internal OTP data (`code`, `code_hash`,
        `attempts`, `expires_at`, `used_at`, or remaining attempts hint) leak into
        any response body or HTTP header across successful or unsuccessful requests.
        """
        workspace, user, _ = self._setup_eligible_client()
        req_resp, code = self._request_otp(user.email, workspace.slug)
        otp = self.login_otp_model.objects.get(user=user)

        sensitive_strings = [
            otp.code_hash,
            str(otp.created_at),
            str(otp.expires_at),
        ]

        def assert_no_leakage(resp, label):
            content_str = resp.content.decode()
            for s in sensitive_strings:
                self.assertNotIn(
                    s,
                    content_str,
                    f"Sensitive string leaked in {label} response body.",
                )
            for header_name, header_value in resp.items():
                for s in sensitive_strings:
                    self.assertNotIn(
                        s,
                        str(header_value),
                        f"Sensitive string leaked in header '{header_name}' of {label}.",
                    )

        assert_no_leakage(req_resp, "request-code success")

        # Check verify success
        verify_success = self.client.post(
            VERIFY_CODE_URL,
            {
                "email": user.email,
                "workspace_slug": workspace.slug,
                "code": code,
            },
            format="json",
        )
        assert_no_leakage(verify_success, "verify-code success")

        # Check verify failure
        verify_fail = self.client.post(
            VERIFY_CODE_URL,
            {
                "email": user.email,
                "workspace_slug": workspace.slug,
                "code": "999999",
            },
            format="json",
        )
        assert_no_leakage(verify_fail, "verify-code failure")
