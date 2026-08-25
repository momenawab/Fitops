"""API and transaction tests for the atomic Application submission endpoint (Story 7.3).

Validates:
- Happy path returns 201 with exact 4 keys {"application_id", "order_id", "order_number",
  "status"} for anonymous caller with full/minimal valid payload (Point 1)
- Application, Membership, and Order are all created by one submission (Point 2)
- All three created records are scoped to slug workspace; foreign workspace untouched (Point 3)
- Membership role is CLIENT and status is ACTIVE (Point 4)
- Order.package is submitted Package; Order.client is accounts.Membership (Point 5)
- Order.amount and currency authoritatively taken from Package, ignoring payload (Point 6)
- User and ClientProfile created with submitted applicant details (Point 7)
- Application.user is associated with created or resolved User (Point 8)
- Initial statuses: Application is SUBMITTED and Order is PENDING_PAYMENT (Point 9)
- Preexisting global User is reused without duplication (Point 10)
- Preexisting Membership is reused and not demoted or modified (Point 11)
- Inactive package is rejected with 400 VALIDATION_ERROR and creates no records (Point 12)
- Cross-workspace package is rejected with 400 VALIDATION_ERROR (Point 13)
- Random nonexistent package rejected with matching error and no tenant leakage (Point 14)
- Unknown slug and SUSPENDED workspace return byte-identical 404 NOT_FOUND (Point 15)
- order_number starts at '000001' zero-padded to 6 digits (Point 16)
- order_number increments sequentially within workspace: '000001', '000002', ... (Point 17)
- order_number is per-workspace, not global; workspace A and B both get '000001' (Point 18)
- UNIQUE(workspace, order_number) constraint prevents duplicates in same workspace (Point 19)
- ATOMICITY: late failure at Order creation rolls back entire transaction (Point 20)
- Application count always equals Order count; no orphaned records (Point 21)
- Repeated submissions are NOT idempotent; creates distinct records (Point 22)
- Non-POST HTTP methods (GET, PATCH, PUT, DELETE) return 405 Method Not Allowed (Point 23)
- Architecture guard: applications exposes {Application}, commerce exposes {Order} (Point 24)
"""

import uuid
from decimal import Decimal
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

PUBLIC_APPLICATIONS_URL_TEMPLATE = "/api/v1/public/coaches/{slug}/applications"
EXPECTED_RESPONSE_KEYS = {"application_id", "order_id", "order_number", "status"}


def public_applications_url(slug: str) -> str:
    """Returns the public application submission URL for a given workspace slug."""
    return f"/api/v1/public/coaches/{slug}/applications"


