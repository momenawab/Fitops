"""API tests for the session endpoints (Story 2.9).

Validates:
- Access control: `/auth/me` and `/auth/logout` both require an authenticated session
- `/auth/me` contract: exactly eight keys, with no `role` key until Membership exists (Epic 03)
- `email_verified` is a derived boolean; the raw `email_verified_at` timestamp is never exposed
- `two_factor_enabled` reflects CoachSecurity, defaulting to False when no row exists
- `two_factor_secret` never appears in any response body
- `/auth/me` returns the authenticated caller's data and never another user's
- `/auth/logout` ends the session, so a subsequent `/auth/me` is rejected
- Session listing and per-session revocation routes do not exist (out of Phase 1 scope)
- Architecture guard: accounts defines exactly {User, CoachProfile, ClientProfile, CoachSecurity}
"""

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

ME_URL = "/api/v1/auth/me"
LOGOUT_URL = "/api/v1/auth/logout"
LOGIN_URL = "/api/v1/auth/login"

ME_KEYS = {
    "id",
    "email",
    "first_name",
    "last_name",
    "phone",
    "email_verified",
    "two_factor_enabled",
    "platform_role",
}


class BaseSessionApiTestCase(TestCase):
    """Base class providing a client, cache reset, and user/security helpers."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def _create_user(self, email="coach@example.com", password="StrongPassword123!", **kwargs):
        """Creates a user, email-verified by default."""
        kwargs.setdefault("email_verified_at", timezone.now())
        return get_user_model().objects.create_user(email=email, password=password, **kwargs)

    def _set_coach_security(self, user, enabled=False, secret="JBSWY3DPEHPK3PXP"):
        """Creates or updates the user's CoachSecurity row."""
        model = apps.get_model("accounts", "CoachSecurity")
        security, _ = model.objects.update_or_create(
            user=user,
            defaults={"two_factor_enabled": enabled, "two_factor_secret": secret},
        )
        return security


class SessionEndpointAccessTests(BaseSessionApiTestCase):
    """Verifies both endpoints reject unauthenticated callers with the standard envelope."""

    def test_me_rejects_unauthenticated_caller(self):
        """Asserts GET /auth/me returns 401 or 403 without a session."""
        response = self.client.get(ME_URL)
        self.assertIn(
            response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]
        )
        self.assertEqual(set(response.json().keys()), {"error"})

    def test_logout_rejects_unauthenticated_caller(self):
        """Asserts POST /auth/logout returns 401 or 403 without a session."""
        response = self.client.post(LOGOUT_URL)
        self.assertIn(
            response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]
        )
        self.assertEqual(set(response.json().keys()), {"error"})

    def test_me_route_exists_and_accepts_get(self):
        """Asserts the literal /auth/me route resolves and accepts GET."""
        self.client.force_authenticate(user=self._create_user(email="route.me@example.com"))
        response = self.client.get(ME_URL)
        self.assertNotIn(
            response.status_code,
            [status.HTTP_404_NOT_FOUND, status.HTTP_405_METHOD_NOT_ALLOWED],
        )

    def test_logout_route_exists_and_accepts_post(self):
        """Asserts the literal /auth/logout route resolves and accepts POST."""
        self.client.force_authenticate(user=self._create_user(email="route.out@example.com"))
        response = self.client.post(LOGOUT_URL)
        self.assertNotIn(
            response.status_code,
            [status.HTTP_404_NOT_FOUND, status.HTTP_405_METHOD_NOT_ALLOWED],
        )


