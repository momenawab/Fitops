"""API tests for Workspace Creation (Story 4.1 / Task B).

Validates:
- Access control: unauthenticated callers are rejected with 401/403 and standard error envelope
- Method dispatch: non-POST HTTP methods (GET, PUT, PATCH, DELETE) return 405 Method Not Allowed
- Success contract: exactly eleven documented response keys, whole-key-set equality,
  logo and profile_image excluded, echoed request fields and default values
- Atomic transaction effects: Workspace created, Membership(role=OWNER, status=ACTIVE) created,
  AuditLog(action="WORKSPACE_CREATED", target_type="Workspace") event recorded
- Ownership rule: caller already owning a Workspace is rejected with 403 PERMISSION_DENIED;
  callers with only CLIENT or COACH memberships can still create a Workspace (201)
- Duplicate slug handling: 409 CONFLICT returned when slug is taken by another workspace
- Rollback atomicity: on duplicate slug or validation errors, no Workspace, Membership,
  or AuditLog records are persisted (counts unchanged)
- Field validation: missing name, slug, currency, timezone, or empty payload return 400
  VALIDATION_ERROR with field-level details
- Cross-Epic architecture guards: audit defines exactly {"AuditLog"}, workspaces defines
  {"Workspace"}, billing defines no models, and no subscription/trial keys in response
"""

import uuid
from datetime import datetime
from unittest.mock import patch

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

FORBIDDEN_BILLING_KEYS = {"subscription", "trial", "plan", "billing"}