class BaseClientOnboardingTestCase(TestCase):
    """Base test case providing model resolution, cache resets, and factory helpers."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.client = APIClient()
        self.application_model = apps.get_model("applications", "Application")
        self.order_model = apps.get_model("commerce", "Order")
        self.workspace_model = apps.get_model("workspaces", "Workspace")
        self.package_model = apps.get_model("coaching", "Package")
        self.membership_model = apps.get_model("accounts", "Membership")
        self.client_profile_model = apps.get_model("accounts", "ClientProfile")
        self.user_model = get_user_model()

    def _create_user(self, email=None, password="SecurePassword123!", **kwargs):
        """Creates and returns an email-verified user instance."""
        if email is None:
            email = f"user-{uuid.uuid4().hex[:8]}@example.com"
        return self.user_model.objects.create_user(email=email, password=password, **kwargs)

    def _create_workspace(self, name=None, slug=None, **kwargs):
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
            "status": "ACTIVE",
        }
        defaults.update(kwargs)
        return self.workspace_model.objects.create(**defaults)

    def _create_membership(
        self,
        user=None,
        workspace=None,
        role="CLIENT",
        status="ACTIVE",
        **kwargs,
    ):
        """Creates and returns a Membership instance."""
        if workspace is None:
            workspace = self._create_workspace()
        if user is None:
            user = self._create_user()
        defaults = {
            "user": user,
            "workspace": workspace,
            "role": role,
            "status": status,
        }
        defaults.update(kwargs)
        return self.membership_model.objects.create(**defaults)

    def _create_package(self, workspace=None, is_active=True, **kwargs):
        """Creates and returns a coaching Package instance."""
        if workspace is None:
            workspace = self._create_workspace()
        unique_id = uuid.uuid4().hex[:8]
        defaults = {
            "workspace": workspace,
            "name": f"Pro Package {unique_id}",
            "description": "Comprehensive 12-week fitness coaching program.",
            "price": Decimal("2500.00"),
            "currency": "USD",
            "duration_days": 90,
            "features": ["Personalized Workout", "Nutrition Guide"],
            "is_active": is_active,
        }
        defaults.update(kwargs)
        return self.package_model.objects.create(**defaults)

    def _build_valid_payload(self, package, **overrides):
        """Builds a complete, valid dictionary payload with all eleven submission fields."""
        unique_id = uuid.uuid4().hex[:8]
        payload = {
            "package_id": str(package.id),
            "full_name": f"Jane Applicant {unique_id}",
            "email": f"applicant-{unique_id}@example.com",
            "phone": "+1234567890",
            "age": 28,
            "gender": "female",
            "height": 172.50,
            "weight": 65.25,
            "goal": "Build functional strength and athletic performance",
            "training_experience": "3 years intermediate training",
            "notes": "Prefers morning workout sessions and high protein guidance.",
        }
        payload.update(overrides)
        return payload

    def assert_error_envelope(
        self, response, expected_status, expected_code=None, expected_field=None
    ):
        """Asserts the API §2 error envelope; fields is only present for VALIDATION_ERROR."""
        self.assertEqual(response.status_code, expected_status)
        data = response.json()
        self.assertEqual(
            set(data.keys()),
            {"error"},
            f"Response top-level keys must equal {{'error'}}, got {set(data.keys())}.",
        )
        error = data["error"]
        self.assertIsInstance(error, dict)
        if expected_code is not None:
            self.assertEqual(
                error.get("code"),
                expected_code,
                f"Error code must be '{expected_code}', got '{error.get('code')}'.",
            )
        self.assertIsInstance(error.get("message"), str)
        if expected_code == "VALIDATION_ERROR" or expected_field is not None:
            self.assertIn(
                "fields",
                error,
                "VALIDATION_ERROR response must carry a 'fields' dictionary.",
            )
            self.assertIsInstance(error["fields"], dict)
            if expected_field is not None:
                self.assertIn(
                    expected_field,
                    error["fields"],
                    f"Expected field '{expected_field}' in error['fields'].",
                )
                self.assertIsInstance(
                    error["fields"][expected_field],
                    list,
                    f"Field errors for '{expected_field}' must be a list.",
                )
        else:
            self.assertNotIn(
                "fields",
                error,
                "Non-validation errors (NOT_FOUND, etc.) must not carry 'fields'.",
            )


class ClientOnboardingHappyPathTests(BaseClientOnboardingTestCase):
    """Verifies happy path 201 Created and response structure for anonymous callers (Point 1)."""

    def test_anonymous_submission_with_full_valid_payload_returns_201_created(self):
        """Asserts unauthenticated POST with full 11-field valid payload returns 201 Created."""
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)
        payload = self._build_valid_payload(package)

        url = public_applications_url(workspace.slug)
        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(
            set(data.keys()),
            EXPECTED_RESPONSE_KEYS,
            f"Response must contain exactly {EXPECTED_RESPONSE_KEYS}, got {set(data.keys())}.",
        )
        self.assertEqual(data["order_number"], "000001")
        self.assertEqual(data["status"], "SUBMITTED")

    def test_anonymous_submission_with_minimal_required_fields_returns_201_created(self):
        """Asserts submission with only package_id, full_name, email returns 201 Created."""
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)
        unique_id = uuid.uuid4().hex[:8]
        payload = {
            "package_id": str(package.id),
            "full_name": f"Minimal Applicant {unique_id}",
            "email": f"minimal-{unique_id}@example.com",
        }

        url = public_applications_url(workspace.slug)
        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(set(data.keys()), EXPECTED_RESPONSE_KEYS)

        application = self.application_model.objects.get(id=data["application_id"])
        self.assertEqual(application.full_name, payload["full_name"])
        self.assertEqual(application.email, payload["email"])
        self.assertEqual(application.phone, "")
        self.assertIsNone(application.age)

    def test_response_contains_exact_four_keys_without_personal_data_leakage(self):
        """Guards privacy boundary: personal data submitted by prospect is not echoed back."""
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)
        unique_id = uuid.uuid4().hex[:8]
        sensitive_name = f"SecretApplicantName-{unique_id}"
        sensitive_email = f"secret-{unique_id}@privacy-shield.org"
        sensitive_phone = "+999888777666"
        sensitive_notes = f"ConfidentialMedicalHistory-{unique_id}"

        payload = self._build_valid_payload(
            package,
            full_name=sensitive_name,
            email=sensitive_email,
            phone=sensitive_phone,
            notes=sensitive_notes,
        )

        url = public_applications_url(workspace.slug)
        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        raw_text = response.content.decode()

        self.assertNotIn(sensitive_name, raw_text, "Prospect name leaked in response text.")
        self.assertNotIn(sensitive_email, raw_text, "Prospect email leaked in response text.")
        self.assertNotIn(sensitive_phone, raw_text, "Prospect phone leaked in response text.")
        self.assertNotIn(sensitive_notes, raw_text, "Prospect notes leaked in response text.")


class ClientOnboardingCreationCountTests(BaseClientOnboardingTestCase):
    """Verifies that Application, Membership, and Order are all created (Point 2)."""

    def test_submission_creates_application_membership_and_order_records(self):
        """Asserts each record count increases by exactly 1 on successful submission."""
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)
        payload = self._build_valid_payload(package)

        app_count_before = self.application_model.objects.count()
        order_count_before = self.order_model.objects.count()
        membership_count_before = self.membership_model.objects.count()

        url = public_applications_url(workspace.slug)
        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            self.application_model.objects.count(),
            app_count_before + 1,
            "Application count must increase by exactly 1.",
        )
        self.assertEqual(
            self.order_model.objects.count(),
            order_count_before + 1,
            "Order count must increase by exactly 1.",
        )
        self.assertEqual(
            self.membership_model.objects.count(),
            membership_count_before + 1,
            "Membership count must increase by exactly 1.",
        )
        self.assertTrue(
            self.membership_model.objects.filter(
                workspace=workspace, user__email=payload["email"]
            ).exists(),
            "A Membership must exist for the submitted user and workspace.",
        )


class ClientOnboardingWorkspaceScopingTests(BaseClientOnboardingTestCase):
    """Verifies that all created records belong strictly to the target workspace (Point 3)."""

    def test_all_created_records_belong_to_slug_workspace_and_foreign_workspace_is_untouched(
        self,
    ):
        """Asserts Application, Order, and Membership are scoped to target workspace."""
        target_ws = self._create_workspace()
        foreign_ws = self._create_workspace()
        package = self._create_package(workspace=target_ws)
        payload = self._build_valid_payload(package)

        url = public_applications_url(target_ws.slug)
        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()

        application = self.application_model.objects.get(id=data["application_id"])
        order = self.order_model.objects.get(id=data["order_id"])
        membership = self.membership_model.objects.get(
            workspace=target_ws, user__email=payload["email"]
        )

        self.assertEqual(application.workspace_id, target_ws.id)
        self.assertEqual(order.workspace_id, target_ws.id)
        self.assertEqual(membership.workspace_id, target_ws.id)

        # Ensure nothing was created in the foreign workspace
        self.assertEqual(
            self.application_model.objects.filter(workspace=foreign_ws).count(),
            0,
            "Foreign workspace must contain 0 applications.",
        )
        self.assertEqual(
            self.order_model.objects.filter(workspace=foreign_ws).count(),
            0,
            "Foreign workspace must contain 0 orders.",
        )
        self.assertEqual(
            self.membership_model.objects.filter(workspace=foreign_ws).count(),
            0,
            "Foreign workspace must contain 0 memberships.",
        )


class ClientOnboardingMembershipRoleTests(BaseClientOnboardingTestCase):
    """Verifies membership role and status created by onboarding flow (Point 4)."""

    def test_created_membership_has_role_client_and_status_active(self):
        """Asserts created Membership has role='CLIENT' and status='ACTIVE'."""
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)
        payload = self._build_valid_payload(package)

        url = public_applications_url(workspace.slug)
        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        membership = self.membership_model.objects.get(
            workspace=workspace, user__email=payload["email"]
        )
        self.assertEqual(
            membership.role,
            "CLIENT",
            "Onboarding flow must assign CLIENT role to created Membership.",
        )
        self.assertEqual(
            membership.status,
            "ACTIVE",
            "Onboarding flow must set ACTIVE status on created Membership.",
        )


class ClientOnboardingOrderRelationsTests(BaseClientOnboardingTestCase):
    """Verifies Order relations: package FK and client Membership FK (Point 5)."""

    def test_order_package_and_client_foreign_keys_point_to_submitted_package_and_membership(
        self,
    ):
        """Asserts Order.package is submitted Package and Order.client is the Membership."""
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)
        payload = self._build_valid_payload(package)

        url = public_applications_url(workspace.slug)
        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()

        order = self.order_model.objects.get(id=data["order_id"])
        membership = self.membership_model.objects.get(
            workspace=workspace, user__email=payload["email"]
        )

        self.assertEqual(order.package_id, package.id)
        self.assertEqual(order.package, package)
        self.assertEqual(order.client_id, membership.id)
        self.assertEqual(order.client, membership)

    def test_order_client_field_related_model_is_membership_not_user_or_client_profile(self):
        """Guards relation contract (DB §10): Order.client points to Membership model.

        Orders belong to a tenant's workspace. To preserve workspace scoping and member history,
        Order.client must point strictly to accounts.Membership, never User or ClientProfile.
        """
        client_field = self.order_model._meta.get_field("client")
        self.assertEqual(
            client_field.related_model,
            self.membership_model,
            "Order.client must be a ForeignKey to accounts.Membership.",
        )
        self.assertNotEqual(
            client_field.related_model,
            self.user_model,
            "Order.client must NOT reference the User model directly.",
        )
        self.assertNotEqual(
            client_field.related_model,
            self.client_profile_model,
            "Order.client must NOT reference the ClientProfile model.",
        )


class ClientOnboardingOrderPricingTests(BaseClientOnboardingTestCase):
    """Verifies authoritative price and currency inheritance from Package (Point 6)."""

    def test_order_amount_and_currency_authoritatively_taken_from_package_ignoring_payload(
        self,
    ):
        """Guards pricing authority: Order amount/currency must come from Package, not payload.

        The frontend/caller can never be permitted to specify or override the authoritative
        order price or currency. Submitting forged amount and currency values must be ignored;
        the server-side transaction must strictly copy price and currency from the Package.
        """
        workspace = self._create_workspace()
        package = self._create_package(
            workspace=workspace,
            price=Decimal("4321.99"),
            currency="EGP",
        )
        payload = self._build_valid_payload(
            package,
            amount="1.00",
            currency="USD",
        )

        url = public_applications_url(workspace.slug)
        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()

        order = self.order_model.objects.get(id=data["order_id"])
        self.assertEqual(
            order.amount,
            Decimal("4321.99"),
            "Order amount must match package price Decimal('4321.99'), ignoring payload.",
        )
        self.assertEqual(
            order.currency,
            "EGP",
            "Order currency must match package currency 'EGP', ignoring payload.",
        )
        self.assertNotEqual(order.amount, Decimal("1.00"))
        self.assertNotEqual(order.currency, "USD")


class ClientOnboardingUserAndProfileTests(BaseClientOnboardingTestCase):
    """Verifies User and ClientProfile creation from submission data (Point 7)."""

    def test_user_and_client_profile_created_with_submitted_information(self):
        """Asserts User.email matches submission and ClientProfile is created."""
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)
        unique_id = uuid.uuid4().hex[:8]
        submitted_email = f"client-{unique_id}@example.com"
        submitted_name = f"Taylor Swift {unique_id}"

        payload = self._build_valid_payload(
            package,
            email=submitted_email,
            full_name=submitted_name,
        )

        url = public_applications_url(workspace.slug)
        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()

        application = self.application_model.objects.get(id=data["application_id"])
        self.assertEqual(application.full_name, submitted_name)
        self.assertEqual(application.email, submitted_email)

        user = self.user_model.objects.get(email=submitted_email)
        self.assertEqual(user.email, submitted_email)

        self.assertTrue(
            self.client_profile_model.objects.filter(user=user).exists(),
            "ClientProfile must be created for the new user.",
        )


class ClientOnboardingUserAssociationTests(BaseClientOnboardingTestCase):
    """Verifies Application.user association after successful onboarding (Point 8)."""

    def test_application_user_is_associated_with_created_or_resolved_user(self):
        """Asserts Application.user is not null and points to the created/resolved User."""
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)
        payload = self._build_valid_payload(package)

        url = public_applications_url(workspace.slug)
        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()

        application = self.application_model.objects.get(id=data["application_id"])
        user = self.user_model.objects.get(email=payload["email"])

        self.assertIsNotNone(application.user, "Application.user must not be null.")
        self.assertEqual(application.user_id, user.id)
        self.assertEqual(application.user, user)


class ClientOnboardingLifecycleStatusTests(BaseClientOnboardingTestCase):
    """Verifies initial lifecycle statuses of Application and Order (Point 9)."""

    def test_application_status_is_submitted_and_order_status_is_pending_payment(self):
        """Asserts Application.status=='SUBMITTED' and Order.status=='PENDING_PAYMENT'."""
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)
        payload = self._build_valid_payload(package)

        url = public_applications_url(workspace.slug)
        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()

        application = self.application_model.objects.get(id=data["application_id"])
        order = self.order_model.objects.get(id=data["order_id"])

        self.assertEqual(
            application.status,
            "SUBMITTED",
            "Initial Application status must be SUBMITTED.",
        )
        self.assertEqual(
            order.status,
            "PENDING_PAYMENT",
            "Initial Order status must be PENDING_PAYMENT.",
        )


class ClientOnboardingUserReuseTests(BaseClientOnboardingTestCase):
    """Verifies that an existing global User is reused without duplication (Point 10)."""

    def test_existing_global_user_is_reused_without_creating_duplicate(self):
        """Guards global user deduplication: preexisting User is linked to Application.

        A user may already exist globally (e.g. from an account in another workspace).
        When submitting an application with an existing email, the system must reuse that User
        entity instead of attempting to create a duplicate user or raising IntegrityError.
        """
        existing_email = f"global-user-{uuid.uuid4().hex[:8]}@example.com"
        existing_user = self._create_user(email=existing_email)

        user_count_before = self.user_model.objects.count()

        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)
        payload = self._build_valid_payload(package, email=existing_email)

        url = public_applications_url(workspace.slug)
        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()

        self.assertEqual(
            self.user_model.objects.count(),
            user_count_before,
            "Total User count must not increase when an existing user submits an application.",
        )

        application = self.application_model.objects.get(id=data["application_id"])
        self.assertEqual(
            application.user_id,
            existing_user.id,
            "Application.user must link directly to the preexisting User.",
        )


class ClientOnboardingMembershipReuseTests(BaseClientOnboardingTestCase):
    """Verifies that an existing Membership is reused and not modified (Point 11)."""

    def test_existing_membership_is_reused_and_not_demoted_or_modified(self):
        """Guards membership integrity: existing membership role is not demoted to CLIENT.

        If a user already holds a Membership in this workspace (e.g. with role 'COACH' or
        'OWNER'), submitting an application must not silently demote their role to 'CLIENT'
        and must not attempt to insert a duplicate (user, workspace) Membership row.
        """
        workspace = self._create_workspace()
        coach_user = self._create_user(email=f"coach-{uuid.uuid4().hex[:8]}@example.com")
        existing_membership = self._create_membership(
            user=coach_user,
            workspace=workspace,
            role="COACH",
            status="ACTIVE",
        )

        membership_count_before = self.membership_model.objects.filter(workspace=workspace).count()

        package = self._create_package(workspace=workspace)
        payload = self._build_valid_payload(package, email=coach_user.email)

        url = public_applications_url(workspace.slug)
        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        existing_membership.refresh_from_db()
        self.assertEqual(
            existing_membership.role,
            "COACH",
            "Existing Membership role must remain COACH; must not be demoted to CLIENT.",
        )
        self.assertEqual(
            existing_membership.status,
            "ACTIVE",
            "Existing Membership status must remain ACTIVE.",
        )
        self.assertEqual(
            self.membership_model.objects.filter(workspace=workspace, user=coach_user).count(),
            1,
            "Must not create a duplicate Membership for the same user and workspace.",
        )
        self.assertEqual(
            self.membership_model.objects.filter(workspace=workspace).count(),
            membership_count_before,
            "Total Membership count in workspace must not increase.",
        )


class ClientOnboardingInactivePackageTests(BaseClientOnboardingTestCase):
    """Verifies that submitting an inactive package returns 400 with no side effects (Point 12)."""

    def test_inactive_package_returns_400_and_creates_no_records(self):
        """Asserts inactive package yields 400 VALIDATION_ERROR and writes zero database rows."""
        workspace = self._create_workspace()
        inactive_package = self._create_package(workspace=workspace, is_active=False)
        payload = self._build_valid_payload(inactive_package)

        url = public_applications_url(workspace.slug)
        response = self.client.post(url, payload, format="json")

        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_400_BAD_REQUEST,
            expected_code="VALIDATION_ERROR",
            expected_field="package_id",
        )

        self.assertEqual(
            self.application_model.objects.count(),
            0,
            "No Application may be created on inactive package submission.",
        )
        self.assertEqual(
            self.order_model.objects.count(),
            0,
            "No Order may be created on inactive package submission.",
        )
        self.assertEqual(
            self.membership_model.objects.filter(workspace=workspace).count(),
            0,
            "No Membership may be created on inactive package submission.",
        )
        self.assertEqual(
            self.user_model.objects.filter(email=payload["email"]).count(),
            0,
            "No User may be created on inactive package submission.",
        )


class ClientOnboardingCrossWorkspacePackageTests(BaseClientOnboardingTestCase):
    """Verifies that submitting a foreign workspace package returns 400 (Point 13)."""

    def test_cross_workspace_package_returns_400_and_creates_no_records(self):
        """Asserts foreign package yields 400 VALIDATION_ERROR and writes zero database rows."""
        target_ws = self._create_workspace()
        foreign_ws = self._create_workspace()
        foreign_package = self._create_package(workspace=foreign_ws, is_active=True)
        payload = self._build_valid_payload(foreign_package)

        url = public_applications_url(target_ws.slug)
        response = self.client.post(url, payload, format="json")

        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_400_BAD_REQUEST,
            expected_code="VALIDATION_ERROR",
            expected_field="package_id",
        )

        self.assertEqual(
            self.application_model.objects.count(),
            0,
            "No Application may be created on cross-workspace package submission.",
        )
        self.assertEqual(
            self.order_model.objects.count(),
            0,
            "No Order may be created on cross-workspace package submission.",
        )
        self.assertEqual(
            self.membership_model.objects.filter(workspace=target_ws).count(),
            0,
            "No Membership may be created on cross-workspace package submission.",
        )
        self.assertEqual(
            self.user_model.objects.filter(email=payload["email"]).count(),
            0,
            "No User may be created on cross-workspace package submission.",
        )


class ClientOnboardingAntiEnumerationTests(BaseClientOnboardingTestCase):
    """Verifies anti-enumeration and tenant leakage protection on package errors (Point 14)."""

    def test_foreign_and_random_nonexistent_package_errors_match_without_tenant_leakage(
        self,
    ):
        """Guards anti-enumeration (DB §26, API §25): foreign & nonexistent errors match.

        A prospect must never be able to determine whether a package UUID belongs to a
        different workspace versus being entirely nonexistent. The error code and message
        template (with submitted UUID normalised) must be identical, and foreign workspace
        identifiers must never leak in the response body.
        """
        workspace_a = self._create_workspace()
        workspace_b = self._create_workspace()
        foreign_package = self._create_package(workspace=workspace_b, is_active=True)
        random_uuid = uuid.uuid4()

        foreign_payload = self._build_valid_payload(foreign_package)
        random_payload = self._build_valid_payload(foreign_package, package_id=str(random_uuid))

        url = public_applications_url(workspace_a.slug)
        foreign_res = self.client.post(url, foreign_payload, format="json")
        random_res = self.client.post(url, random_payload, format="json")

        self.assertEqual(foreign_res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(random_res.status_code, status.HTTP_400_BAD_REQUEST)

        foreign_data = foreign_res.json()
        random_data = random_res.json()

        self.assertEqual(foreign_data["error"]["code"], "VALIDATION_ERROR")
        self.assertEqual(random_data["error"]["code"], "VALIDATION_ERROR")
        self.assertIn("package_id", foreign_data["error"]["fields"])
        self.assertIn("package_id", random_data["error"]["fields"])

        foreign_msg = str(foreign_data["error"]["fields"]["package_id"])
        random_msg = str(random_data["error"]["fields"]["package_id"])

        foreign_template = foreign_msg.replace(str(foreign_package.id), "<pk>")
        random_template = random_msg.replace(str(random_uuid), "<pk>")

        self.assertEqual(
            foreign_template,
            random_template,
            "Normalized error message for foreign package must equal nonexistent package error.",
        )

        self.assertNotIn(
            str(workspace_b.id),
            foreign_res.content.decode(),
            "Foreign workspace UUID must not leak in error response.",
        )
        self.assertNotIn(
            workspace_b.slug,
            foreign_res.content.decode(),
            "Foreign workspace slug must not leak in error response.",
        )


class ClientOnboardingNotFoundAndSuspendedTests(BaseClientOnboardingTestCase):
    """Verifies 404 NOT_FOUND and anti-enumeration on unknown/suspended workspaces (Point 15)."""

    def test_unknown_slug_and_suspended_workspace_both_return_byte_identical_404(self):
        """Guards anti-enumeration: SUSPENDED workspace returns byte-identical 404 to unknown.

        A suspended workspace must be invisible to public prospective clients. Returning 403
        or a differentiated error message would leak that a workspace exists. Both suspended
        and nonexistent slugs must return byte-identical 404 NOT_FOUND responses.
        """
        suspended_ws = self._create_workspace(status="SUSPENDED")
        pkg = self._create_package(workspace=suspended_ws)
        payload = self._build_valid_payload(pkg)

        nonexistent_slug = f"nonexistent-slug-{uuid.uuid4().hex[:10]}"

        suspended_url = public_applications_url(suspended_ws.slug)
        nonexistent_url = public_applications_url(nonexistent_slug)

        suspended_res = self.client.post(suspended_url, payload, format="json")
        nonexistent_res = self.client.post(nonexistent_url, payload, format="json")

        self.assertEqual(suspended_res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(nonexistent_res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertNotEqual(
            suspended_res.status_code,
            status.HTTP_403_FORBIDDEN,
            "SUSPENDED workspace must never return 403 Forbidden.",
        )
        self.assertEqual(
            suspended_res.content,
            nonexistent_res.content,
            "SUSPENDED workspace response must be byte-identical to nonexistent slug response.",
        )
        self.assert_error_envelope(
            suspended_res,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )


class ClientOnboardingOrderNumberFormatTests(BaseClientOnboardingTestCase):
    """Verifies that the first order_number is zero-padded 6 digits '000001' (Point 16)."""

    def test_first_order_number_is_zero_padded_six_digits_000001(self):
        """Asserts the initial order_number in a workspace starts at '000001'."""
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)
        payload = self._build_valid_payload(package)

        url = public_applications_url(workspace.slug)
        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()

        self.assertEqual(
            data["order_number"],
            "000001",
            "First order_number in response must be '000001'.",
        )

        order = self.order_model.objects.get(id=data["order_id"])
        self.assertEqual(
            order.order_number,
            "000001",
            "First order_number stored in database must be '000001'.",
        )


class ClientOnboardingOrderNumberSequentialTests(BaseClientOnboardingTestCase):
    """Verifies that order numbers increment sequentially within a workspace (Point 17)."""

    def test_order_numbers_are_sequential_across_multiple_submissions_in_same_workspace(
        self,
    ):
        """Asserts three submissions in same workspace yield '000001', '000002', '000003'."""
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)
        url = public_applications_url(workspace.slug)

        expected_numbers = ["000001", "000002", "000003"]
        actual_numbers = []

        for _ in range(3):
            payload = self._build_valid_payload(package)
            response = self.client.post(url, payload, format="json")
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            actual_numbers.append(response.json()["order_number"])

        self.assertEqual(
            actual_numbers,
            expected_numbers,
            "Order numbers in the same workspace must increment sequentially from '000001'.",
        )


class ClientOnboardingOrderNumberPerWorkspaceTests(BaseClientOnboardingTestCase):
    """Verifies that order numbers are scoped per-workspace and not global (Point 18)."""

    def test_order_numbers_are_scoped_per_workspace_and_both_start_at_000001(self):
        """Guards Decision 52: order_number is per-workspace sequential, never a global counter.

        Submitting an application in Workspace A yields '000001'. A subsequent submission in
        Workspace B must ALSO yield '000001'. A test or implementation expecting '000002' in
        Workspace B would violate multi-tenant isolation and Decision 52.
        """
        workspace_a = self._create_workspace()
        workspace_b = self._create_workspace()
        package_a = self._create_package(workspace=workspace_a)
        package_b = self._create_package(workspace=workspace_b)

        res_a = self.client.post(
            public_applications_url(workspace_a.slug),
            self._build_valid_payload(package_a),
            format="json",
        )
        self.assertEqual(res_a.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            res_a.json()["order_number"],
            "000001",
            "Workspace A first order must be '000001'.",
        )

        res_b = self.client.post(
            public_applications_url(workspace_b.slug),
            self._build_valid_payload(package_b),
            format="json",
        )
        self.assertEqual(res_b.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            res_b.json()["order_number"],
            "000001",
            "Workspace B first order must ALSO be '000001' (per-workspace counter).",
        )


class ClientOnboardingOrderNumberUniquenessTests(BaseClientOnboardingTestCase):
    """Verifies the UNIQUE(workspace, order_number) database constraint (Point 19)."""

    def test_order_number_conflict_is_retried_and_submission_still_succeeds(self):
        """Guards decision 52's concurrency requirement: allocation retries on conflict.

        Two simultaneous submissions in one workspace can compute the same order_number; the
        loser hits UNIQUE(workspace, order_number). The contract requires the allocation to
        recompute and retry rather than fail the request. A real thread race cannot be staged
        in a single-connection TestCase, so the conflict is injected by making the FIRST
        Order insert raise IntegrityError and letting the retry run the real create.

        This also proves the retry is savepoint-wrapped: without a savepoint the IntegrityError
        would leave the outer atomic block broken and the retry's next query would raise
        TransactionManagementError instead of succeeding.
        """
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)
        url = public_applications_url(workspace.slug)

        real_create = self.order_model.objects.create
        calls = {"n": 0}

        def flaky_create(*args, **kwargs):
            """Raise a unique-violation on the first attempt, then behave normally."""
            calls["n"] += 1
            if calls["n"] == 1:
                raise IntegrityError("duplicate key value violates unique constraint")
            return real_create(*args, **kwargs)

        with patch.object(self.order_model.objects, "create", side_effect=flaky_create):
            response = self.client.post(url, self._build_valid_payload(package), format="json")

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
            "A retried order-number conflict must still produce a successful submission.",
        )
        self.assertGreaterEqual(calls["n"], 2, "The allocation must have retried after conflict.")
        self.assertEqual(self.order_model.objects.filter(workspace=workspace).count(), 1)
        self.assertEqual(self.application_model.objects.filter(workspace=workspace).count(), 1)

    def test_duplicate_order_number_in_same_workspace_violates_integrity_constraint(self):
        """Asserts inserting duplicate order_number in same workspace raises IntegrityError."""
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)
        user = self._create_user()
        membership = self._create_membership(user=user, workspace=workspace, role="CLIENT")

        self.order_model.objects.create(
            workspace=workspace,
            client=membership,
            package=package,
            order_number="000001",
            amount=Decimal("100.00"),
            currency="USD",
        )

        # Attempt duplicate insert in same workspace inside atomic block
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.order_model.objects.create(
                    workspace=workspace,
                    client=membership,
                    package=package,
                    order_number="000001",
                    amount=Decimal("200.00"),
                    currency="USD",
                )

        # Same order_number in a DIFFERENT workspace must succeed
        workspace_b = self._create_workspace()
        package_b = self._create_package(workspace=workspace_b)
        user_b = self._create_user()
        membership_b = self._create_membership(user=user_b, workspace=workspace_b, role="CLIENT")

        order_b = self.order_model.objects.create(
            workspace=workspace_b,
            client=membership_b,
            package=package_b,
            order_number="000001",
            amount=Decimal("100.00"),
            currency="USD",
        )
        self.assertEqual(order_b.order_number, "000001")


class ClientOnboardingAtomicityTests(BaseClientOnboardingTestCase):
    """Verifies that late failures roll back the entire transaction atomically (Point 20)."""

    def test_late_failure_at_order_creation_rolls_back_entire_transaction(self):
        """Guards transaction atomicity (API §7): late failure during Order rolls back all.

        A validation failure proves nothing because no database writes were attempted. This
        test forces a failure at the final Order creation step (after Application, User, and
        Membership creation in the transaction) to prove that the entire transaction rolls
        back cleanly with zero orphaned Application, Order, Membership, or User records.
        """
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)
        payload = self._build_valid_payload(package)
        url = public_applications_url(workspace.slug)

        user_count_before = self.user_model.objects.count()
        client_profile_count_before = self.client_profile_model.objects.count()

        # Patch Order manager's create method to simulate a late database failure
        # Patch the manager INSTANCE, not type(...). Order and Application share one
        # manager class (WorkspaceScopedModel calls TenantQuerySet.as_manager() once in the
        # abstract base), so patching the class would also stub Application.objects.create —
        # the Application would never be created and "it rolled back" would be vacuously
        # true. Patching the instance affects Order alone, so the Application really is
        # written first and the rollback assertion below is meaningful.
        with patch.object(
            self.order_model.objects,
            "create",
            side_effect=RuntimeError("Simulated database failure during Order creation"),
        ):
            try:
                response = self.client.post(url, payload, format="json")
                self.assertEqual(
                    response.status_code,
                    status.HTTP_500_INTERNAL_SERVER_ERROR,
                    "Late failure should surface as 500 when handled by DRF exception handler.",
                )
            except RuntimeError:
                # If the exception is unhandled and propagates out of client, that is also
                # acceptable; the critical invariant being tested is the database state.
                pass

        # Assert zero records exist in target workspace
        self.assertEqual(
            self.application_model.objects.filter(workspace=workspace).count(),
            0,
            "Application record must be rolled back on late failure.",
        )
        self.assertEqual(
            self.order_model.objects.filter(workspace=workspace).count(),
            0,
            "Order record must not exist on late failure.",
        )
        self.assertEqual(
            self.membership_model.objects.filter(workspace=workspace).count(),
            0,
            "Membership record must be rolled back on late failure.",
        )
        self.assertEqual(
            self.user_model.objects.filter(email=payload["email"]).count(),
            0,
            "User entity must be rolled back on late failure.",
        )
        self.assertEqual(
            self.user_model.objects.count(),
            user_count_before,
            "Global User count must not increase on late failure.",
        )
        self.assertEqual(
            self.client_profile_model.objects.count(),
            client_profile_count_before,
            "ClientProfile count must not increase on late failure.",
        )


class ClientOnboardingApplicationOrderCoexistenceTests(BaseClientOnboardingTestCase):
    """Verifies that an Application never exists without its corresponding Order (Point 21)."""

    def test_application_count_always_equals_order_count_in_workspace(self):
        """Asserts Application count equals Order count after submissions and late failures.

        Per API §7: 'a failure at any step must not leave an Application without its Order
        or an Order without its Application.' This invariant must hold across all execution
        paths (success, late failure, and sequential additions).
        """
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)
        url = public_applications_url(workspace.slug)

        self.assertEqual(self.application_model.objects.filter(workspace=workspace).count(), 0)
        self.assertEqual(self.order_model.objects.filter(workspace=workspace).count(), 0)

        # Successful submission 1
        res1 = self.client.post(url, self._build_valid_payload(package), format="json")
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            self.application_model.objects.filter(workspace=workspace).count(),
            1,
        )
        self.assertEqual(
            self.order_model.objects.filter(workspace=workspace).count(),
            1,
        )

        # Successful submission 2
        res2 = self.client.post(url, self._build_valid_payload(package), format="json")
        self.assertEqual(res2.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            self.application_model.objects.filter(workspace=workspace).count(),
            2,
        )
        self.assertEqual(
            self.order_model.objects.filter(workspace=workspace).count(),
            2,
        )

        # Late failure attempt must not leave an orphaned Application
        # Patch the manager INSTANCE, not type(...). Order and Application share one
        # manager class (WorkspaceScopedModel calls TenantQuerySet.as_manager() once in the
        # abstract base), so patching the class would also stub Application.objects.create —
        # the Application would never be created and "it rolled back" would be vacuously
        # true. Patching the instance affects Order alone, so the Application really is
        # written first and the rollback assertion below is meaningful.
        with patch.object(
            self.order_model.objects,
            "create",
            side_effect=RuntimeError("Order creation failure"),
        ):
            try:
                self.client.post(url, self._build_valid_payload(package), format="json")
            except RuntimeError:
                pass

        # Counts must still match and remain 2
        self.assertEqual(
            self.application_model.objects.filter(workspace=workspace).count(),
            2,
            "Failed submission must not leave an orphaned Application.",
        )
        self.assertEqual(
            self.order_model.objects.filter(workspace=workspace).count(),
            2,
            "Failed submission must not create an Order.",
        )
        self.assertEqual(
            self.application_model.objects.filter(workspace=workspace).count(),
            self.order_model.objects.filter(workspace=workspace).count(),
            "Application count must strictly equal Order count.",
        )


class ClientOnboardingNonIdempotentTests(BaseClientOnboardingTestCase):
    """Verifies that identical repeated submissions create separate records (Point 22)."""

    def test_submitting_identical_payload_twice_creates_two_distinct_applications_and_orders(
        self,
    ):
        """Guards against invented idempotency: repeated submissions create separate rows.

        No requirement specifies deduplication or idempotency on public application intake.
        Submitting the identical payload twice must create two distinct Applications and two
        distinct Orders with incremented order_numbers ('000001' and '000002').
        """
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)
        payload = self._build_valid_payload(package)
        url = public_applications_url(workspace.slug)

        res1 = self.client.post(url, payload, format="json")
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)
        data1 = res1.json()

        res2 = self.client.post(url, payload, format="json")
        self.assertEqual(res2.status_code, status.HTTP_201_CREATED)
        data2 = res2.json()

        self.assertNotEqual(
            data1["application_id"],
            data2["application_id"],
            "Repeated submission must create a new distinct Application ID.",
        )
        self.assertNotEqual(
            data1["order_id"],
            data2["order_id"],
            "Repeated submission must create a new distinct Order ID.",
        )
        self.assertEqual(data1["order_number"], "000001")
        self.assertEqual(data2["order_number"], "000002")

        self.assertEqual(
            self.application_model.objects.filter(workspace=workspace).count(),
            2,
            "Two distinct Applications must exist in database.",
        )
        self.assertEqual(
            self.order_model.objects.filter(workspace=workspace).count(),
            2,
            "Two distinct Orders must exist in database.",
        )


class ClientOnboardingMethodHandlingTests(BaseClientOnboardingTestCase):
    """Verifies that non-POST HTTP methods return 405 Method Not Allowed (Point 23)."""

    def test_non_post_methods_return_405_method_not_allowed(self):
        """Asserts GET, PATCH, PUT, and DELETE on application URL return 405."""
        workspace = self._create_workspace()
        url = public_applications_url(workspace.slug)

        for method in ("get", "patch", "put", "delete"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(url)
                self.assertEqual(
                    response.status_code,
                    status.HTTP_405_METHOD_NOT_ALLOWED,
                    f"HTTP {method.upper()} on public application submission URL must return 405.",
                )


class ClientOnboardingArchitectureGuardTests(TestCase):
    """Verifies architectural boundaries across applications and commerce apps (Point 24)."""

    def test_applications_app_exposes_only_application_model(self):
        """Guards architectural boundary: applications app must define only Application."""
        applications_app = apps.get_app_config("applications")
        concrete_model_names = {model._meta.object_name for model in applications_app.get_models()}
        self.assertSetEqual(
            concrete_model_names,
            {"Application"},
            "applications app must define exactly {'Application'}.",
        )

    def test_commerce_app_exposes_only_order_model(self):
        """Guards architectural boundary: commerce app must define only Order.

        Story 8.1 introduced only the Order model; downstream models like Payment or
        Subscription (Stories 8.3+) must not leak early into the commerce app.
        """
        commerce_app = apps.get_app_config("commerce")
        concrete_model_names = {model._meta.object_name for model in commerce_app.get_models()}
        self.assertSetEqual(
            concrete_model_names,
            {"Order"},
            "commerce app must define exactly {'Order'}; no Payment or Subscription models.",
        )
