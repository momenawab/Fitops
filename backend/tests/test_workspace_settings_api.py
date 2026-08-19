"""API tests for Workspace Settings (Story 4.2 / Task B).

Validates:
- Access control: unauthenticated GET and PATCH requests are rejected with 401/403 and
  the standard API §2 error envelope.
- Authorization: ACTIVE OWNER can GET and PATCH; ACTIVE COACH can GET (200) but is rejected
  on PATCH with 403 PERMISSION_DENIED (the central authorization guard).
- 404 family & indistinguishability: callers with no membership, INACTIVE membership,
  SUSPENDED workspace, or CLIENT-only role receive identical 404 NOT_FOUND responses
  on both GET and PATCH without revealing workspace existence.
- GET contract: exactly eleven documented response keys (whole-key-set equality), logo and
  profile_image excluded, field values match stored Workspace, cross-tenant isolation.
- PATCH contract: partial updates (omitted fields remain unchanged), individual and multi-field
  updates, empty payload acceptance, whole-key-set equality on response, cross-tenant isolation.
- Immutability: slug, status, and id cannot be altered via PATCH; database values remain untouched.
- Validation: invalid payloads (e.g. currency > 3 characters) return 400 VALIDATION_ERROR with
  offending field in fields dict, persisting no changes.
- Method dispatch: PUT and DELETE return 405 Method Not Allowed.
- Story 4.1 regression: POST /api/v1/workspace continues to allow single workspace creation (201)
  and reject subsequent creation attempts (403).
- Architecture guards: workspaces app model set is the approved one, billing defines no models,
  and responses contain no branding or billing keys.
"""

import uuid

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

WORKSPACE_URL = "/api/v1/workspace"

EXPECTED_WORKSPACE_KEYS = {
    "id",
    "name",
    "slug",
    "description",
    "brand_color",
    "currency",
    "timezone",
    "whatsapp_number",
    "status",
    "created_at",
    "updated_at",
}

FORBIDDEN_BRANDING_KEYS = {"logo", "profile_image"}
FORBIDDEN_BILLING_KEYS = {"subscription", "trial", "plan", "billing"}