class BaseWorkspaceCreateApiTestCase(TestCase):
    """Base test case providing client initialization, cache clearing, and entity helpers."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.client = APIClient()
        self.user_model = get_user_model()
        self.workspace_model = apps.get_model("workspaces", "Workspace")
        self.membership_model = apps.get_model("accounts", "Membership")
        self.audit_log_model = apps.get_model("audit", "AuditLog")

    def _create_user(self, email=None, password="StrongPassword123!", **kwargs):
        """Creates and returns a user, email-verified by default."""
        if email is None:
            email = f"coach-{uuid.uuid4().hex[:8]}@example.com"
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
        }
        defaults.update(kwargs)
        return self.workspace_model.objects.create(**defaults)

    def _create_membership(
        self, user=None, workspace=None, role="COACH", status="ACTIVE", **kwargs
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
        # API §2: `fields` is emitted only for field-level validation errors. CONFLICT and
        # PERMISSION_DENIED carry no `fields` key, so asserting it unconditionally is wrong.
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
                "Non-validation errors must not carry a 'fields' key.",
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


class WorkspaceCreateEndpointAccessTests(BaseWorkspaceCreateApiTestCase):
    """Verifies access control, authentication, and HTTP method enforcement."""

    def test_unauthenticated_post_returns_401_or_403_with_error_envelope(self):
        """Asserts unauthenticated POST is rejected with 401/403 and error envelope."""
        payload = {
            "name": "Bergo Coaching",
            "slug": "bergo",
            "currency": "EGP",
            "timezone": "Africa/Cairo",
        }
        response = self.client.post(WORKSPACE_URL, payload, format="json")
        self.assertIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )
        data = response.json()
        self.assertEqual(set(data.keys()), {"error"})
        self.assertEqual(self.workspace_model.objects.count(), 0)
        self.assertEqual(self.membership_model.objects.count(), 0)
        self.assertEqual(self.audit_log_model.objects.count(), 0)

    def test_authenticated_coach_without_workspace_can_access_post(self):
        """Asserts an authenticated coach with no owned workspace succeeds with 201."""
        user = self._create_user(email="newcoach@example.com")
        self.client.force_authenticate(user=user)
        payload = {
            "name": "Bergo Coaching",
            "slug": "bergo",
            "currency": "EGP",
            "timezone": "Africa/Cairo",
        }
        response = self.client.post(WORKSPACE_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_disallowed_http_methods_return_405_method_not_allowed(self):
        """Asserts non-POST HTTP methods return 405 Method Not Allowed for authenticated users."""
        user = self._create_user(email="methodcheck@example.com")
        self.client.force_authenticate(user=user)
        for method in ["get", "put", "patch", "delete"]:
            with self.subTest(http_method=method):
                client_method = getattr(self.client, method)
                response = client_method(WORKSPACE_URL)
                self.assertEqual(
                    response.status_code,
                    status.HTTP_405_METHOD_NOT_ALLOWED,
                    f"HTTP {method.upper()} to {WORKSPACE_URL} must return 405.",
                )


class WorkspaceCreateSuccessContractTests(BaseWorkspaceCreateApiTestCase):
    """Verifies the exact 201 response schema, field echoing, defaults, and typing."""

    def test_response_body_has_exactly_the_eleven_documented_keys(self):
        """Asserts whole-key-set equality against the eleven documented contract keys."""
        user = self._create_user(email="contract.keys@example.com")
        self.client.force_authenticate(user=user)
        payload = {
            "name": "Bergo Coaching",
            "slug": "bergo",
            "currency": "EGP",
            "timezone": "Africa/Cairo",
        }
        response = self.client.post(WORKSPACE_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            set(response.json().keys()),
            EXPECTED_WORKSPACE_KEYS,
            "Response keys must exactly match the eleven documented contract keys.",
        )

    def test_response_body_excludes_logo_and_profile_image(self):
        """Asserts logo and profile_image fields are excluded from creation response."""
        user = self._create_user(email="branding.excluded@example.com")
        self.client.force_authenticate(user=user)
        payload = {
            "name": "Bergo Coaching",
            "slug": "bergo",
            "currency": "EGP",
            "timezone": "Africa/Cairo",
        }
        response = self.client.post(WORKSPACE_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertNotIn("logo", data, "logo must be excluded from Story 4.1 response.")
        self.assertNotIn(
            "profile_image",
            data,
            "profile_image must be excluded from Story 4.1 response.",
        )

    def test_response_body_echoes_request_fields_and_default_values(self):
        """Asserts response correctly echoes submitted values and empty optional defaults."""
        user = self._create_user(email="echo.fields@example.com")
        self.client.force_authenticate(user=user)
        payload = {
            "name": "Bergo Coaching",
            "slug": "bergo",
            "currency": "EGP",
            "timezone": "Africa/Cairo",
        }
        response = self.client.post(WORKSPACE_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data["name"], "Bergo Coaching")
        self.assertEqual(data["slug"], "bergo")
        self.assertEqual(data["currency"], "EGP")
        self.assertEqual(data["timezone"], "Africa/Cairo")
        self.assertEqual(data["status"], "ACTIVE")
        self.assertEqual(data["description"], "")
        self.assertEqual(data["brand_color"], "")
        self.assertEqual(data["whatsapp_number"], "")

    def test_response_id_is_valid_uuid_string_matching_database_record(self):
        """Asserts response id is a valid UUID string matching the persisted Workspace pk."""
        user = self._create_user(email="uuid.match@example.com")
        self.client.force_authenticate(user=user)
        payload = {
            "name": "Bergo Coaching",
            "slug": "bergo-uuid",
            "currency": "EGP",
            "timezone": "Africa/Cairo",
        }
        response = self.client.post(WORKSPACE_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        raw_id = response.json()["id"]
        parsed_uuid = uuid.UUID(raw_id)
        self.assertEqual(str(parsed_uuid), raw_id)

        workspace = self.workspace_model.objects.get(slug="bergo-uuid")
        self.assertEqual(workspace.id, parsed_uuid)

    def test_response_timestamps_are_iso8601_strings(self):
        """Asserts created_at and updated_at in response are ISO8601 datetime strings."""
        user = self._create_user(email="timestamps.iso@example.com")
        self.client.force_authenticate(user=user)
        payload = {
            "name": "Bergo Coaching",
            "slug": "bergo-iso",
            "currency": "EGP",
            "timezone": "Africa/Cairo",
        }
        response = self.client.post(WORKSPACE_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        created_at_dt = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
        updated_at_dt = datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00"))
        self.assertIsInstance(created_at_dt, datetime)
        self.assertIsInstance(updated_at_dt, datetime)

    def test_exactly_one_workspace_exists_after_successful_creation(self):
        """Asserts exactly one Workspace row is created in the database."""
        user = self._create_user(email="single.ws@example.com")
        self.client.force_authenticate(user=user)
        payload = {
            "name": "Bergo Coaching",
            "slug": "bergo-single",
            "currency": "EGP",
            "timezone": "Africa/Cairo",
        }
        initial_count = self.workspace_model.objects.count()
        response = self.client.post(WORKSPACE_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.workspace_model.objects.count(), initial_count + 1)
        self.assertTrue(self.workspace_model.objects.filter(slug="bergo-single").exists())


class WorkspaceCreateTransactionEffectTests(BaseWorkspaceCreateApiTestCase):
    """Verifies all four atomic effects: Workspace, Membership(OWNER), AuditLog."""

    def test_creates_membership_with_role_owner_and_status_active_for_caller(self):
        """Asserts a Membership is created for caller with role=OWNER and status=ACTIVE."""
        coach = self._create_user(email="owner.member@example.com")
        self.client.force_authenticate(user=coach)
        payload = {
            "name": "Bergo Coaching",
            "slug": "bergo-member",
            "currency": "EGP",
            "timezone": "Africa/Cairo",
        }
        response = self.client.post(WORKSPACE_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        workspace = self.workspace_model.objects.get(slug="bergo-member")
        membership = self.membership_model.objects.get(user=coach, workspace=workspace)
        self.assertEqual(membership.role, "OWNER")
        self.assertEqual(membership.status, "ACTIVE")
        self.assertEqual(
            self.membership_model.objects.filter(workspace=workspace).count(),
            1,
            "Exactly one Membership row must be created for the new workspace.",
        )

    def test_writes_exactly_one_audit_log_event(self):
        """Asserts exactly one AuditLog row is created during workspace creation."""
        coach = self._create_user(email="audit.count@example.com")
        self.client.force_authenticate(user=coach)
        payload = {
            "name": "Bergo Coaching",
            "slug": "bergo-audit-count",
            "currency": "EGP",
            "timezone": "Africa/Cairo",
        }
        initial_audit_count = self.audit_log_model.objects.count()
        response = self.client.post(WORKSPACE_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            self.audit_log_model.objects.count(),
            initial_audit_count + 1,
            "Exactly one AuditLog event must be written.",
        )

    def test_audit_log_row_matches_contract_fields_and_references(self):
        """Asserts AuditLog event records WORKSPACE_CREATED, target_type, target_id, and FKs."""
        coach = self._create_user(email="audit.fields@example.com")
        self.client.force_authenticate(user=coach)
        payload = {
            "name": "Bergo Coaching",
            "slug": "bergo-audit-fields",
            "currency": "EGP",
            "timezone": "Africa/Cairo",
        }
        response = self.client.post(WORKSPACE_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        workspace = self.workspace_model.objects.get(slug="bergo-audit-fields")
        audit_log = self.audit_log_model.objects.get(
            action="WORKSPACE_CREATED",
            target_type="Workspace",
            target_id=workspace.id,
        )
        self.assertEqual(audit_log.action, "WORKSPACE_CREATED")
        self.assertEqual(audit_log.target_type, "Workspace")
        self.assertEqual(audit_log.target_id, workspace.id)
        self.assertEqual(audit_log.user, coach)
        self.assertEqual(audit_log.workspace, workspace)
        self.assertIsInstance(audit_log.metadata, dict)


class WorkspaceCreateOwnershipRuleTests(BaseWorkspaceCreateApiTestCase):
    """Verifies that only coaches who do NOT already own a workspace may create one."""

    def test_coach_who_already_owns_a_workspace_is_denied_with_403(self):
        """Asserts a coach with an existing OWNER membership gets 403 PERMISSION_DENIED."""
        owner = self._create_user(email="existing.owner@example.com")
        existing_ws = self._create_workspace(slug="first-owned-ws")
        self._create_membership(user=owner, workspace=existing_ws, role="OWNER")

        self.client.force_authenticate(user=owner)
        payload = {
            "name": "Second Gym",
            "slug": "second-gym",
            "currency": "USD",
            "timezone": "UTC",
        }
        response = self.client.post(WORKSPACE_URL, payload, format="json")
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_403_FORBIDDEN,
            expected_code="PERMISSION_DENIED",
        )
        self.assertFalse(
            self.workspace_model.objects.filter(slug="second-gym").exists(),
            "No second workspace must be created for an existing owner.",
        )

    def test_coach_who_already_owns_a_workspace_persists_nothing_all_counts_unchanged(self):
        """Asserts all counts remain unchanged when an existing owner is rejected."""
        owner = self._create_user(email="counts.owner@example.com")
        existing_ws = self._create_workspace(slug="count-owned-ws")
        self._create_membership(user=owner, workspace=existing_ws, role="OWNER")

        ws_count_before = self.workspace_model.objects.count()
        membership_count_before = self.membership_model.objects.count()
        audit_count_before = self.audit_log_model.objects.count()

        self.client.force_authenticate(user=owner)
        payload = {
            "name": "Denied Workspace",
            "slug": "denied-ws",
            "currency": "USD",
            "timezone": "UTC",
        }
        response = self.client.post(WORKSPACE_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.assertEqual(self.workspace_model.objects.count(), ws_count_before)
        self.assertEqual(self.membership_model.objects.count(), membership_count_before)
        self.assertEqual(self.audit_log_model.objects.count(), audit_count_before)

    def test_user_with_only_client_membership_can_create_workspace(self):
        """Asserts a user who is only a CLIENT in another workspace can create a workspace."""
        client_user = self._create_user(email="client.turning.coach@example.com")
        other_ws = self._create_workspace(slug="other-gym-ws")
        self._create_membership(user=client_user, workspace=other_ws, role="CLIENT")

        self.client.force_authenticate(user=client_user)
        payload = {
            "name": "Client New Gym",
            "slug": "client-new-gym",
            "currency": "USD",
            "timezone": "UTC",
        }
        response = self.client.post(WORKSPACE_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        created_ws = self.workspace_model.objects.get(slug="client-new-gym")
        self.assertTrue(
            self.membership_model.objects.filter(
                user=client_user, workspace=created_ws, role="OWNER"
            ).exists(),
            "A new OWNER membership must be created for the caller in the new workspace.",
        )

    def test_user_with_only_coach_membership_can_create_workspace(self):
        """Asserts a user who is only a COACH in another workspace can create a workspace."""
        coach_user = self._create_user(email="employed.coach@example.com")
        other_ws = self._create_workspace(slug="employed-gym-ws")
        self._create_membership(user=coach_user, workspace=other_ws, role="COACH")

        self.client.force_authenticate(user=coach_user)
        payload = {
            "name": "Employed Coach Own Gym",
            "slug": "coach-own-gym",
            "currency": "USD",
            "timezone": "UTC",
        }
        response = self.client.post(WORKSPACE_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        created_ws = self.workspace_model.objects.get(slug="coach-own-gym")
        self.assertTrue(
            self.membership_model.objects.filter(
                user=coach_user, workspace=created_ws, role="OWNER"
            ).exists(),
            "A new OWNER membership must be created for the coach in their new workspace.",
        )

    def test_user_with_both_client_and_coach_memberships_can_create_workspace(self):
        """Asserts user with multiple non-OWNER memberships can create their first workspace."""
        user = self._create_user(email="multi.non.owner@example.com")
        ws_1 = self._create_workspace(slug="gym-one-ws")
        ws_2 = self._create_workspace(slug="gym-two-ws")
        self._create_membership(user=user, workspace=ws_1, role="CLIENT")
        self._create_membership(user=user, workspace=ws_2, role="COACH")

        self.client.force_authenticate(user=user)
        payload = {
            "name": "First Owned Gym",
            "slug": "first-owned-gym",
            "currency": "USD",
            "timezone": "UTC",
        }
        response = self.client.post(WORKSPACE_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class AuditLogSurvivalTests(BaseWorkspaceCreateApiTestCase):
    """Verifies the audit record outlives the user and workspace it references."""

    def test_audit_log_survives_deletion_of_its_user_and_workspace(self):
        """Guards the SET_NULL decision.

        An audit log is a security record: CASCADE would delete exactly the history that makes
        it an audit log, so both foreign keys are nullable with SET_NULL. Deleting the acting
        user or the workspace must blank the reference, never remove the row.
        """
        user = self._create_user(email="audit.survival@example.com")
        self.client.force_authenticate(user=user)
        response = self.client.post(
            WORKSPACE_URL,
            {
                "name": "Audit Survival",
                "slug": "audit-survival",
                "currency": "EGP",
                "timezone": "Africa/Cairo",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        audit_model = apps.get_model("audit", "AuditLog")
        workspace_model = apps.get_model("workspaces", "Workspace")
        self.assertEqual(audit_model.objects.count(), 1)
        entry_id = audit_model.objects.get().id

        workspace_model.objects.all().delete()
        user.delete()

        self.assertEqual(
            audit_model.objects.filter(pk=entry_id).count(),
            1,
            "The audit record must survive deletion of its user and workspace.",
        )
        entry = audit_model.objects.get(pk=entry_id)
        self.assertIsNone(entry.user_id, "Deleted user must be nulled, not cascade-deleted.")
        self.assertIsNone(entry.workspace_id, "Deleted workspace must be nulled.")
        self.assertEqual(entry.action, "WORKSPACE_CREATED")


class WorkspaceCreateLateFailureAtomicityTests(BaseWorkspaceCreateApiTestCase):
    """Verifies the transaction rolls back a failure that occurs AFTER the Workspace is created."""

    def test_failure_after_workspace_creation_rolls_back_everything(self):
        """Guards the outer transaction itself.

        The duplicate-slug and validation tests fail at the FIRST step, so nothing would have
        been persisted even without a transaction - they cannot detect a missing
        ``transaction.atomic()``. This test forces a failure at the LAST step (the audit event)
        and asserts the Workspace and Membership created before it are rolled back too.
        """
        user = self._create_user(email="late.failure@example.com")
        self.client.force_authenticate(user=user)

        workspace_model = apps.get_model("workspaces", "Workspace")
        membership_model = apps.get_model("accounts", "Membership")
        audit_model = apps.get_model("audit", "AuditLog")

        before = (
            workspace_model.objects.count(),
            membership_model.objects.count(),
            audit_model.objects.count(),
        )

        with patch(
            "apps.workspaces.views.AuditLog.objects.create",
            side_effect=RuntimeError("audit write failed"),
        ):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    WORKSPACE_URL,
                    {
                        "name": "Late Failure Coaching",
                        "slug": "late-failure",
                        "currency": "EGP",
                        "timezone": "Africa/Cairo",
                    },
                    format="json",
                )

        after = (
            workspace_model.objects.count(),
            membership_model.objects.count(),
            audit_model.objects.count(),
        )
        self.assertEqual(
            after,
            before,
            "A failure after Workspace creation must roll back the Workspace and Membership.",
        )


class WorkspaceCreateDuplicateSlugTests(BaseWorkspaceCreateApiTestCase):
    """Verifies duplicate slug conflict detection and transaction rollback."""

    def test_duplicate_slug_from_different_coach_returns_409_conflict(self):
        """Asserts a duplicate slug request from a different coach returns 409 CONFLICT."""
        coach_a = self._create_user(email="coach.a@example.com")
        self.client.force_authenticate(user=coach_a)
        payload_a = {
            "name": "Alpha Coaching",
            "slug": "shared-slug",
            "currency": "USD",
            "timezone": "UTC",
        }
        resp_a = self.client.post(WORKSPACE_URL, payload_a, format="json")
        self.assertEqual(resp_a.status_code, status.HTTP_201_CREATED)

        coach_b = self._create_user(email="coach.b@example.com")
        self.client.force_authenticate(user=coach_b)
        payload_b = {
            "name": "Beta Coaching",
            "slug": "shared-slug",
            "currency": "EUR",
            "timezone": "Europe/Berlin",
        }
        resp_b = self.client.post(WORKSPACE_URL, payload_b, format="json")
        self.assert_error_envelope(
            resp_b,
            expected_status=status.HTTP_409_CONFLICT,
            expected_code="CONFLICT",
        )

    def test_duplicate_slug_rollback_persists_nothing_all_counts_unchanged(self):
        """Asserts duplicate slug failure persists nothing and all three counts are unchanged."""
        existing_ws = self._create_workspace(name="Original WS", slug="taken-slug")
        owner = self._create_user(email="taken.owner@example.com")
        self._create_membership(user=owner, workspace=existing_ws, role="OWNER")

        # Snapshot counts before the failed duplicate slug attempt
        ws_count_before = self.workspace_model.objects.count()
        membership_count_before = self.membership_model.objects.count()
        audit_count_before = self.audit_log_model.objects.count()

        challenger = self._create_user(email="challenger@example.com")
        self.client.force_authenticate(user=challenger)
        payload = {
            "name": "Challenger Coaching",
            "slug": "taken-slug",
            "currency": "USD",
            "timezone": "UTC",
        }
        response = self.client.post(WORKSPACE_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

        # Assert all three database entity counts remain strictly unchanged
        self.assertEqual(
            self.workspace_model.objects.count(),
            ws_count_before,
            "Workspace count must remain unchanged after duplicate slug conflict.",
        )
        self.assertEqual(
            self.membership_model.objects.count(),
            membership_count_before,
            "Membership count must remain unchanged after duplicate slug conflict.",
        )
        self.assertEqual(
            self.audit_log_model.objects.count(),
            audit_count_before,
            "AuditLog count must remain unchanged after duplicate slug conflict.",
        )


class WorkspaceCreateValidationTests(BaseWorkspaceCreateApiTestCase):
    """Verifies §2 validation error handling and rollback on field errors."""

    def test_missing_name_returns_400_validation_error(self):
        """Asserts omitting 'name' returns 400 with VALIDATION_ERROR and name field error."""
        user = self._create_user(email="val.name@example.com")
        self.client.force_authenticate(user=user)
        payload = {
            "slug": "no-name-ws",
            "currency": "USD",
            "timezone": "UTC",
        }
        response = self.client.post(WORKSPACE_URL, payload, format="json")
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_400_BAD_REQUEST,
            expected_code="VALIDATION_ERROR",
            expected_field="name",
        )

    def test_missing_slug_returns_400_validation_error(self):
        """Asserts omitting 'slug' returns 400 with VALIDATION_ERROR and slug field error."""
        user = self._create_user(email="val.slug@example.com")
        self.client.force_authenticate(user=user)
        payload = {
            "name": "No Slug Gym",
            "currency": "USD",
            "timezone": "UTC",
        }
        response = self.client.post(WORKSPACE_URL, payload, format="json")
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_400_BAD_REQUEST,
            expected_code="VALIDATION_ERROR",
            expected_field="slug",
        )

    def test_missing_currency_returns_400_validation_error(self):
        """Asserts omitting 'currency' returns 400 with VALIDATION_ERROR and currency error."""
        user = self._create_user(email="val.currency@example.com")
        self.client.force_authenticate(user=user)
        payload = {
            "name": "No Currency Gym",
            "slug": "no-currency-ws",
            "timezone": "UTC",
        }
        response = self.client.post(WORKSPACE_URL, payload, format="json")
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_400_BAD_REQUEST,
            expected_code="VALIDATION_ERROR",
            expected_field="currency",
        )

    def test_missing_timezone_returns_400_validation_error(self):
        """Asserts omitting 'timezone' returns 400 with VALIDATION_ERROR and timezone error."""
        user = self._create_user(email="val.tz@example.com")
        self.client.force_authenticate(user=user)
        payload = {
            "name": "No Timezone Gym",
            "slug": "no-tz-ws",
            "currency": "USD",
        }
        response = self.client.post(WORKSPACE_URL, payload, format="json")
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_400_BAD_REQUEST,
            expected_code="VALIDATION_ERROR",
            expected_field="timezone",
        )

    def test_empty_payload_returns_400_validation_error(self):
        """Asserts submitting an empty payload returns 400 with VALIDATION_ERROR."""
        user = self._create_user(email="val.empty@example.com")
        self.client.force_authenticate(user=user)
        response = self.client.post(WORKSPACE_URL, {}, format="json")
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_400_BAD_REQUEST,
            expected_code="VALIDATION_ERROR",
        )

    def test_validation_failure_persists_nothing_all_counts_remain_zero(self):
        """Asserts validation failure rolls back completely and persists no records."""
        user = self._create_user(email="val.rollback@example.com")
        self.client.force_authenticate(user=user)
        ws_count_before = self.workspace_model.objects.count()
        membership_count_before = self.membership_model.objects.count()
        audit_count_before = self.audit_log_model.objects.count()

        response = self.client.post(
            WORKSPACE_URL,
            {"name": "Incomplete Payload Gym"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            self.workspace_model.objects.count(),
            ws_count_before,
            "Workspace count must not increase after validation failure.",
        )
        self.assertEqual(
            self.membership_model.objects.count(),
            membership_count_before,
            "Membership count must not increase after validation failure.",
        )
        self.assertEqual(
            self.audit_log_model.objects.count(),
            audit_count_before,
            "AuditLog count must not increase after validation failure.",
        )


class WorkspaceCreateArchitectureGuardTests(TestCase):
    """Verifies architectural boundaries across apps and prevents cross-Epic leakage."""

    def test_audit_app_exposes_exactly_audit_log_model(self):
        """Asserts the audit app defines exactly {"AuditLog"} and no premature models."""
        audit_app = apps.get_app_config("audit")
        concrete_model_names = {model._meta.object_name for model in audit_app.get_models()}
        self.assertEqual(
            concrete_model_names,
            {"AuditLog"},
            "audit app must expose exactly {'AuditLog'}.",
        )

    def test_workspaces_app_exposes_only_workspace_model(self):
        """Asserts the workspaces app defines exactly {"Workspace"} for Story 4.1."""
        workspaces_app = apps.get_app_config("workspaces")
        concrete_model_names = {model._meta.object_name for model in workspaces_app.get_models()}
        self.assertEqual(
            concrete_model_names,
            {"Workspace"},
            "workspaces app must expose only {'Workspace'}.",
        )

    def test_billing_app_exposes_no_models(self):
        """Guards Epic 22 boundary: billing app must define zero models in Story 4.1."""
        billing_app = apps.get_app_config("billing")
        concrete_model_names = {model._meta.object_name for model in billing_app.get_models()}
        self.assertEqual(
            concrete_model_names,
            set(),
            "billing app must expose no models (deferred to Epic 22).",
        )

    def test_workspace_create_response_has_no_billing_subscription_or_plan_keys(self):
        """Asserts creation response does not contain billing/subscription/trial keys."""
        cache.clear()
        client = APIClient()
        user_model = get_user_model()
        user = user_model.objects.create_user(
            email="nobilling@example.com",
            password="StrongPassword123!",
            email_verified_at=timezone.now(),
        )
        client.force_authenticate(user=user)
        payload = {
            "name": "Guarded Gym",
            "slug": "guarded-gym",
            "currency": "USD",
            "timezone": "UTC",
        }
        response = client.post(WORKSPACE_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json()
        for forbidden in FORBIDDEN_BILLING_KEYS:
            with self.subTest(forbidden_key=forbidden):
                self.assertNotIn(
                    forbidden,
                    response_data,
                    f"Forbidden billing/subscription key '{forbidden}' found in response.",
                )
