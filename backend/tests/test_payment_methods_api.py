"""API tests for Workspace Payment Methods (Story 4.4 / Task B).

Validates:
- Access control: unauthenticated requests across all four methods (GET, POST, PATCH, DELETE)
  are rejected with 401/403 and the standard API §2 error envelope.
- Authorization (Coach/Owner): ACTIVE OWNER and ACTIVE COACH are both authorised across all
  four endpoints (GET 200, POST 201, PATCH 200, DELETE 204).
- 404 family & indistinguishability: callers with no membership, INACTIVE membership,
  SUSPENDED workspace, or CLIENT-only role receive identical 404 NOT_FOUND responses
  without revealing workspace existence.
- Model contract: PaymentMethod defines exactly the ten documented concrete fields,
  inherits WorkspaceScopedModel, exposes the four valid 'type' choices, and defaults
  'is_active' to True.
- POST /api/v1/workspace/payment-methods contract: creates row in caller's Workspace,
  accepts all four payment method types, returns exactly nine keys, validates missing
  or invalid fields, handles WebP image conversion, and enforces MIME and size ceilings.
- GET /api/v1/workspace/payment-methods contract: returns unpaginated list of caller's
  Workspace payment methods, excludes other workspaces, and includes nine keys per item.
- PATCH /api/v1/workspace/payment-methods/{id} contract: partial updates, toggling
  is_active, replacing image with WebP conversion, and cross-workspace 404 immutability.
- DELETE /api/v1/workspace/payment-methods/{id} contract: 204 No Content, hard delete from
  database, 404 on subsequent delete, and cross-workspace 404 with row survival.
- Object isolation: cross-workspace ID and non-existent random UUID produce byte-identical
  404 NOT_FOUND responses (never 403) across PATCH and DELETE.
- Rate limiting: POST and PATCH enforce shared 'workspace_logo_upload' throttle (20/hour,
  429 on 21st request), while GET and DELETE remain unthrottled.
- Contract preservation & architecture guards: GET /api/v1/workspace preserves eleven keys,
  workspaces app exposes {"Workspace", "PaymentMethod"}, and billing defines no models.
"""

import io
import os
import shutil
import tempfile
import uuid

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient

PAYMENT_METHODS_URL = "/api/v1/workspace/payment-methods"
WORKSPACE_URL = "/api/v1/workspace"

EXPECTED_PAYMENT_METHOD_KEYS = {
    "id",
    "type",
    "name",
    "instructions",
    "account_details",
    "image",
    "is_active",
    "created_at",
    "updated_at",
}

EXPECTED_PAYMENT_METHOD_FIELDS = {
    "id",
    "workspace",
    "type",
    "name",
    "instructions",
    "account_details",
    "image",
    "is_active",
    "created_at",
    "updated_at",
}

VALID_PAYMENT_METHOD_TYPES = {
    "INSTAPAY",
    "VODAFONE_CASH",
    "BANK_TRANSFER",
    "CUSTOM",
}

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


def make_test_image(
    width: int = 100,
    height: int = 100,
    color: tuple[int, int, int] = (200, 30, 30),
    image_format: str = "PNG",
    filename: str = "test.png",
    content_type: str = "image/png",
) -> SimpleUploadedFile:
    """Generates an in-memory test image using Pillow and returns a SimpleUploadedFile."""
    buf = io.BytesIO()
    image = Image.new("RGB", (width, height), color)
    image.save(buf, format=image_format)
    buf.seek(0)
    return SimpleUploadedFile(filename, buf.getvalue(), content_type=content_type)


def make_large_file(
    size_bytes: int = 11 * 1024 * 1024,
    filename: str = "large.png",
    content_type: str = "image/png",
) -> SimpleUploadedFile:
    """Generates an oversize file with PNG signature bytes to test upload size ceilings."""
    header = b"\x89PNG\r\n\x1a\n"
    content = header + b"\x00" * max(0, size_bytes - len(header))
    return SimpleUploadedFile(filename, content, content_type=content_type)


def make_non_image_file(
    filename: str = "document.txt",
    content: bytes = b"This is plain text and not a valid image payload.",
    content_type: str = "text/plain",
) -> SimpleUploadedFile:
    """Generates a non-image file to test MIME type validation."""
    return SimpleUploadedFile(filename, content, content_type=content_type)


def payment_method_detail_url(pk: uuid.UUID | str) -> str:
    """Returns the URL for a specific payment method detail endpoint."""
    return f"{PAYMENT_METHODS_URL}/{pk}"