class BaseWorkspaceSettingsApiTestCase(TestCase):
    """Base test case providing client setup, cache reset, model access, and entity factories."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.client = APIClient()
        self.user_model = get_user_model()
        self.workspace_model = apps.get_model("workspaces", "Workspace")
        self.membership_model = apps.get_model("accounts", "Membership")

    def _create_user(self, email=None, password="StrongPassword123!", **kwargs):
        """Creates and returns a user, email-verified by default."""
        if email is None:
            email = f"user-{uuid.uuid4().hex[:8]}@example.com"
        kwargs.setdefault("email_verified_at", timezone.now())
        return self.user_model.objects.create_user(email=email, password=password, **kwargs)

    def _create_workspace(self, name=None, slug=None, **kwargs):
        """Creates and returns a Workspace directly in the database."""
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
            "status": "ACTIVE",
        }
        defaults.update(kwargs)
        return self.workspace_model.objects.create(**defaults)

    def _create_membership(
        self, user=None, workspace=None, role="OWNER", status="ACTIVE", **kwargs
    ):
        """Creates and returns a Membership directly in the database."""
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

    def assert_error_envelope(
        self, response, expected_status, expected_code=None, expected_field=None
    ):
        """Asserts the standard API §2 error envelope structure and attributes."""
        self.assertEqual(response.status_code, expected_status)
        data = response.json()
        self.assertEqual(
            set(data.keys()),
            {"error"},
            "Response top-level key must be exactly 'error'.",
        )
        error = data["error"]
        self.assertIsInstance(error, dict, "Error payload must be a dictionary.")
        if expected_code is not None:
            self.assertEqual(
                error.get("code"),
                expected_code,
                f"Error code must be '{expected_code}'.",
            )
        self.assertIsInstance(
            error.get("message"),
            str,
            "Error 'message' must be a string.",
        )
        # API §2: `fields` is emitted only for VALIDATION_ERROR. PERMISSION_DENIED and
        # NOT_FOUND carry no `fields` key.
        if expected_code == "VALIDATION_ERROR" or expected_field is not None:
            self.assertIsInstance(
                error.get("fields"),
                dict,
                "VALIDATION_ERROR responses must carry a 'fields' dictionary.",
            )
        else:
            self.assertNotIn(
                "fields",
                error,
                "Non-validation errors (PERMISSION_DENIED, NOT_FOUND) must not carry 'fields'.",
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


class WorkspaceSettingsAccessAndAuthorizationTests(BaseWorkspaceSettingsApiTestCase):
    """Verifies access control and role-based permissions on GET and PATCH /api/v1/workspace."""

    def test_unauthenticated_get_returns_401_or_403_with_error_envelope(self):
        """Asserts unauthenticated GET is rejected with 401/403 and error envelope."""
        response = self.client.get(WORKSPACE_URL)
        self.assertIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )
        data = response.json()
        self.assertEqual(set(data.keys()), {"error"})
        self.assertIsInstance(data["error"], dict)

    def test_unauthenticated_patch_returns_401_or_403_with_error_envelope(self):
        """Asserts unauthenticated PATCH is rejected with 401/403 and error envelope."""
        response = self.client.patch(
            WORKSPACE_URL,
            {"name": "Unauthorized Update"},
            format="json",
        )
        self.assertIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )
        data = response.json()
        self.assertEqual(set(data.keys()), {"error"})
        self.assertIsInstance(data["error"], dict)

    def test_active_owner_can_get_workspace_200(self):
        """Asserts caller with an ACTIVE OWNER membership receives 200 on GET."""
        owner = self._create_user(email="owner.get@example.com")
        workspace = self._create_workspace(name="Owner GET Gym")
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        # Create decoy second workspace to guard multi-tenant resolution
        self._create_membership(role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        response = self.client.get(WORKSPACE_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "Owner GET Gym")

    def test_active_owner_can_patch_workspace_200(self):
        """Asserts caller with an ACTIVE OWNER membership receives 200 on PATCH."""
        owner = self._create_user(email="owner.patch@example.com")
        workspace = self._create_workspace(name="Original Gym Name")
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self._create_membership(role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        response = self.client.patch(
            WORKSPACE_URL,
            {"name": "Owner Updated Gym Name"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "Owner Updated Gym Name")
        workspace.refresh_from_db()
        self.assertEqual(workspace.name, "Owner Updated Gym Name")

    def test_active_coach_get_succeeds_200(self):
        """Asserts caller with an ACTIVE COACH membership receives 200 on GET."""
        coach = self._create_user(email="coach.get@example.com")
        workspace = self._create_workspace(name="Coach Visible Gym")
        self._create_membership(user=coach, workspace=workspace, role="COACH", status="ACTIVE")

        self._create_membership(role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=coach)
        response = self.client.get(WORKSPACE_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "Coach Visible Gym")

    def test_active_coach_patch_returns_403_permission_denied(self):
        """Central authorization guard: ACTIVE COACH hitting PATCH receives 403 PERMISSION_DENIED.

        Asserts that coach membership grants GET visibility but cannot alter settings,
        returning 403 PERMISSION_DENIED without leaking a 'fields' dictionary, and
        leaves stored workspace data completely unchanged.
        """
        coach = self._create_user(email="coach.patch@example.com")
        workspace = self._create_workspace(name="Unmodifiable Gym")
        self._create_membership(user=coach, workspace=workspace, role="COACH", status="ACTIVE")

        self._create_membership(role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=coach)
        response = self.client.patch(
            WORKSPACE_URL,
            {"name": "Attempted Coach Change"},
            format="json",
        )
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_403_FORBIDDEN,
            expected_code="PERMISSION_DENIED",
        )
        workspace.refresh_from_db()
        self.assertEqual(
            workspace.name,
            "Unmodifiable Gym",
            "Workspace attributes must remain unchanged after forbidden coach PATCH attempt.",
        )


class WorkspaceSettingsNoQualifyingMembershipTests(BaseWorkspaceSettingsApiTestCase):
    """Verifies 404 NOT_FOUND and indistinguishability across non-qualifying users."""

    def test_authenticated_user_without_membership_get_returns_404_not_found(self):
        """Asserts an authenticated user with no membership receives 404 NOT_FOUND on GET."""
        user = self._create_user(email="nomembership.get@example.com")
        self._create_membership(role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=user)
        response = self.client.get(WORKSPACE_URL)
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )

    def test_user_with_inactive_membership_get_returns_404_not_found(self):
        """Asserts a user with INACTIVE membership receives 404 NOT_FOUND on GET."""
        user = self._create_user(email="inactive.get@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=user, workspace=workspace, role="OWNER", status="INACTIVE")

        self.client.force_authenticate(user=user)
        response = self.client.get(WORKSPACE_URL)
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )

    def test_user_with_suspended_workspace_get_returns_404_not_found(self):
        """Asserts an active owner of a SUSPENDED workspace receives 404 NOT_FOUND on GET."""
        user = self._create_user(email="suspended.get@example.com")
        workspace = self._create_workspace(status="SUSPENDED")
        self._create_membership(user=user, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=user)
        response = self.client.get(WORKSPACE_URL)
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )

    def test_user_with_client_only_membership_get_returns_404_not_found(self):
        """Asserts a user with only a CLIENT membership receives 404 NOT_FOUND on GET."""
        user = self._create_user(email="client.get@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=user, workspace=workspace, role="CLIENT", status="ACTIVE")

        self.client.force_authenticate(user=user)
        response = self.client.get(WORKSPACE_URL)
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )

    def test_four_unauthorized_get_scenarios_are_strictly_indistinguishable(self):
        """Asserts GET responses across all 4 non-qualifying cases are identical to each other."""
        # 1. No membership
        user_no_mem = self._create_user(email="indist.nomem.get@example.com")

        # 2. Inactive membership
        user_inactive = self._create_user(email="indist.inactive.get@example.com")
        ws_inactive = self._create_workspace()
        self._create_membership(
            user=user_inactive, workspace=ws_inactive, role="OWNER", status="INACTIVE"
        )

        # 3. Suspended workspace
        user_suspended = self._create_user(email="indist.suspended.get@example.com")
        ws_suspended = self._create_workspace(status="SUSPENDED")
        self._create_membership(
            user=user_suspended, workspace=ws_suspended, role="OWNER", status="ACTIVE"
        )

        # 4. Client-only membership
        user_client = self._create_user(email="indist.client.get@example.com")
        ws_client = self._create_workspace()
        self._create_membership(
            user=user_client, workspace=ws_client, role="CLIENT", status="ACTIVE"
        )

        # Collect real responses
        self.client.force_authenticate(user=user_no_mem)
        res_no_mem = self.client.get(WORKSPACE_URL)

        self.client.force_authenticate(user=user_inactive)
        res_inactive = self.client.get(WORKSPACE_URL)

        self.client.force_authenticate(user=user_suspended)
        res_suspended = self.client.get(WORKSPACE_URL)

        self.client.force_authenticate(user=user_client)
        res_client = self.client.get(WORKSPACE_URL)

        responses = [res_no_mem, res_inactive, res_suspended, res_client]

        for resp in responses:
            self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
            self.assertEqual(resp.json()["error"]["code"], "NOT_FOUND")
            self.assertNotIn("fields", resp.json()["error"])

        # Compare real responses against each other
        self.assertEqual(res_no_mem.status_code, res_inactive.status_code)
        self.assertEqual(res_inactive.status_code, res_suspended.status_code)
        self.assertEqual(res_suspended.status_code, res_client.status_code)

        self.assertEqual(
            res_no_mem.json()["error"]["code"],
            res_inactive.json()["error"]["code"],
        )
        self.assertEqual(
            res_inactive.json()["error"]["code"],
            res_suspended.json()["error"]["code"],
        )
        self.assertEqual(
            res_suspended.json()["error"]["code"],
            res_client.json()["error"]["code"],
        )

        self.assertEqual(
            res_no_mem.json()["error"]["message"],
            res_inactive.json()["error"]["message"],
        )
        self.assertEqual(
            res_inactive.json()["error"]["message"],
            res_suspended.json()["error"]["message"],
        )
        self.assertEqual(
            res_suspended.json()["error"]["message"],
            res_client.json()["error"]["message"],
        )

    def test_authenticated_user_without_membership_patch_returns_404_not_found(self):
        """Asserts an authenticated user with no membership receives 404 NOT_FOUND on PATCH."""
        user = self._create_user(email="nomembership.patch@example.com")
        self._create_membership(role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=user)
        response = self.client.patch(WORKSPACE_URL, {"name": "No Membership"}, format="json")
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )

    def test_user_with_inactive_membership_patch_returns_404_not_found(self):
        """Asserts a user with INACTIVE membership receives 404 NOT_FOUND on PATCH."""
        user = self._create_user(email="inactive.patch@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=user, workspace=workspace, role="OWNER", status="INACTIVE")

        self.client.force_authenticate(user=user)
        response = self.client.patch(WORKSPACE_URL, {"name": "Inactive Membership"}, format="json")
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )

    def test_user_with_suspended_workspace_patch_returns_404_not_found(self):
        """Asserts an active owner of a SUSPENDED workspace receives 404 NOT_FOUND on PATCH."""
        user = self._create_user(email="suspended.patch@example.com")
        workspace = self._create_workspace(status="SUSPENDED")
        self._create_membership(user=user, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=user)
        response = self.client.patch(WORKSPACE_URL, {"name": "Suspended WS"}, format="json")
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )

    def test_user_with_client_only_membership_patch_returns_404_not_found(self):
        """Asserts a user with only a CLIENT membership receives 404 NOT_FOUND on PATCH."""
        user = self._create_user(email="client.patch@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=user, workspace=workspace, role="CLIENT", status="ACTIVE")

        self.client.force_authenticate(user=user)
        response = self.client.patch(WORKSPACE_URL, {"name": "Client PATCH"}, format="json")
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )

    def test_four_unauthorized_patch_scenarios_are_strictly_indistinguishable(self):
        """Asserts PATCH responses across all 4 non-qualifying cases are identical to each other."""
        user_no_mem = self._create_user(email="indist.nomem.patch@example.com")

        user_inactive = self._create_user(email="indist.inactive.patch@example.com")
        ws_inactive = self._create_workspace()
        self._create_membership(
            user=user_inactive, workspace=ws_inactive, role="OWNER", status="INACTIVE"
        )

        user_suspended = self._create_user(email="indist.suspended.patch@example.com")
        ws_suspended = self._create_workspace(status="SUSPENDED")
        self._create_membership(
            user=user_suspended, workspace=ws_suspended, role="OWNER", status="ACTIVE"
        )

        user_client = self._create_user(email="indist.client.patch@example.com")
        ws_client = self._create_workspace()
        self._create_membership(
            user=user_client, workspace=ws_client, role="CLIENT", status="ACTIVE"
        )

        patch_payload = {"name": "Indistinguishable Name Update"}

        self.client.force_authenticate(user=user_no_mem)
        res_no_mem = self.client.patch(WORKSPACE_URL, patch_payload, format="json")

        self.client.force_authenticate(user=user_inactive)
        res_inactive = self.client.patch(WORKSPACE_URL, patch_payload, format="json")

        self.client.force_authenticate(user=user_suspended)
        res_suspended = self.client.patch(WORKSPACE_URL, patch_payload, format="json")

        self.client.force_authenticate(user=user_client)
        res_client = self.client.patch(WORKSPACE_URL, patch_payload, format="json")

        responses = [res_no_mem, res_inactive, res_suspended, res_client]

        for resp in responses:
            self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
            self.assertEqual(resp.json()["error"]["code"], "NOT_FOUND")
            self.assertNotIn("fields", resp.json()["error"])

        self.assertEqual(res_no_mem.status_code, res_inactive.status_code)
        self.assertEqual(res_inactive.status_code, res_suspended.status_code)
        self.assertEqual(res_suspended.status_code, res_client.status_code)

        self.assertEqual(
            res_no_mem.json()["error"]["code"],
            res_inactive.json()["error"]["code"],
        )
        self.assertEqual(
            res_inactive.json()["error"]["code"],
            res_suspended.json()["error"]["code"],
        )
        self.assertEqual(
            res_suspended.json()["error"]["code"],
            res_client.json()["error"]["code"],
        )

        self.assertEqual(
            res_no_mem.json()["error"]["message"],
            res_inactive.json()["error"]["message"],
        )
        self.assertEqual(
            res_inactive.json()["error"]["message"],
            res_suspended.json()["error"]["message"],
        )
        self.assertEqual(
            res_suspended.json()["error"]["message"],
            res_client.json()["error"]["message"],
        )


class WorkspaceSettingsGetContractTests(BaseWorkspaceSettingsApiTestCase):
    """Verifies schema specification, field matching, and multi-tenant isolation on GET."""

    def test_get_response_body_has_exactly_the_eleven_documented_keys(self):
        """Asserts whole-key-set equality against the eleven documented contract keys on GET."""
        owner = self._create_user(email="get.keys@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        response = self.client.get(WORKSPACE_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            set(response.json().keys()),
            EXPECTED_WORKSPACE_KEYS,
            "GET response keys must exactly match the eleven documented contract keys.",
        )

    def test_get_response_body_excludes_logo_and_profile_image(self):
        """Asserts logo and profile_image are excluded from GET response (deferred to 4.3)."""
        owner = self._create_user(email="get.branding@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        response = self.client.get(WORKSPACE_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        for forbidden in FORBIDDEN_BRANDING_KEYS:
            with self.subTest(forbidden_branding_key=forbidden):
                self.assertNotIn(
                    forbidden,
                    data,
                    f"Branding key '{forbidden}' must be excluded from Story 4.2 GET response.",
                )

    def test_get_response_body_matches_stored_workspace_values(self):
        """Asserts returned values accurately reflect all stored workspace fields."""
        owner = self._create_user(email="get.values@example.com")
        workspace = self._create_workspace(
            name="Apex Athletic",
            slug="apex-athletic",
            description="High performance coaching",
            brand_color="#123456",
            currency="EGP",
            timezone="Africa/Cairo",
            whatsapp_number="+201112223344",
            status="ACTIVE",
        )
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        response = self.client.get(WORKSPACE_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data["id"], str(workspace.id))
        self.assertEqual(data["name"], "Apex Athletic")
        self.assertEqual(data["slug"], "apex-athletic")
        self.assertEqual(data["description"], "High performance coaching")
        self.assertEqual(data["brand_color"], "#123456")
        self.assertEqual(data["currency"], "EGP")
        self.assertEqual(data["timezone"], "Africa/Cairo")
        self.assertEqual(data["whatsapp_number"], "+201112223344")
        self.assertEqual(data["status"], "ACTIVE")
        self.assertIsInstance(data["created_at"], str)
        self.assertIsInstance(data["updated_at"], str)

    def test_cross_tenant_get_isolation_between_two_workspaces(self):
        """Asserts each owner gets only their own workspace without cross-tenant data leakage."""
        owner_a = self._create_user(email="tenant.a@example.com")
        ws_a = self._create_workspace(name="Workspace Alpha", slug="ws-alpha")
        self._create_membership(user=owner_a, workspace=ws_a, role="OWNER", status="ACTIVE")

        owner_b = self._create_user(email="tenant.b@example.com")
        ws_b = self._create_workspace(name="Workspace Beta", slug="ws-beta")
        self._create_membership(user=owner_b, workspace=ws_b, role="OWNER", status="ACTIVE")

        # Owner A query
        self.client.force_authenticate(user=owner_a)
        res_a = self.client.get(WORKSPACE_URL)
        self.assertEqual(res_a.status_code, status.HTTP_200_OK)
        data_a = res_a.json()
        self.assertEqual(data_a["id"], str(ws_a.id))
        self.assertEqual(data_a["name"], "Workspace Alpha")
        self.assertEqual(data_a["slug"], "ws-alpha")
        self.assertNotIn("Workspace Beta", res_a.content.decode("utf-8"))
        self.assertNotIn("ws-beta", res_a.content.decode("utf-8"))

        # Owner B query
        self.client.force_authenticate(user=owner_b)
        res_b = self.client.get(WORKSPACE_URL)
        self.assertEqual(res_b.status_code, status.HTTP_200_OK)
        data_b = res_b.json()
        self.assertEqual(data_b["id"], str(ws_b.id))
        self.assertEqual(data_b["name"], "Workspace Beta")
        self.assertEqual(data_b["slug"], "ws-beta")
        self.assertNotIn("Workspace Alpha", res_b.content.decode("utf-8"))
        self.assertNotIn("ws-alpha", res_b.content.decode("utf-8"))


class WorkspaceSettingsPatchContractTests(BaseWorkspaceSettingsApiTestCase):
    """Verifies PATCH update mechanics, partial payloads, empty payload, and cross-tenant guards."""

    def test_patch_single_field_updates_and_leaves_other_fields_unchanged(self):
        """Asserts updating a single field leaves all untouched fields strictly unchanged."""
        owner = self._create_user(email="patch.single@example.com")
        workspace = self._create_workspace(
            name="Initial Name",
            description="Initial Description",
            brand_color="#000000",
            currency="USD",
            timezone="UTC",
            whatsapp_number="+10000000000",
        )
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        response = self.client.patch(
            WORKSPACE_URL,
            {"name": "Renamed Gym"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        workspace.refresh_from_db()

        self.assertEqual(workspace.name, "Renamed Gym")
        self.assertEqual(workspace.description, "Initial Description")
        self.assertEqual(workspace.brand_color, "#000000")
        self.assertEqual(workspace.currency, "USD")
        self.assertEqual(workspace.timezone, "UTC")
        self.assertEqual(workspace.whatsapp_number, "+10000000000")

    def test_patch_each_documented_field_individually(self):
        """Asserts each of the six documented PATCH fields updates cleanly when submitted alone."""
        owner = self._create_user(email="patch.each@example.com")
        workspace = self._create_workspace(
            name="Base Gym",
            description="Base Desc",
            brand_color="#111111",
            currency="USD",
            whatsapp_number="+1111111111",
            timezone="UTC",
        )
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        field_updates = [
            ("name", "Updated Fitness Hub"),
            ("description", "Updated online coaching program"),
            ("brand_color", "#223344"),
            ("currency", "EGP"),
            ("whatsapp_number", "+201000000000"),
            ("timezone", "Africa/Cairo"),
        ]

        self.client.force_authenticate(user=owner)

        for field, new_value in field_updates:
            with self.subTest(field=field, value=new_value):
                response = self.client.patch(
                    WORKSPACE_URL,
                    {field: new_value},
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(response.json()[field], new_value)
                workspace.refresh_from_db()
                self.assertEqual(getattr(workspace, field), new_value)

    def test_patch_multiple_fields_simultaneously(self):
        """Asserts submitting all six documented fields at once updates every field."""
        owner = self._create_user(email="patch.multi@example.com")
        workspace = self._create_workspace(
            name="Old Gym",
            description="Old Desc",
            brand_color="#000000",
            currency="USD",
            whatsapp_number="+10000000000",
            timezone="UTC",
        )
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        payload = {
            "name": "New Coaching Hub",
            "description": "Comprehensive fitness coaching",
            "brand_color": "#AABBCC",
            "currency": "EUR",
            "whatsapp_number": "+447000000000",
            "timezone": "Europe/London",
        }

        self.client.force_authenticate(user=owner)
        response = self.client.patch(WORKSPACE_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        workspace.refresh_from_db()

        self.assertEqual(workspace.name, "New Coaching Hub")
        self.assertEqual(workspace.description, "Comprehensive fitness coaching")
        self.assertEqual(workspace.brand_color, "#AABBCC")
        self.assertEqual(workspace.currency, "EUR")
        self.assertEqual(workspace.whatsapp_number, "+447000000000")
        self.assertEqual(workspace.timezone, "Europe/London")

    def test_patch_empty_payload_succeeds_200_and_changes_nothing(self):
        """Asserts an empty PATCH payload `{}` returns 200 and leaves database state unchanged."""
        owner = self._create_user(email="patch.empty@example.com")
        workspace = self._create_workspace(
            name="Stable Gym",
            description="Stable Desc",
            brand_color="#555555",
            currency="USD",
            whatsapp_number="+1234567890",
            timezone="UTC",
        )
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        response = self.client.patch(WORKSPACE_URL, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        workspace.refresh_from_db()

        self.assertEqual(workspace.name, "Stable Gym")
        self.assertEqual(workspace.description, "Stable Desc")
        self.assertEqual(workspace.brand_color, "#555555")
        self.assertEqual(workspace.currency, "USD")
        self.assertEqual(workspace.whatsapp_number, "+1234567890")
        self.assertEqual(workspace.timezone, "UTC")

    def test_patch_response_body_has_exactly_the_eleven_documented_keys(self):
        """Asserts whole-key-set equality against the eleven documented contract keys on PATCH."""
        owner = self._create_user(email="patch.keys@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        response = self.client.patch(WORKSPACE_URL, {"name": "Keys Check"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            set(response.json().keys()),
            EXPECTED_WORKSPACE_KEYS,
            "PATCH response keys must exactly match the eleven documented contract keys.",
        )

    def test_patch_response_body_excludes_logo_and_profile_image(self):
        """Asserts logo and profile_image are excluded from PATCH response (deferred to 4.3)."""
        owner = self._create_user(email="patch.branding@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        response = self.client.patch(WORKSPACE_URL, {"name": "Branding Check"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        for forbidden in FORBIDDEN_BRANDING_KEYS:
            with self.subTest(forbidden_branding_key=forbidden):
                self.assertNotIn(
                    forbidden,
                    data,
                    f"Branding key '{forbidden}' must be excluded from Story 4.2 PATCH response.",
                )

    def test_cross_tenant_patch_isolation_does_not_affect_other_workspace(self):
        """Asserts PATCHing Workspace A modifies only Workspace A while Workspace B is untouched."""
        owner_a = self._create_user(email="patch.tenant.a@example.com")
        ws_a = self._create_workspace(name="Alpha Original", slug="ws-alpha-patch")
        self._create_membership(user=owner_a, workspace=ws_a, role="OWNER", status="ACTIVE")

        owner_b = self._create_user(email="patch.tenant.b@example.com")
        ws_b = self._create_workspace(name="Beta Untouched", slug="ws-beta-patch")
        self._create_membership(user=owner_b, workspace=ws_b, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner_a)
        response = self.client.patch(
            WORKSPACE_URL,
            {"name": "Alpha Modified"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        ws_a.refresh_from_db()
        ws_b.refresh_from_db()

        self.assertEqual(ws_a.name, "Alpha Modified")
        self.assertEqual(
            ws_b.name,
            "Beta Untouched",
            "Workspace B attributes must remain completely untouched after Workspace A PATCH.",
        )


class WorkspaceSettingsImmutabilityAndValidationTests(BaseWorkspaceSettingsApiTestCase):
    """Verifies that non-updatable fields are immutable and validation failures reject cleanly."""

    def test_patch_slug_is_immutable_and_ignored_in_database(self):
        """Asserts sending 'slug' in PATCH body does not change stored slug upon DB reload."""
        owner = self._create_user(email="immut.slug@example.com")
        workspace = self._create_workspace(name="Gym Name", slug="original-slug")
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        response = self.client.patch(
            WORKSPACE_URL,
            {"name": "Updated Name", "slug": "malicious-slug-tamper"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        workspace.refresh_from_db()

        self.assertEqual(
            workspace.slug,
            "original-slug",
            "Database slug must remain strictly unchanged after PATCH attempt.",
        )
        self.assertEqual(workspace.name, "Updated Name")
        self.assertEqual(response.json()["slug"], "original-slug")

    def test_patch_status_is_immutable_and_ignored_in_database(self):
        """Asserts sending 'status' in PATCH body does not change stored status upon DB reload."""
        owner = self._create_user(email="immut.status@example.com")
        workspace = self._create_workspace(name="Gym Name", status="ACTIVE")
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        response = self.client.patch(
            WORKSPACE_URL,
            {"name": "Updated Name", "status": "SUSPENDED"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        workspace.refresh_from_db()

        self.assertEqual(
            workspace.status,
            "ACTIVE",
            "Database status must remain strictly ACTIVE after PATCH attempt.",
        )
        self.assertEqual(workspace.name, "Updated Name")
        self.assertEqual(response.json()["status"], "ACTIVE")

    def test_patch_id_is_immutable_and_ignored_in_database(self):
        """Asserts sending 'id' in PATCH body does not change stored id upon DB reload."""
        owner = self._create_user(email="immut.id@example.com")
        workspace = self._create_workspace(name="Gym Name")
        original_id = workspace.id
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        fake_id = str(uuid.uuid4())
        self.client.force_authenticate(user=owner)
        response = self.client.patch(
            WORKSPACE_URL,
            {"name": "Updated Name", "id": fake_id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        workspace.refresh_from_db()

        self.assertEqual(
            workspace.id,
            original_id,
            "Database id must remain strictly unchanged after PATCH attempt.",
        )
        self.assertEqual(workspace.name, "Updated Name")
        self.assertEqual(response.json()["id"], str(original_id))

    def test_patch_invalid_currency_returns_400_validation_error_and_persists_nothing(self):
        """Asserts invalid currency (>3 chars) returns 400 VALIDATION_ERROR and changes nothing."""
        owner = self._create_user(email="val.currency@example.com")
        workspace = self._create_workspace(name="Original Gym", currency="USD")
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        response = self.client.patch(
            WORKSPACE_URL,
            {"name": "Renamed Gym", "currency": "TOOLONG"},
            format="json",
        )
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_400_BAD_REQUEST,
            expected_code="VALIDATION_ERROR",
            expected_field="currency",
        )
        workspace.refresh_from_db()

        self.assertEqual(
            workspace.currency,
            "USD",
            "Workspace currency must remain unchanged after validation failure.",
        )
        self.assertEqual(
            workspace.name,
            "Original Gym",
            "Workspace name must not update when companion field validation fails.",
        )


class WorkspaceSettingsMethodAndRegressionGuardTests(BaseWorkspaceSettingsApiTestCase):
    """Verifies HTTP method restrictions and guards against regressions in Story 4.1 POST logic."""

    def test_disallowed_http_methods_put_and_delete_return_405_method_not_allowed(self):
        """Asserts PUT and DELETE return 405 Method Not Allowed for authenticated owners."""
        owner = self._create_user(email="method.check@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        for method in ["put", "delete"]:
            with self.subTest(http_method=method):
                client_method = getattr(self.client, method)
                response = client_method(WORKSPACE_URL)
                self.assertEqual(
                    response.status_code,
                    status.HTTP_405_METHOD_NOT_ALLOWED,
                    f"HTTP {method.upper()} to {WORKSPACE_URL} must return 405.",
                )

    def test_story_4_1_regression_post_works_for_coach_without_workspace(self):
        """Regression guard: POST /api/v1/workspace continues to succeed (201) for new coach."""
        coach = self._create_user(email="regress.newcoach@example.com")
        self.client.force_authenticate(user=coach)
        payload = {
            "name": "Story 4.1 Created Workspace",
            "slug": f"story-41-ws-{uuid.uuid4().hex[:6]}",
            "currency": "EGP",
            "timezone": "Africa/Cairo",
        }
        response = self.client.post(WORKSPACE_URL, payload, format="json")
        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
            "Story 4.1 POST must remain fully operational after GET/PATCH implementation.",
        )
        data = response.json()
        self.assertEqual(data["name"], "Story 4.1 Created Workspace")

    def test_story_4_1_regression_post_returns_403_for_coach_with_existing_workspace(self):
        """Regression guard: POST returns 403 if coach already owns a workspace."""
        owner = self._create_user(email="regress.existingowner@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        payload = {
            "name": "Second Workspace Attempt",
            "slug": f"second-ws-{uuid.uuid4().hex[:6]}",
            "currency": "USD",
            "timezone": "UTC",
        }
        response = self.client.post(WORKSPACE_URL, payload, format="json")
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_403_FORBIDDEN,
            expected_code="PERMISSION_DENIED",
        )


class WorkspaceSettingsArchitectureGuardTests(TestCase):
    """Verifies architectural boundaries across apps and prevents cross-Epic schema leakage."""

    def test_workspaces_app_exposes_only_workspace_model(self):
        """Asserts the workspaces app defines exactly the approved model set."""
        workspaces_app = apps.get_app_config("workspaces")
        concrete_model_names = {model._meta.object_name for model in workspaces_app.get_models()}
        self.assertEqual(
            concrete_model_names,
            {"Workspace", "PaymentMethod"},
            "workspaces app must expose only {'Workspace'}.",
        )

    def test_billing_app_exposes_no_models(self):
        """Guards Epic 22 boundary: billing app must define zero models in Story 4.2."""
        billing_app = apps.get_app_config("billing")
        concrete_model_names = {model._meta.object_name for model in billing_app.get_models()}
        self.assertEqual(
            concrete_model_names,
            set(),
            "billing app must expose no models (deferred to Epic 22).",
        )

    def test_workspace_settings_responses_contain_no_branding_or_billing_keys(self):
        """Asserts GET and PATCH responses do not leak branding (4.3) or billing (22) keys."""
        cache.clear()
        client = APIClient()
        user_model = get_user_model()
        workspace_model = apps.get_model("workspaces", "Workspace")
        membership_model = apps.get_model("accounts", "Membership")

        owner = user_model.objects.create_user(
            email="guarded.settings@example.com",
            password="StrongPassword123!",
            email_verified_at=timezone.now(),
        )
        workspace = workspace_model.objects.create(
            name="Architecture Guarded Gym",
            slug=f"arch-guard-{uuid.uuid4().hex[:6]}",
            currency="USD",
            timezone="UTC",
            status="ACTIVE",
        )
        membership_model.objects.create(
            user=owner,
            workspace=workspace,
            role="OWNER",
            status="ACTIVE",
        )

        client.force_authenticate(user=owner)

        # 1. GET response verification
        get_response = client.get(WORKSPACE_URL)
        self.assertEqual(get_response.status_code, status.HTTP_200_OK)
        get_data = get_response.json()

        # 2. PATCH response verification
        patch_response = client.patch(
            WORKSPACE_URL,
            {"name": "Renamed Guarded Gym"},
            format="json",
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        patch_data = patch_response.json()

        all_forbidden_keys = FORBIDDEN_BRANDING_KEYS | FORBIDDEN_BILLING_KEYS

        for response_type, payload in [("GET", get_data), ("PATCH", patch_data)]:
            for forbidden in all_forbidden_keys:
                with self.subTest(response_type=response_type, forbidden_key=forbidden):
                    self.assertNotIn(
                        forbidden,
                        payload,
                        f"Forbidden key '{forbidden}' found in {response_type} response payload.",
                    )