class MeContractTests(BaseSessionApiTestCase):
    """Verifies the exact /auth/me response contract."""

    def test_me_returns_exactly_the_documented_key_set(self):
        """Asserts whole-key-set equality so any leaked or missing field fails."""
        user = self._create_user(email="keys@example.com", first_name="Ada", last_name="L")
        self.client.force_authenticate(user=user)
        response = self.client.get(ME_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(set(response.json().keys()), ME_KEYS)

    def test_me_does_not_expose_a_role_key(self):
        """Guards the Epic 03 boundary: role comes from Membership, which does not exist yet.

        API §4 lists a "Role" return, but role is workspace-scoped via Membership and a global
        role field would contradict §4's own rule that workspace context is resolved separately.
        Re-adding the key before Epic 03 must fail loudly rather than ship a wrong contract.
        """
        self.client.force_authenticate(user=self._create_user(email="norole@example.com"))
        response = self.client.get(ME_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("role", response.json())

    def test_me_reports_email_verified_true_as_a_boolean(self):
        """Asserts a verified user yields boolean True, not a truthy timestamp."""
        self.client.force_authenticate(user=self._create_user(email="verified@example.com"))
        payload = self.client.get(ME_URL).json()
        self.assertIsInstance(payload["email_verified"], bool)
        self.assertIs(payload["email_verified"], True)

    def test_me_reports_email_verified_false_for_unverified_user(self):
        """Asserts an unverified user yields boolean False."""
        user = self._create_user(email="unverified@example.com", email_verified_at=None)
        self.client.force_authenticate(user=user)
        payload = self.client.get(ME_URL).json()
        self.assertIsInstance(payload["email_verified"], bool)
        self.assertIs(payload["email_verified"], False)

    def test_me_never_exposes_the_raw_email_verified_at_timestamp(self):
        """Asserts the underlying timestamp field is not serialized."""
        user = self._create_user(email="timestamp@example.com")
        self.client.force_authenticate(user=user)
        response = self.client.get(ME_URL)
        self.assertNotIn("email_verified_at", response.json())
        self.assertNotIn("email_verified_at", response.content.decode())

    def test_me_reports_two_factor_disabled_when_no_coach_security_row_exists(self):
        """Asserts a user with no CoachSecurity row is reported as 2FA-disabled."""
        user = self._create_user(email="no2fa@example.com")
        self.client.force_authenticate(user=user)
        payload = self.client.get(ME_URL).json()
        self.assertIs(payload["two_factor_enabled"], False)

    def test_me_reports_two_factor_disabled_when_row_exists_but_is_off(self):
        """Asserts an existing CoachSecurity row with the flag off reports False."""
        user = self._create_user(email="off2fa@example.com")
        self._set_coach_security(user, enabled=False)
        self.client.force_authenticate(user=user)
        self.assertIs(self.client.get(ME_URL).json()["two_factor_enabled"], False)

    def test_me_reports_two_factor_enabled_when_row_is_on(self):
        """Asserts an enabled CoachSecurity row reports True."""
        user = self._create_user(email="on2fa@example.com")
        self._set_coach_security(user, enabled=True)
        self.client.force_authenticate(user=user)
        self.assertIs(self.client.get(ME_URL).json()["two_factor_enabled"], True)

    def test_me_never_leaks_the_two_factor_secret(self):
        """Asserts the TOTP secret is absent from the raw response body and headers."""
        canary = "CANARYSECRETNEVERLEAKMEENDPOINT12"
        user = self._create_user(email="secret@example.com")
        self._set_coach_security(user, enabled=True, secret=canary)
        self.client.force_authenticate(user=user)
        response = self.client.get(ME_URL)
        self.assertNotIn(canary, response.content.decode())
        for name, value in response.items():
            self.assertNotIn(canary, str(value), f"Secret leaked in header {name}.")

    def test_me_returns_the_users_uuid_as_a_string(self):
        """Asserts the id field is the caller's UUID rendered as a string."""
        user = self._create_user(email="uuid@example.com")
        self.client.force_authenticate(user=user)
        self.assertEqual(self.client.get(ME_URL).json()["id"], str(user.pk))

    def test_me_round_trips_platform_role_none_and_admin(self):
        """Asserts platform_role reflects the stored value for both documented values."""
        plain = self._create_user(email="plain@example.com")
        self.client.force_authenticate(user=plain)
        self.assertEqual(self.client.get(ME_URL).json()["platform_role"], "NONE")

        admin = self._create_user(email="admin@example.com", platform_role="ADMIN")
        self.client.force_authenticate(user=admin)
        self.assertEqual(self.client.get(ME_URL).json()["platform_role"], "ADMIN")

    def test_me_returns_the_callers_own_identity_and_not_another_users(self):
        """Guards against returning the wrong user: a second user must not appear in the body."""
        caller = self._create_user(email="caller@example.com")
        other = self._create_user(email="other@example.com")
        self.client.force_authenticate(user=caller)
        response = self.client.get(ME_URL)
        self.assertEqual(response.json()["email"], "caller@example.com")
        self.assertNotIn(other.email, response.content.decode())
        self.assertNotIn(str(other.pk), response.content.decode())


class LogoutTests(BaseSessionApiTestCase):
    """Verifies logout terminates the session rather than merely returning 200."""

    def _login(self, email="logout@example.com", password="StrongPassword123!"):
        """Establishes a real Django session through the login endpoint."""
        self._create_user(email=email, password=password)
        response = self.client.post(
            LOGIN_URL, {"email": email, "password": password}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"authenticated": True})

    def test_logout_returns_200_for_an_authenticated_caller(self):
        """Asserts a logged-in caller can log out successfully."""
        self._login()
        self.assertEqual(self.client.post(LOGOUT_URL).status_code, status.HTTP_200_OK)

    def test_logout_actually_ends_the_session(self):
        """Guards the real security property: /auth/me must be rejected after logout.

        A 200 from logout proves nothing on its own. This asserts the session is genuinely
        terminated by showing an endpoint that worked before logout fails afterwards.
        """
        self._login(email="ends@example.com")
        self.assertEqual(self.client.get(ME_URL).status_code, status.HTTP_200_OK)

        self.assertEqual(self.client.post(LOGOUT_URL).status_code, status.HTTP_200_OK)

        after = self.client.get(ME_URL)
        self.assertIn(after.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_logging_out_twice_is_rejected_rather_than_erroring(self):
        """Asserts a second logout behaves like any unauthenticated request, not a 500."""
        self._login(email="twice@example.com")
        self.assertEqual(self.client.post(LOGOUT_URL).status_code, status.HTTP_200_OK)
        second = self.client.post(LOGOUT_URL)
        self.assertIn(second.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])


class OutOfScopeSessionRouteTests(BaseSessionApiTestCase):
    """Verifies per-session management stayed out of the Phase 1 API surface."""

    def test_session_listing_and_revocation_routes_do_not_exist(self):
        """Asserts GET /auth/sessions and the revoke route are absent (404)."""
        self.client.force_authenticate(user=self._create_user(email="scope@example.com"))
        listing = self.client.get("/api/v1/auth/sessions")
        self.assertEqual(listing.status_code, status.HTTP_404_NOT_FOUND)
        revoke = self.client.post(
            "/api/v1/auth/sessions/3f0f1a1e-0000-4000-8000-000000000000/revoke"
        )
        self.assertEqual(revoke.status_code, status.HTTP_404_NOT_FOUND)


class AccountsArchitectureGuardTests(TestCase):
    """Verifies no session or token model was introduced by this Story."""

    def test_accounts_app_exposes_only_the_approved_models(self):
        """Asserts set equality so a UserSession or token model fails loudly."""
        names = {m.__name__ for m in apps.get_app_config("accounts").get_models()}
        self.assertEqual(names, {"User", "CoachProfile", "ClientProfile", "CoachSecurity"})