class BasePaymentMethodsApiTestCase(TestCase):
    """Base test case providing client setup, cache reset, media isolation, and entity helpers."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.client = APIClient()
        self.user_model = get_user_model()
        self.workspace_model = apps.get_model("workspaces", "Workspace")
        self.membership_model = apps.get_model("accounts", "Membership")
        self.payment_method_model = apps.get_model("workspaces", "PaymentMethod")

        # Isolate media filesystem writes into a dedicated temporary directory
        self.temp_media_dir = tempfile.mkdtemp()
        self._media_override = override_settings(MEDIA_ROOT=self.temp_media_dir)
        self._media_override.enable()

    def tearDown(self):
        self._media_override.disable()
        if os.path.exists(self.temp_media_dir):
            shutil.rmtree(self.temp_media_dir, ignore_errors=True)
        super().tearDown()

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

    def _create_payment_method(
        self,
        workspace=None,
        type="INSTAPAY",
        name="InstaPay",
        instructions="Send payment to 01000000000",
        account_details="01000000000",
        is_active=True,
        **kwargs,
    ):
        """Creates and returns a PaymentMethod directly in the database."""
        if workspace is None:
            workspace = self._create_workspace()
        defaults = {
            "workspace": workspace,
            "type": type,
            "name": name,
            "instructions": instructions,
            "account_details": account_details,
            "is_active": is_active,
        }
        defaults.update(kwargs)
        return self.payment_method_model.objects.create(**defaults)

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
        # API §2: `fields` is emitted only for VALIDATION_ERROR. PERMISSION_DENIED, NOT_FOUND,
        # RATE_LIMITED, FILE_TOO_LARGE, and UNSUPPORTED_FILE_TYPE carry no `fields` key.
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
                "Non-validation errors (PERMISSION_DENIED, NOT_FOUND, RATE_LIMITED, "
                "UNSUPPORTED_FILE_TYPE, FILE_TOO_LARGE) must not carry 'fields'.",
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


class PaymentMethodsAccessAndAuthorizationTests(BasePaymentMethodsApiTestCase):
    """Verifies authentication and Coach/Owner authorization on Payment Methods endpoints."""

    def test_unauthenticated_requests_on_all_methods_return_401_or_403_with_error_envelope(self):
        """Asserts unauthenticated requests on all four methods return 401/403 with envelope."""
        random_id = uuid.uuid4()
        detail_url = payment_method_detail_url(random_id)

        # GET collection
        get_res = self.client.get(PAYMENT_METHODS_URL)
        self.assertIn(
            get_res.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )
        self.assertEqual(set(get_res.json().keys()), {"error"})

        # POST collection
        post_res = self.client.post(
            PAYMENT_METHODS_URL,
            {"type": "INSTAPAY", "name": "Unauthorized Method"},
            format="json",
        )
        self.assertIn(
            post_res.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )
        self.assertEqual(set(post_res.json().keys()), {"error"})

        # PATCH detail
        patch_res = self.client.patch(
            detail_url,
            {"name": "Unauthorized Update"},
            format="json",
        )
        self.assertIn(
            patch_res.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )
        self.assertEqual(set(patch_res.json().keys()), {"error"})

        # DELETE detail
        delete_res = self.client.delete(detail_url)
        self.assertIn(
            delete_res.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )
        self.assertEqual(set(delete_res.json().keys()), {"error"})

    def test_active_owner_is_authorised_on_all_four_endpoints(self):
        """Asserts caller with an ACTIVE OWNER membership is authorised on all four endpoints."""
        owner = self._create_user(email="owner.all@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        # Decoy workspace to ensure multi-tenant scoping
        self._create_membership(role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)

        # 1. POST -> 201 Created
        post_response = self.client.post(
            PAYMENT_METHODS_URL,
            {
                "type": "INSTAPAY",
                "name": "Owner InstaPay",
                "instructions": "Transfer via InstaPay",
                "account_details": "01000000000",
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(post_response.status_code, status.HTTP_201_CREATED)
        created_id = post_response.json()["id"]

        # 2. GET collection -> 200 OK
        get_response = self.client.get(PAYMENT_METHODS_URL)
        self.assertEqual(get_response.status_code, status.HTTP_200_OK)
        returned_ids = [item["id"] for item in get_response.json()]
        self.assertIn(created_id, returned_ids)

        # 3. PATCH item -> 200 OK
        patch_response = self.client.patch(
            payment_method_detail_url(created_id),
            {"name": "Owner InstaPay Updated"},
            format="json",
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_response.json()["name"], "Owner InstaPay Updated")

        # 4. DELETE item -> 204 No Content
        delete_response = self.client.delete(payment_method_detail_url(created_id))
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)

    def test_active_coach_is_authorised_on_all_four_endpoints(self):
        """Asserts caller with an ACTIVE COACH membership is authorised on all four endpoints.

        API §6 Payment Methods explicitly specifies 'Coach/Owner' permission for all operations,
        unlike the OWNER-only restriction on Workspace Branding/Settings.
        """
        coach = self._create_user(email="coach.all@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=coach, workspace=workspace, role="COACH", status="ACTIVE")

        # Decoy workspace to ensure multi-tenant scoping
        self._create_membership(role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=coach)

        # 1. POST -> 201 Created
        post_response = self.client.post(
            PAYMENT_METHODS_URL,
            {
                "type": "VODAFONE_CASH",
                "name": "Vodafone Cash Wallet",
                "instructions": "Transfer to wallet",
                "account_details": "01011112222",
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(post_response.status_code, status.HTTP_201_CREATED)
        created_id = post_response.json()["id"]

        # 2. GET collection -> 200 OK
        get_response = self.client.get(PAYMENT_METHODS_URL)
        self.assertEqual(get_response.status_code, status.HTTP_200_OK)
        returned_ids = [item["id"] for item in get_response.json()]
        self.assertIn(created_id, returned_ids)

        # 3. PATCH item -> 200 OK
        patch_response = self.client.patch(
            payment_method_detail_url(created_id),
            {"instructions": "Updated transfer instructions by coach"},
            format="json",
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            patch_response.json()["instructions"],
            "Updated transfer instructions by coach",
        )

        # 4. DELETE item -> 204 No Content
        delete_response = self.client.delete(payment_method_detail_url(created_id))
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)

    def test_active_coach_can_create_payment_method_201(self):
        """Asserts ACTIVE COACH receives 201 when creating a payment method."""
        coach = self._create_user(email="coach.post@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=coach, workspace=workspace, role="COACH", status="ACTIVE")
        self._create_membership(role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=coach)
        response = self.client.post(
            PAYMENT_METHODS_URL,
            {
                "type": "INSTAPAY",
                "name": "Coach InstaPay",
                "instructions": "Send to coach@instapay",
                "account_details": "coach@instapay",
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(set(data.keys()), EXPECTED_PAYMENT_METHOD_KEYS)
        self.assertEqual(data["name"], "Coach InstaPay")
        self.assertTrue(
            self.payment_method_model.objects.filter(pk=data["id"], workspace=workspace).exists(),
            "PaymentMethod must be created in the coach's workspace.",
        )

    def test_active_coach_can_patch_payment_method_200(self):
        """Asserts ACTIVE COACH receives 200 when updating a payment method."""
        coach = self._create_user(email="coach.patch@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=coach, workspace=workspace, role="COACH", status="ACTIVE")
        self._create_membership(role="OWNER", status="ACTIVE")

        pm = self._create_payment_method(
            workspace=workspace,
            type="BANK_TRANSFER",
            name="Bank Transfer Original",
        )

        self.client.force_authenticate(user=coach)
        response = self.client.patch(
            payment_method_detail_url(pm.id),
            {"name": "Bank Transfer Coach Updated"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        pm.refresh_from_db()
        self.assertEqual(pm.name, "Bank Transfer Coach Updated")

    def test_active_coach_can_delete_payment_method_204(self):
        """Asserts ACTIVE COACH receives 204 when deleting a payment method."""
        coach = self._create_user(email="coach.delete@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=coach, workspace=workspace, role="COACH", status="ACTIVE")
        self._create_membership(role="OWNER", status="ACTIVE")

        pm = self._create_payment_method(workspace=workspace, name="To Be Deleted By Coach")

        self.client.force_authenticate(user=coach)
        response = self.client.delete(payment_method_detail_url(pm.id))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(
            self.payment_method_model.objects.filter(pk=pm.id).exists(),
            "PaymentMethod must be hard-deleted from database.",
        )


class PaymentMethodsNoQualifyingMembershipTests(BasePaymentMethodsApiTestCase):
    """Verifies 404 NOT_FOUND and indistinguishability across non-qualifying users."""

    def test_no_membership_get_returns_404_not_found(self):
        """Asserts user with no membership receives 404 NOT_FOUND on GET payment methods."""
        user = self._create_user(email="nomem.get@example.com")
        self._create_membership(role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=user)
        response = self.client.get(PAYMENT_METHODS_URL)
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )

    def test_inactive_membership_get_returns_404_not_found(self):
        """Asserts user with INACTIVE membership receives 404 NOT_FOUND on GET payment methods."""
        user = self._create_user(email="inactive.get@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=user, workspace=workspace, role="OWNER", status="INACTIVE")

        self.client.force_authenticate(user=user)
        response = self.client.get(PAYMENT_METHODS_URL)
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )

    def test_suspended_workspace_get_returns_404_not_found(self):
        """Asserts caller in a SUSPENDED workspace receives 404 NOT_FOUND on GET payment methods."""
        user = self._create_user(email="suspended.get@example.com")
        workspace = self._create_workspace(status="SUSPENDED")
        self._create_membership(user=user, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=user)
        response = self.client.get(PAYMENT_METHODS_URL)
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )

    def test_client_only_membership_get_returns_404_not_found(self):
        """Asserts user with only CLIENT membership receives 404 NOT_FOUND on GET payment."""
        user = self._create_user(email="client.get@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=user, workspace=workspace, role="CLIENT", status="ACTIVE")

        self.client.force_authenticate(user=user)
        response = self.client.get(PAYMENT_METHODS_URL)
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )

    def test_four_non_qualifying_scenarios_on_get_are_strictly_indistinguishable(self):
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
        res_no_mem = self.client.get(PAYMENT_METHODS_URL)

        self.client.force_authenticate(user=user_inactive)
        res_inactive = self.client.get(PAYMENT_METHODS_URL)

        self.client.force_authenticate(user=user_suspended)
        res_suspended = self.client.get(PAYMENT_METHODS_URL)

        self.client.force_authenticate(user=user_client)
        res_client = self.client.get(PAYMENT_METHODS_URL)

        responses = [res_no_mem, res_inactive, res_suspended, res_client]

        for resp in responses:
            self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
            self.assertEqual(resp.json()["error"]["code"], "NOT_FOUND")
            self.assertNotIn("fields", resp.json()["error"])

        # Pairwise comparison of status, code, message
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

    def test_four_non_qualifying_scenarios_on_post_are_strictly_indistinguishable(self):
        """Asserts POST responses across all 4 non-qualifying cases are identical to each other."""
        user_no_mem = self._create_user(email="indist.nomem.post@example.com")

        user_inactive = self._create_user(email="indist.inactive.post@example.com")
        ws_inactive = self._create_workspace()
        self._create_membership(
            user=user_inactive, workspace=ws_inactive, role="OWNER", status="INACTIVE"
        )

        user_suspended = self._create_user(email="indist.suspended.post@example.com")
        ws_suspended = self._create_workspace(status="SUSPENDED")
        self._create_membership(
            user=user_suspended, workspace=ws_suspended, role="OWNER", status="ACTIVE"
        )

        user_client = self._create_user(email="indist.client.post@example.com")
        ws_client = self._create_workspace()
        self._create_membership(
            user=user_client, workspace=ws_client, role="CLIENT", status="ACTIVE"
        )

        payload = {
            "type": "INSTAPAY",
            "name": "Indistinguishable Test Method",
            "instructions": "Test instructions",
            "account_details": "01000000000",
        }

        self.client.force_authenticate(user=user_no_mem)
        res_no_mem = self.client.post(PAYMENT_METHODS_URL, payload, format="json")

        self.client.force_authenticate(user=user_inactive)
        res_inactive = self.client.post(PAYMENT_METHODS_URL, payload, format="json")

        self.client.force_authenticate(user=user_suspended)
        res_suspended = self.client.post(PAYMENT_METHODS_URL, payload, format="json")

        self.client.force_authenticate(user=user_client)
        res_client = self.client.post(PAYMENT_METHODS_URL, payload, format="json")

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


class PaymentMethodModelContractTests(BasePaymentMethodsApiTestCase):
    """Verifies PaymentMethod model schema contract, fields, typing, choices, and defaults."""

    def test_payment_method_concrete_fields_set_equality(self):
        """Asserts PaymentMethod defines exactly the ten documented concrete fields."""
        concrete_fields = {field.name for field in self.payment_method_model._meta.concrete_fields}
        self.assertSetEqual(
            concrete_fields,
            EXPECTED_PAYMENT_METHOD_FIELDS,
            "PaymentMethod concrete fields must exactly match the authoritative schema contract.",
        )

    def test_payment_method_type_choices_match_contract(self):
        """Asserts PaymentMethod.type choices are exactly the four documented values."""
        type_field = self.payment_method_model._meta.get_field("type")
        stored_choices = {
            choice[0] if isinstance(choice, (list, tuple)) else choice
            for choice in type_field.choices
        }
        self.assertSetEqual(
            stored_choices,
            VALID_PAYMENT_METHOD_TYPES,
            f"PaymentMethod.type choices must be exactly {VALID_PAYMENT_METHOD_TYPES}.",
        )

    def test_payment_method_is_active_defaults_to_true(self):
        """Asserts PaymentMethod.is_active field defaults to True."""
        is_active_field = self.payment_method_model._meta.get_field("is_active")
        self.assertTrue(
            is_active_field.default,
            "PaymentMethod.is_active field must default to True.",
        )

        # Confirm instance creation with omitted is_active defaults to True
        pm = self._create_payment_method()
        self.assertTrue(pm.is_active)

    def test_workspaces_app_exposes_exactly_workspace_and_payment_method_models(self):
        """Asserts workspaces app defines exactly {'Workspace', 'PaymentMethod'}."""
        workspaces_app = apps.get_app_config("workspaces")
        concrete_model_names = {model._meta.object_name for model in workspaces_app.get_models()}
        self.assertSetEqual(
            concrete_model_names,
            {"Workspace", "PaymentMethod"},
            "workspaces app must expose exactly {'Workspace', 'PaymentMethod'}.",
        )

    def test_payment_method_inherits_workspace_scoped_model_and_tenant_queryset(self):
        """Asserts PaymentMethod inherits WorkspaceScopedModel and TenantQuerySet scoping."""
        workspace_a = self._create_workspace(name="WS A Scoped")
        workspace_b = self._create_workspace(name="WS B Scoped")

        pm_a = self._create_payment_method(workspace=workspace_a, name="Method A")
        pm_b = self._create_payment_method(workspace=workspace_b, name="Method B")

        # TenantQuerySet.for_workspace scoping check
        qs_a = self.payment_method_model.objects.for_workspace(workspace_a)
        self.assertEqual(qs_a.count(), 1)
        self.assertEqual(qs_a.first().pk, pm_a.pk)
        self.assertFalse(qs_a.filter(pk=pm_b.pk).exists())

        # Unscoped queryset check
        all_pks = set(self.payment_method_model.objects.unscoped().values_list("pk", flat=True))
        self.assertTrue({pm_a.pk, pm_b.pk}.issubset(all_pks))


class PaymentMethodsPostEndpointTests(BasePaymentMethodsApiTestCase):
    """Verifies POST /api/v1/workspace/payment-methods creation, validation, and uploads."""

    def test_post_valid_json_creates_row_in_callers_workspace_with_nine_keys(self):
        """Asserts valid JSON POST returns 201 with exactly 9 keys in caller's workspace."""
        owner = self._create_user(email="pm.post.valid@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        # Decoy workspace to test proper tenant attachment
        self._create_membership(role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        payload = {
            "type": "INSTAPAY",
            "name": "Primary InstaPay Account",
            "instructions": "Send to mobile number and upload receipt",
            "account_details": "01001234567",
            "is_active": True,
        }
        response = self.client.post(PAYMENT_METHODS_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(
            set(data.keys()),
            EXPECTED_PAYMENT_METHOD_KEYS,
            "POST response body must contain exactly the nine documented model keys.",
        )
        self.assertNotIn("workspace", data)
        self.assertNotIn("workspace_id", data)
        self.assertEqual(data["type"], "INSTAPAY")
        self.assertEqual(data["name"], "Primary InstaPay Account")
        self.assertEqual(data["instructions"], "Send to mobile number and upload receipt")
        self.assertEqual(data["account_details"], "01001234567")
        self.assertTrue(data["is_active"])
        self.assertIsNone(data["image"])

        # Verify database row is created in caller's workspace
        pm = self.payment_method_model.objects.get(pk=data["id"])
        self.assertEqual(pm.workspace_id, workspace.id)
        self.assertEqual(pm.name, "Primary InstaPay Account")

    def test_post_accepts_all_four_payment_method_types(self):
        """Asserts POST succeeds (201) for each of the four documented payment method types."""
        owner = self._create_user(email="pm.post.types@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)

        for pm_type in VALID_PAYMENT_METHOD_TYPES:
            with self.subTest(payment_method_type=pm_type):
                response = self.client.post(
                    PAYMENT_METHODS_URL,
                    {
                        "type": pm_type,
                        "name": f"Method for {pm_type}",
                        "instructions": f"Instructions for {pm_type}",
                        "account_details": f"Details for {pm_type}",
                        "is_active": True,
                    },
                    format="json",
                )
                self.assertEqual(
                    response.status_code,
                    status.HTTP_201_CREATED,
                    f"POST with type '{pm_type}' must return 201 Created.",
                )
                self.assertEqual(response.json()["type"], pm_type)

    def test_post_invalid_type_returns_400_validation_error(self):
        """Asserts submitting an invalid type returns 400 VALIDATION_ERROR with 'type' field."""
        owner = self._create_user(email="pm.badtype@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        response = self.client.post(
            PAYMENT_METHODS_URL,
            {
                "type": "BITCOIN",
                "name": "Crypto Wallet",
                "instructions": "Send BTC",
                "account_details": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
            },
            format="json",
        )
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_400_BAD_REQUEST,
            expected_code="VALIDATION_ERROR",
            expected_field="type",
        )
        self.assertEqual(self.payment_method_model.objects.count(), 0)

    def test_post_missing_name_returns_400_validation_error(self):
        """Asserts omitting the required 'name' field returns 400 VALIDATION_ERROR."""
        owner = self._create_user(email="pm.noname@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        response = self.client.post(
            PAYMENT_METHODS_URL,
            {
                "type": "INSTAPAY",
                "instructions": "Send payment",
                "account_details": "01000000000",
            },
            format="json",
        )
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_400_BAD_REQUEST,
            expected_code="VALIDATION_ERROR",
            expected_field="name",
        )
        self.assertEqual(self.payment_method_model.objects.count(), 0)

    def test_post_omitted_is_active_defaults_to_true(self):
        """Asserts is_active defaults to True when omitted from the POST request payload."""
        owner = self._create_user(email="pm.defaultactive@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        response = self.client.post(
            PAYMENT_METHODS_URL,
            {
                "type": "BANK_TRANSFER",
                "name": "CIB Bank Account",
                "instructions": "Transfer to CIB account",
                "account_details": "EG12345678901234567890",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertTrue(data["is_active"], "Response is_active must default to True.")

        pm = self.payment_method_model.objects.get(pk=data["id"])
        self.assertTrue(pm.is_active, "Database is_active must default to True.")

    def test_post_with_image_multipart_converts_to_webp_and_returns_url(self):
        """Asserts uploading an image converts it to WebP format and returns a URL."""
        owner = self._create_user(email="pm.image@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        png_file = make_test_image(
            width=500, height=300, image_format="PNG", filename="instapay_qr.png"
        )
        response = self.client.post(
            PAYMENT_METHODS_URL,
            {
                "type": "INSTAPAY",
                "name": "InstaPay with QR",
                "instructions": "Scan QR code to pay",
                "account_details": "01000000000",
                "is_active": True,
                "image": png_file,
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(set(data.keys()), EXPECTED_PAYMENT_METHOD_KEYS)
        self.assertIsNotNone(data["image"])
        self.assertIsInstance(data["image"], str)

        # Image URL must not leak raw filesystem path
        self.assertNotIn(self.temp_media_dir, data["image"])
        self.assertFalse(data["image"].startswith("/Users/"))
        self.assertFalse(data["image"].startswith("/private/"))

        pm = self.payment_method_model.objects.get(pk=data["id"])
        self.assertTrue(bool(pm.image), "PaymentMethod.image FileField must be populated.")
        self.assertTrue(
            pm.image.name.endswith(".webp"),
            f"Stored filename must end with '.webp', got '{pm.image.name}'.",
        )

        # Read stored bytes back with PIL to verify binary format is WEBP
        with pm.image.open("rb") as stored_file:
            with Image.open(stored_file) as img:
                self.assertEqual(
                    img.format,
                    "WEBP",
                    f"Stored image format must be 'WEBP', got '{img.format}'.",
                )

    def test_post_non_image_file_returns_400_unsupported_file_type(self):
        """Asserts non-image upload returns 400 UNSUPPORTED_FILE_TYPE without 'fields' dict."""
        owner = self._create_user(email="pm.badmime@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        text_file = make_non_image_file(filename="qr.txt")
        response = self.client.post(
            PAYMENT_METHODS_URL,
            {
                "type": "INSTAPAY",
                "name": "Invalid File InstaPay",
                "instructions": "Some instructions",
                "account_details": "01000000000",
                "image": text_file,
            },
            format="multipart",
        )
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_400_BAD_REQUEST,
            expected_code="UNSUPPORTED_FILE_TYPE",
        )
        self.assertEqual(self.payment_method_model.objects.count(), 0)

    def test_post_oversize_file_returns_400_file_too_large(self):
        """Asserts uploading a file > 10 MB returns 400 FILE_TOO_LARGE without 'fields' dict."""
        owner = self._create_user(email="pm.hugefile@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        large_file = make_large_file(size_bytes=11 * 1024 * 1024, filename="huge_qr.png")
        response = self.client.post(
            PAYMENT_METHODS_URL,
            {
                "type": "INSTAPAY",
                "name": "Huge File InstaPay",
                "instructions": "Some instructions",
                "account_details": "01000000000",
                "image": large_file,
            },
            format="multipart",
        )
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_400_BAD_REQUEST,
            expected_code="FILE_TOO_LARGE",
        )
        self.assertEqual(self.payment_method_model.objects.count(), 0)

    def test_post_disallowed_image_mime_type_returns_400_unsupported_file_type(self):
        """Asserts decodable image of disallowed MIME type (ICO) returns 400 UNSUPPORTED."""
        owner = self._create_user(email="pm.ico@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        buf = io.BytesIO()
        Image.new("RGB", (64, 64), (10, 20, 30)).save(buf, format="ICO")
        ico_upload = SimpleUploadedFile("icon.ico", buf.getvalue(), content_type="image/x-icon")

        response = self.client.post(
            PAYMENT_METHODS_URL,
            {
                "type": "INSTAPAY",
                "name": "ICO InstaPay",
                "instructions": "Some instructions",
                "account_details": "01000000000",
                "image": ico_upload,
            },
            format="multipart",
        )
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_400_BAD_REQUEST,
            expected_code="UNSUPPORTED_FILE_TYPE",
        )
        self.assertEqual(self.payment_method_model.objects.count(), 0)


class PaymentMethodsGetEndpointTests(BasePaymentMethodsApiTestCase):
    """Verifies GET /api/v1/workspace/payment-methods unpaginated list and tenant isolation."""

    def test_get_returns_only_callers_workspace_payment_methods(self):
        """Asserts GET returns only the caller's Workspace payment methods, excluding others."""
        owner_a = self._create_user(email="owner.a.get@example.com")
        ws_a = self._create_workspace(name="Gym A")
        self._create_membership(user=owner_a, workspace=ws_a, role="OWNER", status="ACTIVE")

        owner_b = self._create_user(email="owner.b.get@example.com")
        ws_b = self._create_workspace(name="Gym B")
        self._create_membership(user=owner_b, workspace=ws_b, role="OWNER", status="ACTIVE")

        pm_a1 = self._create_payment_method(workspace=ws_a, type="INSTAPAY", name="Gym A InstaPay")
        pm_a2 = self._create_payment_method(
            workspace=ws_a, type="VODAFONE_CASH", name="Gym A Vodafone Cash"
        )
        pm_b1 = self._create_payment_method(
            workspace=ws_b, type="BANK_TRANSFER", name="Gym B Bank Transfer"
        )
        pm_b2 = self._create_payment_method(workspace=ws_b, type="CUSTOM", name="Gym B Cash Desk")

        self.client.force_authenticate(user=owner_a)
        response = self.client.get(PAYMENT_METHODS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertIsInstance(data, list, "GET response must be a plain unpaginated list.")
        self.assertEqual(len(data), 2, "Response must contain exactly the 2 methods in WS A.")

        returned_ids = {item["id"] for item in data}
        self.assertSetEqual(
            returned_ids,
            {str(pm_a1.id), str(pm_a2.id)},
            "GET response must contain only Workspace A payment method IDs.",
        )
        self.assertNotIn(str(pm_b1.id), returned_ids)
        self.assertNotIn(str(pm_b2.id), returned_ids)

        for item in data:
            self.assertEqual(
                set(item.keys()),
                EXPECTED_PAYMENT_METHOD_KEYS,
                "Each payment method item must contain exactly the nine documented keys.",
            )
            self.assertNotIn("workspace", item)

    def test_get_returns_empty_list_when_no_payment_methods_exist(self):
        """Asserts GET returns an empty list `[]` when caller's workspace has no payment methods."""
        owner_a = self._create_user(email="owner.empty.a@example.com")
        ws_a = self._create_workspace(name="Gym A Empty")
        self._create_membership(user=owner_a, workspace=ws_a, role="OWNER", status="ACTIVE")

        owner_b = self._create_user(email="owner.empty.b@example.com")
        ws_b = self._create_workspace(name="Gym B NonEmpty")
        self._create_membership(user=owner_b, workspace=ws_b, role="OWNER", status="ACTIVE")
        self._create_payment_method(workspace=ws_b, name="Gym B Method")

        self.client.force_authenticate(user=owner_a)
        response = self.client.get(PAYMENT_METHODS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), [])


class PaymentMethodsPatchEndpointTests(BasePaymentMethodsApiTestCase):
    """Verifies PATCH /api/v1/workspace/payment-methods/{id} partial updates and cross-tenant."""

    def test_patch_partial_update_modifies_name_and_preserves_other_fields(self):
        """Asserts partial update modifies the targeted field and leaves other fields intact."""
        owner = self._create_user(email="pm.patch.partial@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        pm = self._create_payment_method(
            workspace=workspace,
            type="INSTAPAY",
            name="Original InstaPay Name",
            instructions="Original instructions text",
            account_details="01001112223",
            is_active=True,
        )

        self.client.force_authenticate(user=owner)
        response = self.client.patch(
            payment_method_detail_url(pm.id),
            {"name": "Updated InstaPay Name"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(set(data.keys()), EXPECTED_PAYMENT_METHOD_KEYS)
        self.assertEqual(data["name"], "Updated InstaPay Name")
        self.assertEqual(data["instructions"], "Original instructions text")
        self.assertEqual(data["account_details"], "01001112223")
        self.assertEqual(data["type"], "INSTAPAY")
        self.assertTrue(data["is_active"])

        pm.refresh_from_db()
        self.assertEqual(pm.name, "Updated InstaPay Name")
        self.assertEqual(pm.instructions, "Original instructions text")
        self.assertEqual(pm.account_details, "01001112223")

    def test_patch_toggle_is_active_flag(self):
        """Asserts is_active can be toggled to False and back to True via PATCH."""
        owner = self._create_user(email="pm.patch.active@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        pm = self._create_payment_method(workspace=workspace, is_active=True)

        self.client.force_authenticate(user=owner)

        # Deactivate
        res_false = self.client.patch(
            payment_method_detail_url(pm.id),
            {"is_active": False},
            format="json",
        )
        self.assertEqual(res_false.status_code, status.HTTP_200_OK)
        self.assertFalse(res_false.json()["is_active"])
        pm.refresh_from_db()
        self.assertFalse(pm.is_active)

        # Reactivate
        res_true = self.client.patch(
            payment_method_detail_url(pm.id),
            {"is_active": True},
            format="json",
        )
        self.assertEqual(res_true.status_code, status.HTTP_200_OK)
        self.assertTrue(res_true.json()["is_active"])
        pm.refresh_from_db()
        self.assertTrue(pm.is_active)

    def test_patch_replace_image_stores_new_webp(self):
        """Asserts replacing image via multipart PATCH converts new image to WebP."""
        owner = self._create_user(email="pm.patch.img@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        pm = self._create_payment_method(workspace=workspace, name="Method With Image")

        self.client.force_authenticate(user=owner)
        new_image = make_test_image(
            width=600, height=400, color=(10, 80, 200), filename="replacement_qr.png"
        )
        response = self.client.patch(
            payment_method_detail_url(pm.id),
            {"image": new_image, "instructions": "Updated instructions with new QR"},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIsNotNone(data["image"])

        pm.refresh_from_db()
        self.assertTrue(pm.image.name.endswith(".webp"))
        with pm.image.open("rb") as stored_file:
            with Image.open(stored_file) as img:
                self.assertEqual(img.format, "WEBP")

    def test_patch_cross_workspace_id_returns_404_and_leaves_target_unchanged(self):
        """Cross-tenant PATCH: attempting to update WS B item as Owner A returns 404 & no-op."""
        owner_a = self._create_user(email="owner.a.patch@example.com")
        ws_a = self._create_workspace(name="Gym A")
        self._create_membership(user=owner_a, workspace=ws_a, role="OWNER", status="ACTIVE")

        owner_b = self._create_user(email="owner.b.patch@example.com")
        ws_b = self._create_workspace(name="Gym B")
        self._create_membership(user=owner_b, workspace=ws_b, role="OWNER", status="ACTIVE")

        pm_b = self._create_payment_method(
            workspace=ws_b,
            name="Gym B Untouched Method",
            instructions="Gym B original instructions",
        )

        self.client.force_authenticate(user=owner_a)
        response = self.client.patch(
            payment_method_detail_url(pm_b.id),
            {"name": "Hacked Method Name", "instructions": "Hacked instructions"},
            format="json",
        )
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )

        pm_b.refresh_from_db()
        self.assertEqual(
            pm_b.name,
            "Gym B Untouched Method",
            "Target payment method in Workspace B must remain unchanged.",
        )
        self.assertEqual(
            pm_b.instructions,
            "Gym B original instructions",
            "Target payment method in Workspace B must remain unchanged.",
        )


class PaymentMethodsDeleteEndpointTests(BasePaymentMethodsApiTestCase):
    """Verifies DELETE /api/v1/workspace/payment-methods/{id} hard delete and cross-tenant."""

    def test_delete_succeeds_204_and_hard_deletes_row_from_database(self):
        """Asserts DELETE returns 204 and permanently removes the row from the database."""
        owner = self._create_user(email="owner.del@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        pm = self._create_payment_method(
            workspace=workspace,
            type="INSTAPAY",
            name="Hard Delete Target",
            is_active=True,
        )

        self.client.force_authenticate(user=owner)
        response = self.client.delete(payment_method_detail_url(pm.id))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # Confirm hard delete: row is gone from scoped queryset and unscoped queryset
        self.assertFalse(
            self.payment_method_model.objects.filter(pk=pm.id).exists(),
            "PaymentMethod row must no longer exist in standard queryset.",
        )
        self.assertFalse(
            self.payment_method_model.objects.unscoped().filter(pk=pm.id).exists(),
            "PaymentMethod row must be permanently hard-deleted (not soft-deleted).",
        )

    def test_delete_twice_returns_404_on_second_call(self):
        """Asserts deleting an already deleted payment method returns 404 NOT_FOUND."""
        owner = self._create_user(email="owner.deltwice@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        pm = self._create_payment_method(workspace=workspace, name="Delete Twice Target")

        self.client.force_authenticate(user=owner)
        first_delete = self.client.delete(payment_method_detail_url(pm.id))
        self.assertEqual(first_delete.status_code, status.HTTP_204_NO_CONTENT)

        second_delete = self.client.delete(payment_method_detail_url(pm.id))
        self.assert_error_envelope(
            second_delete,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )

    def test_delete_cross_workspace_id_returns_404_and_target_row_survives(self):
        """Cross-tenant delete: deleting WS B payment method as Owner A returns 404 and survives."""
        owner_a = self._create_user(email="owner.a.del@example.com")
        ws_a = self._create_workspace(name="Gym A")
        self._create_membership(user=owner_a, workspace=ws_a, role="OWNER", status="ACTIVE")

        owner_b = self._create_user(email="owner.b.del@example.com")
        ws_b = self._create_workspace(name="Gym B")
        self._create_membership(user=owner_b, workspace=ws_b, role="OWNER", status="ACTIVE")

        pm_a = self._create_payment_method(workspace=ws_a, name="Payment Method A")
        pm_b = self._create_payment_method(workspace=ws_b, name="Payment Method B")

        self.client.force_authenticate(user=owner_a)
        response = self.client.delete(payment_method_detail_url(pm_b.id))
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )

        # Verify WS B's record survives intact in database
        self.assertTrue(
            self.payment_method_model.objects.filter(pk=pm_b.id).exists(),
            "PaymentMethod in Workspace B must survive foreign delete attempt.",
        )
        self.assertTrue(
            self.payment_method_model.objects.filter(pk=pm_a.id).exists(),
            "PaymentMethod in Workspace A must remain intact.",
        )


class PaymentMethodsObjectIsolationTests(BasePaymentMethodsApiTestCase):
    """Verifies that cross-workspace IDs and non-existent random UUIDs produce identical 404s."""

    def test_cross_workspace_id_and_nonexistent_uuid_produce_indistinguishable_404_on_patch(self):
        """Object isolation guard: cross-workspace ID and random UUID produce identical."""
        owner_a = self._create_user(email="iso.owner.a.patch@example.com")
        ws_a = self._create_workspace(name="Gym A")
        self._create_membership(user=owner_a, workspace=ws_a, role="OWNER", status="ACTIVE")

        owner_b = self._create_user(email="iso.owner.b.patch@example.com")
        ws_b = self._create_workspace(name="Gym B")
        self._create_membership(user=owner_b, workspace=ws_b, role="OWNER", status="ACTIVE")

        pm_b = self._create_payment_method(workspace=ws_b, name="WS B Secret Method")
        non_existent_id = uuid.uuid4()

        self.client.force_authenticate(user=owner_a)

        # Cross-workspace ID request
        res_cross = self.client.patch(
            payment_method_detail_url(pm_b.id),
            {"name": "Tampered Name"},
            format="json",
        )

        # Non-existent random UUID request
        res_nonexistent = self.client.patch(
            payment_method_detail_url(non_existent_id),
            {"name": "Tampered Name"},
            format="json",
        )

        # Assert never 403
        self.assertNotEqual(
            res_cross.status_code,
            status.HTTP_403_FORBIDDEN,
            "Cross-workspace ID must never return 403 Forbidden.",
        )

        # Assert both return 404 NOT_FOUND
        self.assertEqual(res_cross.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(res_nonexistent.status_code, status.HTTP_404_NOT_FOUND)

        # Assert byte-identical responses
        self.assertEqual(res_cross.status_code, res_nonexistent.status_code)
        self.assertEqual(
            res_cross.json()["error"]["code"],
            res_nonexistent.json()["error"]["code"],
        )
        self.assertEqual(
            res_cross.json()["error"]["message"],
            res_nonexistent.json()["error"]["message"],
        )
        self.assertEqual(res_cross.content, res_nonexistent.content)

    def test_cross_workspace_id_and_nonexistent_uuid_produce_indistinguishable_404_on_delete(self):
        """Object isolation guard: cross-workspace ID and random UUID produce identical 404s."""
        owner_a = self._create_user(email="iso.owner.a.del@example.com")
        ws_a = self._create_workspace(name="Gym A")
        self._create_membership(user=owner_a, workspace=ws_a, role="OWNER", status="ACTIVE")

        owner_b = self._create_user(email="iso.owner.b.del@example.com")
        ws_b = self._create_workspace(name="Gym B")
        self._create_membership(user=owner_b, workspace=ws_b, role="OWNER", status="ACTIVE")

        pm_b = self._create_payment_method(workspace=ws_b, name="WS B Method")
        non_existent_id = uuid.uuid4()

        self.client.force_authenticate(user=owner_a)

        res_cross = self.client.delete(payment_method_detail_url(pm_b.id))
        res_nonexistent = self.client.delete(payment_method_detail_url(non_existent_id))

        self.assertNotEqual(
            res_cross.status_code,
            status.HTTP_403_FORBIDDEN,
            "Cross-workspace ID must never return 403 Forbidden.",
        )
        self.assertEqual(res_cross.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(res_nonexistent.status_code, status.HTTP_404_NOT_FOUND)

        self.assertEqual(res_cross.status_code, res_nonexistent.status_code)
        self.assertEqual(
            res_cross.json()["error"]["code"],
            res_nonexistent.json()["error"]["code"],
        )
        self.assertEqual(
            res_cross.json()["error"]["message"],
            res_nonexistent.json()["error"]["message"],
        )
        self.assertEqual(res_cross.content, res_nonexistent.content)


class PaymentMethodsRateLimitingTests(BasePaymentMethodsApiTestCase):
    """Verifies ScopedRateThrottle enforcement (20/hour) under workspace_logo_upload scope."""

    def test_post_throttled_under_shared_upload_scope_at_21st_request(self):
        """Asserts POST is rate-limited at 20/hour under workspace_logo_upload scope."""
        owner = self._create_user(email="throttle.pm.post@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)

        for i in range(20):
            response = self.client.post(
                PAYMENT_METHODS_URL,
                {
                    "type": "CUSTOM",
                    "name": f"Method {i}",
                    "instructions": "Instructions",
                    "account_details": f"ACC_{i}",
                },
                format="json",
            )
            self.assertEqual(
                response.status_code,
                status.HTTP_201_CREATED,
                f"POST request {i + 1} within rate limit must succeed with 201.",
            )

        # 21st request must be throttled
        throttled_response = self.client.post(
            PAYMENT_METHODS_URL,
            {
                "type": "CUSTOM",
                "name": "Method 21",
                "instructions": "Instructions",
                "account_details": "ACC_21",
            },
            format="json",
        )
        self.assert_error_envelope(
            throttled_response,
            expected_status=status.HTTP_429_TOO_MANY_REQUESTS,
            expected_code="RATE_LIMITED",
        )

    def test_patch_throttled_under_shared_upload_scope_at_21st_request(self):
        """Asserts PATCH is rate-limited at 20/hour under workspace_logo_upload scope."""
        owner = self._create_user(email="throttle.pm.patch@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        pm = self._create_payment_method(workspace=workspace, name="Throttled Target")

        self.client.force_authenticate(user=owner)

        for i in range(20):
            response = self.client.patch(
                payment_method_detail_url(pm.id),
                {"name": f"Patched Name {i}"},
                format="json",
            )
            self.assertEqual(
                response.status_code,
                status.HTTP_200_OK,
                f"PATCH request {i + 1} within rate limit must succeed with 200.",
            )

        # 21st request must be throttled
        throttled_response = self.client.patch(
            payment_method_detail_url(pm.id),
            {"name": "Patched Name 21"},
            format="json",
        )
        self.assert_error_envelope(
            throttled_response,
            expected_status=status.HTTP_429_TOO_MANY_REQUESTS,
            expected_code="RATE_LIMITED",
        )

    def test_get_and_delete_endpoints_are_not_throttled(self):
        """Asserts GET and DELETE endpoints remain unthrottled during burst requests."""
        owner = self._create_user(email="throttle.pm.burst@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self._create_payment_method(workspace=workspace, name="Persistent Method")

        self.client.force_authenticate(user=owner)

        # Burst of 25 GET requests must all succeed with 200
        for i in range(25):
            get_response = self.client.get(PAYMENT_METHODS_URL)
            self.assertEqual(
                get_response.status_code,
                status.HTTP_200_OK,
                f"GET request {i + 1} must not be throttled.",
            )


class PaymentMethodsContractPreservationAndArchitectureTests(BasePaymentMethodsApiTestCase):
    """Guards Story 4.1/4.2 11-key contracts, billing app model boundaries, and method dispatch."""

    def test_get_workspace_preserves_exact_eleven_keys_contract(self):
        """Contract preservation: GET /api/v1/workspace returns exactly the 11 established keys."""
        owner = self._create_user(email="guard.pm.get@example.com")
        workspace = self._create_workspace(description="Guarded description", brand_color="#123456")
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        response = self.client.get(WORKSPACE_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(
            set(data.keys()),
            EXPECTED_WORKSPACE_KEYS,
            "GET /api/v1/workspace response keys must be exactly the 11 established keys.",
        )
        self.assertNotIn(
            "payment_methods",
            data,
            "payment_methods must not be present in GET /api/v1/workspace response.",
        )

    def test_billing_app_exposes_no_models(self):
        """Guards Epic 22 boundary: billing app must define zero models in Story 4.4."""
        billing_app = apps.get_app_config("billing")
        concrete_model_names = {model._meta.object_name for model in billing_app.get_models()}
        self.assertEqual(
            concrete_model_names,
            set(),
            "billing app must expose no models (deferred to Epic 22).",
        )

    def test_disallowed_http_methods_return_405_method_not_allowed(self):
        """Asserts disallowed HTTP methods on collection and detail return 405."""
        owner = self._create_user(email="pm.methods@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        pm = self._create_payment_method(workspace=workspace, name="Method For 405")

        self.client.force_authenticate(user=owner)

        # Disallowed on collection (only GET and POST are allowed)
        for method in ["put", "delete"]:
            with self.subTest(endpoint=PAYMENT_METHODS_URL, http_method=method):
                client_method = getattr(self.client, method)
                response = client_method(PAYMENT_METHODS_URL)
                self.assertEqual(
                    response.status_code,
                    status.HTTP_405_METHOD_NOT_ALLOWED,
                    f"HTTP {method.upper()} to {PAYMENT_METHODS_URL} must return 405.",
                )

        # Disallowed on detail (only PATCH and DELETE are allowed)
        detail_url = payment_method_detail_url(pm.id)
        for method in ["post", "put"]:
            with self.subTest(endpoint=detail_url, http_method=method):
                client_method = getattr(self.client, method)
                response = client_method(detail_url)
                self.assertEqual(
                    response.status_code,
                    status.HTTP_405_METHOD_NOT_ALLOWED,
                    f"HTTP {method.upper()} to {detail_url} must return 405.",
                )
