"""API tests for Workspace Branding and Image Pipeline (Story 4.3 / Task B).

Validates:
- Access control: unauthenticated POST /workspace/logo and PATCH /workspace/branding are rejected
  with 401/403 and the standard API §2 error envelope.
- Authorization: ACTIVE OWNER can upload logo and patch branding; ACTIVE COACH is rejected on both
  endpoints with 403 PERMISSION_DENIED (without exposing a 'fields' dictionary).
- 404 family & indistinguishability: callers with no membership, INACTIVE membership,
  SUSPENDED workspace, or CLIENT-only role receive identical 404 NOT_FOUND responses across
  both endpoints without revealing workspace existence.
- Cross-tenant isolation: logo uploads and branding updates by Owner A alter only Workspace A,
  leaving Workspace B completely untouched.
- POST /workspace/logo contract: exactly one response key {"logo"}, non-empty stored FileField,
  WebP conversion (PIL format == 'WEBP' and .webp extension), max width resize (<= 1600px with
  preserved aspect ratio), no upscaling for narrower images, 400px thumbnail generation, and no
  raw filesystem path in the response.
- PATCH /workspace/branding contract: exactly four response keys {"logo", "profile_image",
  "brand_color", "description"}, partial updates (omitted fields remain unchanged), multipart
  file upload support with WebP conversion, and null values for unset images.
- Upload validation: non-image MIME types return 400 UNSUPPORTED_FILE_TYPE; files > 10 MB return
  400 FILE_TOO_LARGE; missing file on POST /workspace/logo returns 400 VALIDATION_ERROR.
- Rate limiting: scope 'workspace_logo_upload' enforced at 20/hour on both upload endpoints (429
  RATE_LIMITED on the 21st request); unrelated endpoints (e.g. GET /workspace) remain unthrottled.
- Contract preservation & architecture guards: GET and PATCH /api/v1/workspace preserve exactly
  eleven response keys without logo or profile_image; workspaces app defines {"Workspace"}; billing
  defines no models; disallowed HTTP methods return 405 Method Not Allowed.
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

BRANDING_URL = "/api/v1/workspace/branding"
LOGO_URL = "/api/v1/workspace/logo"
WORKSPACE_URL = "/api/v1/workspace"

EXPECTED_BRANDING_KEYS = {"logo", "profile_image", "brand_color", "description"}
EXPECTED_LOGO_KEYS = {"logo"}
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


class BaseWorkspaceBrandingApiTestCase(TestCase):
    """Base test case providing client setup, cache reset, media isolation, and entity helpers."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.client = APIClient()
        self.user_model = get_user_model()
        self.workspace_model = apps.get_model("workspaces", "Workspace")
        self.membership_model = apps.get_model("accounts", "Membership")

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


class WorkspaceBrandingAccessAndAuthorizationTests(BaseWorkspaceBrandingApiTestCase):
    """Verifies authentication, OWNER permissions, COACH restrictions, and cross-tenant bounds."""

    def test_unauthenticated_post_logo_returns_401_or_403_with_error_envelope(self):
        """Asserts unauthenticated POST /workspace/logo returns 401/403 with error envelope."""
        image_file = make_test_image()
        response = self.client.post(LOGO_URL, {"logo": image_file}, format="multipart")
        self.assertIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )
        data = response.json()
        self.assertEqual(set(data.keys()), {"error"})
        self.assertIsInstance(data["error"], dict)

    def test_unauthenticated_patch_branding_returns_401_or_403_with_error_envelope(self):
        """Asserts unauthenticated PATCH /workspace/branding returns 401/403 with error envelope."""
        response = self.client.patch(
            BRANDING_URL,
            {"brand_color": "#111111", "description": "Unauthorized bio"},
            format="json",
        )
        self.assertIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )
        data = response.json()
        self.assertEqual(set(data.keys()), {"error"})
        self.assertIsInstance(data["error"], dict)

    def test_active_owner_post_logo_succeeds_200(self):
        """Asserts caller with an ACTIVE OWNER membership receives 200 on POST /workspace/logo."""
        owner = self._create_user(email="owner.logo@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        # Decoy workspace to ensure proper membership resolution
        self._create_membership(role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        image_file = make_test_image()
        response = self.client.post(LOGO_URL, {"logo": image_file}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(set(data.keys()), EXPECTED_LOGO_KEYS)
        self.assertIsNotNone(data["logo"])

    def test_active_owner_patch_branding_succeeds_200(self):
        """Asserts caller with ACTIVE OWNER receives 200 on PATCH /workspace/branding."""
        owner = self._create_user(email="owner.branding@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self._create_membership(role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        response = self.client.patch(
            BRANDING_URL,
            {"brand_color": "#222222", "description": "Owner branding description"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(set(data.keys()), EXPECTED_BRANDING_KEYS)
        self.assertEqual(data["brand_color"], "#222222")
        self.assertEqual(data["description"], "Owner branding description")

    def test_active_coach_post_logo_returns_403_permission_denied(self):
        """Central authorization guard."""
        coach = self._create_user(email="coach.logo@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=coach, workspace=workspace, role="COACH", status="ACTIVE")

        self._create_membership(role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=coach)
        image_file = make_test_image()
        response = self.client.post(LOGO_URL, {"logo": image_file}, format="multipart")
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_403_FORBIDDEN,
            expected_code="PERMISSION_DENIED",
        )
        workspace.refresh_from_db()
        self.assertFalse(
            bool(workspace.logo),
            "Workspace logo must remain empty after forbidden coach logo upload attempt.",
        )

    def test_active_coach_patch_branding_returns_403_permission_denied(self):
        """Central auth guard: ACTIVE COACH hitting PATCH /branding gets 403 PERMISSION_DENIED."""
        coach = self._create_user(email="coach.branding@example.com")
        workspace = self._create_workspace(brand_color="#000000", description="Original Coach Bio")
        self._create_membership(user=coach, workspace=workspace, role="COACH", status="ACTIVE")

        self._create_membership(role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=coach)
        response = self.client.patch(
            BRANDING_URL,
            {"brand_color": "#FFFFFF", "description": "Unauthorized coach attempt"},
            format="json",
        )
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_403_FORBIDDEN,
            expected_code="PERMISSION_DENIED",
        )
        workspace.refresh_from_db()
        self.assertEqual(workspace.brand_color, "#000000")
        self.assertEqual(workspace.description, "Original Coach Bio")

    def test_cross_tenant_post_logo_modifies_only_callers_workspace(self):
        """Cross-tenant isolation: Owner A upload modifies only Workspace A, leaving B untouched."""
        owner_a = self._create_user(email="owner.a.logo@example.com")
        workspace_a = self._create_workspace(name="Gym A")
        self._create_membership(user=owner_a, workspace=workspace_a, role="OWNER", status="ACTIVE")

        owner_b = self._create_user(email="owner.b.logo@example.com")
        workspace_b = self._create_workspace(name="Gym B")
        self._create_membership(user=owner_b, workspace=workspace_b, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner_a)
        image_file = make_test_image(filename="owner_a_logo.png")
        response = self.client.post(LOGO_URL, {"logo": image_file}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        workspace_a.refresh_from_db()
        workspace_b.refresh_from_db()

        self.assertTrue(bool(workspace_a.logo), "Workspace A logo must be populated.")
        self.assertFalse(bool(workspace_b.logo), "Workspace B logo must remain untouched/empty.")

    def test_cross_tenant_patch_branding_modifies_only_callers_workspace(self):
        """Cross-tenant isolation: Owner A branding update modifies only A, leaving B untouched."""
        owner_a = self._create_user(email="owner.a.branding@example.com")
        workspace_a = self._create_workspace(
            name="Gym A", brand_color="#111111", description="Bio A"
        )
        self._create_membership(user=owner_a, workspace=workspace_a, role="OWNER", status="ACTIVE")

        owner_b = self._create_user(email="owner.b.branding@example.com")
        workspace_b = self._create_workspace(
            name="Gym B", brand_color="#222222", description="Bio B"
        )
        self._create_membership(user=owner_b, workspace=workspace_b, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner_a)
        response = self.client.patch(
            BRANDING_URL,
            {"brand_color": "#999999", "description": "Updated Bio A"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        workspace_a.refresh_from_db()
        workspace_b.refresh_from_db()

        self.assertEqual(workspace_a.brand_color, "#999999")
        self.assertEqual(workspace_a.description, "Updated Bio A")
        self.assertEqual(
            workspace_b.brand_color,
            "#222222",
            "Workspace B brand_color must remain unchanged.",
        )
        self.assertEqual(
            workspace_b.description,
            "Bio B",
            "Workspace B description must remain unchanged.",
        )


class WorkspaceBrandingNoQualifyingMembershipTests(BaseWorkspaceBrandingApiTestCase):
    """Verifies 404 NOT_FOUND and indistinguishability across non-qualifying users."""

    def test_no_membership_post_logo_returns_404_not_found(self):
        """Asserts user with no membership receives 404 NOT_FOUND on POST /workspace/logo."""
        user = self._create_user(email="nomem.logo@example.com")
        self._create_membership(role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=user)
        response = self.client.post(LOGO_URL, {"logo": make_test_image()}, format="multipart")
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )

    def test_inactive_membership_post_logo_returns_404_not_found(self):
        """Asserts user with INACTIVE membership receives 404 NOT_FOUND on POST /workspace/logo."""
        user = self._create_user(email="inactive.logo@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=user, workspace=workspace, role="OWNER", status="INACTIVE")

        self.client.force_authenticate(user=user)
        response = self.client.post(LOGO_URL, {"logo": make_test_image()}, format="multipart")
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )

    def test_suspended_workspace_post_logo_returns_404_not_found(self):
        """Asserts owner of a SUSPENDED workspace receives 404 NOT_FOUND on POST /workspace/logo."""
        user = self._create_user(email="suspended.logo@example.com")
        workspace = self._create_workspace(status="SUSPENDED")
        self._create_membership(user=user, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=user)
        response = self.client.post(LOGO_URL, {"logo": make_test_image()}, format="multipart")
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )

    def test_client_only_membership_post_logo_returns_404_not_found(self):
        """Asserts user with only CLIENT membership receives 404 NOT_FOUND on POST /workspace/lo."""
        user = self._create_user(email="client.logo@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=user, workspace=workspace, role="CLIENT", status="ACTIVE")

        self.client.force_authenticate(user=user)
        response = self.client.post(LOGO_URL, {"logo": make_test_image()}, format="multipart")
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )

    def test_no_membership_patch_branding_returns_404_not_found(self):
        """Asserts user with no membership receives 404 NOT_FOUND on PATCH /workspace/branding."""
        user = self._create_user(email="nomem.branding@example.com")
        self._create_membership(role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=user)
        response = self.client.patch(
            BRANDING_URL,
            {"brand_color": "#111111"},
            format="json",
        )
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )

    def test_inactive_membership_patch_branding_returns_404_not_found(self):
        """Asserts user with INACTIVE membership gets 404 NOT_FOUND on PATCH /workspace/branding."""
        user = self._create_user(email="inactive.branding@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=user, workspace=workspace, role="OWNER", status="INACTIVE")

        self.client.force_authenticate(user=user)
        response = self.client.patch(
            BRANDING_URL,
            {"brand_color": "#111111"},
            format="json",
        )
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )

    def test_suspended_workspace_patch_branding_returns_404_not_found(self):
        """Asserts owner of SUSPENDED workspace receives 404 NOT_FOUND on PATCH /workspace/brand."""
        user = self._create_user(email="suspended.branding@example.com")
        workspace = self._create_workspace(status="SUSPENDED")
        self._create_membership(user=user, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=user)
        response = self.client.patch(
            BRANDING_URL,
            {"brand_color": "#111111"},
            format="json",
        )
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )

    def test_client_only_membership_patch_branding_returns_404_not_found(self):
        """Asserts user with only CLIENT membership gets 404 on PATCH /workspace/branding."""
        user = self._create_user(email="client.branding@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=user, workspace=workspace, role="CLIENT", status="ACTIVE")

        self.client.force_authenticate(user=user)
        response = self.client.patch(
            BRANDING_URL,
            {"brand_color": "#111111"},
            format="json",
        )
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )

    def test_four_non_qualifying_scenarios_post_logo_are_strictly_indistinguishable(self):
        """Asserts POST /logo responses across 4 non-qualifying cases are identical to each othe."""
        # 1. No membership
        user_no_mem = self._create_user(email="indist.nomem.logo@example.com")

        # 2. Inactive membership
        user_inactive = self._create_user(email="indist.inactive.logo@example.com")
        ws_inactive = self._create_workspace()
        self._create_membership(
            user=user_inactive, workspace=ws_inactive, role="OWNER", status="INACTIVE"
        )

        # 3. Suspended workspace
        user_suspended = self._create_user(email="indist.suspended.logo@example.com")
        ws_suspended = self._create_workspace(status="SUSPENDED")
        self._create_membership(
            user=user_suspended, workspace=ws_suspended, role="OWNER", status="ACTIVE"
        )

        # 4. Client-only membership
        user_client = self._create_user(email="indist.client.logo@example.com")
        ws_client = self._create_workspace()
        self._create_membership(
            user=user_client, workspace=ws_client, role="CLIENT", status="ACTIVE"
        )

        # Collect real responses
        self.client.force_authenticate(user=user_no_mem)
        res_no_mem = self.client.post(LOGO_URL, {"logo": make_test_image()}, format="multipart")

        self.client.force_authenticate(user=user_inactive)
        res_inactive = self.client.post(LOGO_URL, {"logo": make_test_image()}, format="multipart")

        self.client.force_authenticate(user=user_suspended)
        res_suspended = self.client.post(LOGO_URL, {"logo": make_test_image()}, format="multipart")

        self.client.force_authenticate(user=user_client)
        res_client = self.client.post(LOGO_URL, {"logo": make_test_image()}, format="multipart")

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

    def test_four_non_qualifying_scenarios_patch_branding_are_strictly_indistinguishable(self):
        """Asserts PATCH /branding responses across all 4 non-qualifying cases are identical."""
        # 1. No membership
        user_no_mem = self._create_user(email="indist.nomem.brand@example.com")

        # 2. Inactive membership
        user_inactive = self._create_user(email="indist.inactive.brand@example.com")
        ws_inactive = self._create_workspace()
        self._create_membership(
            user=user_inactive, workspace=ws_inactive, role="OWNER", status="INACTIVE"
        )

        # 3. Suspended workspace
        user_suspended = self._create_user(email="indist.suspended.brand@example.com")
        ws_suspended = self._create_workspace(status="SUSPENDED")
        self._create_membership(
            user=user_suspended, workspace=ws_suspended, role="OWNER", status="ACTIVE"
        )

        # 4. Client-only membership
        user_client = self._create_user(email="indist.client.brand@example.com")
        ws_client = self._create_workspace()
        self._create_membership(
            user=user_client, workspace=ws_client, role="CLIENT", status="ACTIVE"
        )

        # Collect real responses
        self.client.force_authenticate(user=user_no_mem)
        res_no_mem = self.client.patch(BRANDING_URL, {"brand_color": "#111111"}, format="json")

        self.client.force_authenticate(user=user_inactive)
        res_inactive = self.client.patch(BRANDING_URL, {"brand_color": "#111111"}, format="json")

        self.client.force_authenticate(user=user_suspended)
        res_suspended = self.client.patch(BRANDING_URL, {"brand_color": "#111111"}, format="json")

        self.client.force_authenticate(user=user_client)
        res_client = self.client.patch(BRANDING_URL, {"brand_color": "#111111"}, format="json")

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


class WorkspaceLogoUploadEndpointTests(BaseWorkspaceBrandingApiTestCase):
    """Verifies POST /workspace/logo shape, storage, WebP conversion, resizing, and thumbnails."""

    def test_post_logo_response_shape_exactly_one_key(self):
        """Asserts POST /workspace/logo returns exactly {"logo": "<url>"} on success."""
        owner = self._create_user(email="logo.shape@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        image_file = make_test_image(filename="gym_logo.png")
        response = self.client.post(LOGO_URL, {"logo": image_file}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(
            set(data.keys()),
            EXPECTED_LOGO_KEYS,
            "Response body must contain exactly the single key 'logo'.",
        )
        self.assertIsInstance(data["logo"], str)
        self.assertTrue(len(data["logo"]) > 0)

    def test_post_logo_persists_non_empty_file_field_in_database(self):
        """Asserts uploading a logo populates the Workspace.logo FileField in the database."""
        owner = self._create_user(email="logo.persist@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        image_file = make_test_image(filename="gym_logo.png")
        response = self.client.post(LOGO_URL, {"logo": image_file}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        workspace.refresh_from_db()
        self.assertTrue(bool(workspace.logo), "Workspace logo FileField must be populated.")
        self.assertTrue(len(workspace.logo.name) > 0)

    def test_post_logo_converts_image_to_webp_format_and_extension(self):
        """Asserts uploaded PNG is converted to WebP with .webp extension and format == 'WEBP'."""
        owner = self._create_user(email="logo.webp@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        png_file = make_test_image(width=500, height=300, image_format="PNG", filename="sample.png")
        response = self.client.post(LOGO_URL, {"logo": png_file}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        workspace.refresh_from_db()
        self.assertTrue(
            workspace.logo.name.endswith(".webp"),
            f"Stored filename must end with '.webp', got: '{workspace.logo.name}'.",
        )

        # Read stored bytes back with PIL to verify actual binary format is WEBP
        with workspace.logo.open("rb") as stored_file:
            with Image.open(stored_file) as img:
                self.assertEqual(
                    img.format,
                    "WEBP",
                    f"Stored image format must be 'WEBP', got '{img.format}'.",
                )

    def test_post_logo_resizes_image_wider_than_1600px(self):
        """Asserts image wider than 1600px is resized to width <= 1600 with preserved aspect rat."""
        owner = self._create_user(email="logo.resize@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        wide_image = make_test_image(width=2000, height=1200, filename="wide_banner.png")
        response = self.client.post(LOGO_URL, {"logo": wide_image}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        workspace.refresh_from_db()
        with workspace.logo.open("rb") as stored_file:
            with Image.open(stored_file) as img:
                self.assertLessEqual(
                    img.width,
                    1600,
                    f"Processed image width must be <= 1600px, got {img.width}px.",
                )
                self.assertEqual(
                    img.width,
                    1600,
                    f"Processed image width must be scaled down to 1600px, got {img.width}px.",
                )
                # Aspect ratio 2000:1200 (5:3) -> 1600:960
                self.assertAlmostEqual(
                    img.height,
                    960,
                    delta=2,
                    msg=f"Aspect ratio must be preserved; expected height ~960, got {img.height}.",
                )

    def test_post_logo_does_not_upscale_image_narrower_than_1600px(self):
        """Asserts image narrower than 1600px (800x600) is not upscaled."""
        owner = self._create_user(email="logo.noupscale@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        narrow_image = make_test_image(width=800, height=600, filename="small_logo.png")
        response = self.client.post(LOGO_URL, {"logo": narrow_image}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        workspace.refresh_from_db()
        with workspace.logo.open("rb") as stored_file:
            with Image.open(stored_file) as img:
                self.assertEqual(
                    img.width,
                    800,
                    f"Narrower image must not be upscaled; expected width 800, got {img.width}.",
                )
                self.assertEqual(
                    img.height,
                    600,
                    f"Narrower image height must remain 600, got {img.height}.",
                )

    def test_post_logo_generates_thumbnail(self):
        """Asserts a thumbnail is generated at width 400px upon logo upload."""
        owner = self._create_user(email="logo.thumb@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        image_file = make_test_image(width=2000, height=1200, filename="banner.png")
        response = self.client.post(LOGO_URL, {"logo": image_file}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        workspace.refresh_from_db()
        self.assertTrue(bool(workspace.logo), "Workspace logo must be saved.")

        # Discover files written to isolated MEDIA_ROOT
        media_files = []
        for root, _, files in os.walk(self.temp_media_dir):
            for f in files:
                media_files.append(os.path.join(root, f))

        self.assertGreaterEqual(
            len(media_files),
            2,
            f"Expected at least 2 files in MEDIA_ROOT, found: {media_files}",
        )

        # Inspect thumbnail file if identifiable by naming convention
        thumb_candidates = [f for f in media_files if "thumb" in f.lower() or "400" in f.lower()]
        if thumb_candidates:
            with Image.open(thumb_candidates[0]) as thumb_img:
                self.assertEqual(
                    thumb_img.width,
                    400,
                    f"Thumbnail width must be 400px, got {thumb_img.width}px.",
                )
                # Aspect ratio 2000:1200 -> 400:240
                self.assertAlmostEqual(thumb_img.height, 240, delta=2)

    def test_post_logo_response_does_not_expose_raw_filesystem_path(self):
        """Asserts returned logo URL does not expose internal filesystem paths."""
        owner = self._create_user(email="logo.nopath@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        image_file = make_test_image(filename="path_check.png")
        response = self.client.post(LOGO_URL, {"logo": image_file}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        logo_url = response.json()["logo"]
        self.assertNotIn(
            self.temp_media_dir,
            logo_url,
            "Logo URL must not contain internal MEDIA_ROOT filesystem path.",
        )
        self.assertFalse(
            logo_url.startswith("/Users/"),
            "Logo URL must not start with local /Users/ path.",
        )
        self.assertFalse(
            logo_url.startswith("/private/"),
            "Logo URL must not start with /private/ system path.",
        )


class WorkspaceBrandingValidationTests(BaseWorkspaceBrandingApiTestCase):
    """Verifies file type, file size, and payload validation rules for logo and branding."""

    def test_post_logo_rejects_decodable_image_of_disallowed_type(self):
        """Locks the MIME allow-list, which the format cross-check alone does not cover.

        A non-image upload is already rejected because Pillow cannot decode it. An ICO file
        is genuinely decodable and its declared type matches its real format, so only the
        allow-list keeps it out. Without this test the allow-list could be deleted silently.
        """
        owner = self._create_user(email="ico.reject@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")
        self.client.force_authenticate(user=owner)

        buffer = io.BytesIO()
        Image.new("RGB", (64, 64), (10, 20, 30)).save(buffer, format="ICO")
        upload = SimpleUploadedFile("icon.ico", buffer.getvalue(), content_type="image/x-icon")

        response = self.client.post(LOGO_URL, {"logo": upload}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"]["code"], "UNSUPPORTED_FILE_TYPE")

        workspace.refresh_from_db()
        self.assertFalse(bool(workspace.logo), "A disallowed image type must not be stored.")

    def test_post_logo_unsupported_file_type_returns_400_unsupported_file_type(self):
        """Asserts non-image upload returns 400 UNSUPPORTED_FILE_TYPE without 'fields' dict."""
        owner = self._create_user(email="val.badmime.logo@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        text_file = make_non_image_file(filename="document.txt")
        response = self.client.post(LOGO_URL, {"logo": text_file}, format="multipart")
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_400_BAD_REQUEST,
            expected_code="UNSUPPORTED_FILE_TYPE",
        )
        workspace.refresh_from_db()
        self.assertFalse(
            bool(workspace.logo),
            "Workspace logo must remain empty after invalid MIME type upload.",
        )

    def test_post_logo_oversize_file_returns_400_file_too_large(self):
        """Asserts uploading a file > 10 MB returns 400 FILE_TOO_LARGE without 'fields' dict."""
        owner = self._create_user(email="val.oversize.logo@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        large_file = make_large_file(size_bytes=11 * 1024 * 1024, filename="huge.png")
        response = self.client.post(LOGO_URL, {"logo": large_file}, format="multipart")
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_400_BAD_REQUEST,
            expected_code="FILE_TOO_LARGE",
        )
        workspace.refresh_from_db()
        self.assertFalse(
            bool(workspace.logo),
            "Workspace logo must remain empty after oversize file upload attempt.",
        )

    def test_post_logo_missing_file_field_returns_400_validation_error(self):
        """Asserts omitting the 'logo' field on POST /workspace/logo returns 400 VALIDATION_ERRO."""
        owner = self._create_user(email="val.missing.logo@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        response = self.client.post(LOGO_URL, {}, format="multipart")
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_400_BAD_REQUEST,
            expected_code="VALIDATION_ERROR",
            expected_field="logo",
        )

    def test_patch_branding_unsupported_file_type_returns_400_unsupported_file_type(self):
        """Asserts non-image in branding upload returns 400 UNSUPPORTED_FILE_TYPE."""
        owner = self._create_user(email="val.badmime.branding@example.com")
        workspace = self._create_workspace(brand_color="#123456", description="Initial bio")
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        text_file = make_non_image_file(filename="bad_logo.txt")
        response = self.client.patch(
            BRANDING_URL,
            {"logo": text_file, "brand_color": "#654321"},
            format="multipart",
        )
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_400_BAD_REQUEST,
            expected_code="UNSUPPORTED_FILE_TYPE",
        )
        workspace.refresh_from_db()
        self.assertEqual(
            workspace.brand_color,
            "#123456",
            "Workspace attributes must remain unchanged after failed upload validation.",
        )
        self.assertFalse(bool(workspace.logo))

    def test_patch_branding_oversize_file_returns_400_file_too_large(self):
        """Asserts > 10 MB file on PATCH /branding returns 400 FILE_TOO_LARGE."""
        owner = self._create_user(email="val.oversize.branding@example.com")
        workspace = self._create_workspace(brand_color="#123456", description="Initial bio")
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        large_file = make_large_file(size_bytes=11 * 1024 * 1024, filename="huge_profile.png")
        response = self.client.patch(
            BRANDING_URL,
            {"profile_image": large_file},
            format="multipart",
        )
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_400_BAD_REQUEST,
            expected_code="FILE_TOO_LARGE",
        )
        workspace.refresh_from_db()
        self.assertFalse(bool(workspace.profile_image))


class WorkspaceBrandingEndpointTests(BaseWorkspaceBrandingApiTestCase):
    """Verifies PATCH /workspace/branding response shape, partial updates, and uploads."""

    def test_patch_branding_success_response_shape_exactly_four_keys(self):
        """Asserts PATCH /workspace/branding returns exactly 4 keys on success."""
        owner = self._create_user(email="branding.shape@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        response = self.client.patch(
            BRANDING_URL,
            {"brand_color": "#FF5733", "description": "Elite Strength Coaching"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(
            set(data.keys()),
            EXPECTED_BRANDING_KEYS,
            "PATCH /workspace/branding response must contain exactly the 4 documented keys.",
        )
        self.assertEqual(data["brand_color"], "#FF5733")
        self.assertEqual(data["description"], "Elite Strength Coaching")
        self.assertIsNone(data["logo"])
        self.assertIsNone(data["profile_image"])

        workspace.refresh_from_db()
        self.assertEqual(workspace.brand_color, "#FF5733")
        self.assertEqual(workspace.description, "Elite Strength Coaching")

    def test_patch_branding_partial_update_preserves_omitted_fields(self):
        """Asserts updating only brand_color leaves description and images unchanged."""
        owner = self._create_user(email="branding.partial@example.com")
        workspace = self._create_workspace(
            brand_color="#111111", description="Original description text"
        )
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        response = self.client.patch(
            BRANDING_URL,
            {"brand_color": "#336699"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["brand_color"], "#336699")
        self.assertEqual(data["description"], "Original description text")

        workspace.refresh_from_db()
        self.assertEqual(workspace.brand_color, "#336699")
        self.assertEqual(workspace.description, "Original description text")

    def test_patch_branding_unset_images_return_null(self):
        """Asserts logo and profile_image are null in the response when unset."""
        owner = self._create_user(email="branding.nulls@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        response = self.client.patch(
            BRANDING_URL,
            {"description": "Just updating description"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIsNone(data["logo"])
        self.assertIsNone(data["profile_image"])

    def test_patch_branding_with_logo_and_profile_image_uploads(self):
        """Asserts uploading logo and profile_image via PATCH /branding converts both to WebP."""
        owner = self._create_user(email="branding.uploads@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        logo_file = make_test_image(width=500, height=300, filename="patch_logo.png")
        profile_file = make_test_image(width=400, height=400, filename="patch_profile.png")

        response = self.client.patch(
            BRANDING_URL,
            {
                "logo": logo_file,
                "profile_image": profile_file,
                "brand_color": "#445566",
                "description": "Full branding update",
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(set(data.keys()), EXPECTED_BRANDING_KEYS)
        self.assertIsNotNone(data["logo"])
        self.assertIsNotNone(data["profile_image"])
        self.assertEqual(data["brand_color"], "#445566")
        self.assertEqual(data["description"], "Full branding update")

        workspace.refresh_from_db()
        self.assertTrue(workspace.logo.name.endswith(".webp"))
        self.assertTrue(workspace.profile_image.name.endswith(".webp"))

        with workspace.logo.open("rb") as f:
            with Image.open(f) as img:
                self.assertEqual(img.format, "WEBP")

        with workspace.profile_image.open("rb") as f:
            with Image.open(f) as img:
                self.assertEqual(img.format, "WEBP")

    def test_patch_branding_empty_payload_succeeds_and_preserves_values(self):
        """Asserts sending an empty payload returns 200 with unchanged data."""
        owner = self._create_user(email="branding.empty@example.com")
        workspace = self._create_workspace(
            brand_color="#ABCDEF", description="Existing preserved description"
        )
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        response = self.client.patch(BRANDING_URL, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(set(data.keys()), EXPECTED_BRANDING_KEYS)
        self.assertEqual(data["brand_color"], "#ABCDEF")
        self.assertEqual(data["description"], "Existing preserved description")

    def test_patch_branding_response_does_not_expose_raw_filesystem_path(self):
        """Asserts stored image URLs in response do not contain local filesystem paths."""
        owner = self._create_user(email="branding.nopath@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        logo_file = make_test_image(filename="nopath_logo.png")
        profile_file = make_test_image(filename="nopath_profile.png")

        response = self.client.patch(
            BRANDING_URL,
            {"logo": logo_file, "profile_image": profile_file},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        for field in ["logo", "profile_image"]:
            val = data[field]
            self.assertIsNotNone(val)
            self.assertNotIn(self.temp_media_dir, val)
            self.assertFalse(val.startswith("/Users/"))
            self.assertFalse(val.startswith("/private/"))


class WorkspaceBrandingRateLimitingTests(BaseWorkspaceBrandingApiTestCase):
    """Verifies ScopedRateThrottle enforcement (20/hour) on logo upload and branding endpoints."""

    def test_logo_upload_throttled_at_21st_request_per_hour(self):
        """Asserts workspace_logo_upload allows 20 uploads/hour and returns 429 on the 21st."""
        owner = self._create_user(email="throttle.logo@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)

        for i in range(20):
            file_payload = make_test_image(width=10, height=10, filename=f"tiny_{i}.png")
            response = self.client.post(LOGO_URL, {"logo": file_payload}, format="multipart")
            self.assertEqual(
                response.status_code,
                status.HTTP_200_OK,
                f"Upload {i + 1} within the 20/hour rate limit must succeed with 200.",
            )

        # 21st request must be throttled with 429 RATE_LIMITED
        file_payload = make_test_image(width=10, height=10, filename="tiny_21.png")
        throttled_response = self.client.post(LOGO_URL, {"logo": file_payload}, format="multipart")
        self.assert_error_envelope(
            throttled_response,
            expected_status=status.HTTP_429_TOO_MANY_REQUESTS,
            expected_code="RATE_LIMITED",
        )

    def test_branding_patch_shares_rate_limit_scope(self):
        """Asserts PATCH /workspace/branding enforces the workspace_logo_upload throttle scope."""
        owner = self._create_user(email="throttle.branding@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)

        for i in range(20):
            file_payload = make_test_image(width=10, height=10, filename=f"logo_{i}.png")
            response = self.client.patch(
                BRANDING_URL,
                {"logo": file_payload},
                format="multipart",
            )
            self.assertEqual(
                response.status_code,
                status.HTTP_200_OK,
                f"Branding patch upload {i + 1} within limit must succeed with 200.",
            )

        # 21st request must be throttled
        file_payload = make_test_image(width=10, height=10, filename="logo_21.png")
        throttled_response = self.client.patch(
            BRANDING_URL,
            {"logo": file_payload},
            format="multipart",
        )
        self.assert_error_envelope(
            throttled_response,
            expected_status=status.HTTP_429_TOO_MANY_REQUESTS,
            expected_code="RATE_LIMITED",
        )

    def test_unrelated_workspace_endpoint_not_throttled_by_logo_upload_scope(self):
        """Asserts GET /api/v1/workspace is not affected when workspace_logo_upload is exhausted."""
        owner = self._create_user(email="throttle.isolation@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)

        for i in range(20):
            file_payload = make_test_image(width=10, height=10, filename=f"tiny_{i}.png")
            self.client.post(LOGO_URL, {"logo": file_payload}, format="multipart")

        # Confirm uploads are throttled
        file_payload = make_test_image(width=10, height=10, filename="extra.png")
        throttled = self.client.post(LOGO_URL, {"logo": file_payload}, format="multipart")
        self.assertEqual(throttled.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

        # Unrelated GET /api/v1/workspace must succeed without being throttled
        get_response = self.client.get(WORKSPACE_URL)
        self.assertEqual(
            get_response.status_code,
            status.HTTP_200_OK,
            "GET /api/v1/workspace must remain reachable (200) and not throttled by upload limit.",
        )


class WorkspaceBrandingContractPreservationAndArchitectureTests(BaseWorkspaceBrandingApiTestCase):
    """Guards Story 4.1/4.2 11-key contracts, disallowed HTTP methods."""

    def test_get_workspace_preserves_exact_eleven_keys_contract(self):
        """Contract preservation: GET /api/v1/workspace returns exactly the 11 established keys."""
        owner = self._create_user(email="guard.get@example.com")
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
            "logo",
            data,
            "logo must not be present in GET /api/v1/workspace response.",
        )
        self.assertNotIn(
            "profile_image",
            data,
            "profile_image must not be present in GET /api/v1/workspace response.",
        )

    def test_patch_workspace_preserves_exact_eleven_keys_contract(self):
        """Contract preservation."""
        owner = self._create_user(email="guard.patch@example.com")
        workspace = self._create_workspace(description="Guarded description", brand_color="#123456")
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        response = self.client.patch(
            WORKSPACE_URL,
            {"name": "Renamed Gym Workspace"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(
            set(data.keys()),
            EXPECTED_WORKSPACE_KEYS,
            "PATCH /api/v1/workspace response keys must be exactly the 11 established keys.",
        )
        self.assertNotIn(
            "logo",
            data,
            "logo must not be present in PATCH /api/v1/workspace response.",
        )
        self.assertNotIn(
            "profile_image",
            data,
            "profile_image must not be present in PATCH /api/v1/workspace response.",
        )

    def test_workspaces_app_exposes_only_workspace_model(self):
        """Asserts the workspaces app defines exactly {'Workspace'} and no premature models."""
        workspaces_app = apps.get_app_config("workspaces")
        concrete_model_names = {model._meta.object_name for model in workspaces_app.get_models()}
        self.assertEqual(
            concrete_model_names,
            {"Workspace"},
            "workspaces app must expose only {'Workspace'}.",
        )

    def test_billing_app_exposes_no_models(self):
        """Guards Epic 22 boundary: billing app must define zero models in Story 4.3."""
        billing_app = apps.get_app_config("billing")
        concrete_model_names = {model._meta.object_name for model in billing_app.get_models()}
        self.assertEqual(
            concrete_model_names,
            set(),
            "billing app must expose no models (deferred to Epic 22).",
        )

    def test_disallowed_http_methods_on_logo_and_branding_return_405(self):
        """Asserts disallowed HTTP methods on /logo and /branding return 405 Method Not Allowed."""
        owner = self._create_user(email="methods.guard@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)

        # Disallowed methods on LOGO_URL (only POST is allowed)
        for method in ["get", "put", "patch", "delete"]:
            with self.subTest(endpoint=LOGO_URL, http_method=method):
                client_method = getattr(self.client, method)
                response = client_method(LOGO_URL)
                self.assertEqual(
                    response.status_code,
                    status.HTTP_405_METHOD_NOT_ALLOWED,
                    f"HTTP {method.upper()} to {LOGO_URL} must return 405 Method Not Allowed.",
                )

        # Disallowed methods on BRANDING_URL (only PATCH is allowed)
        for method in ["get", "post", "put", "delete"]:
            with self.subTest(endpoint=BRANDING_URL, http_method=method):
                client_method = getattr(self.client, method)
                response = client_method(BRANDING_URL)
                self.assertEqual(
                    response.status_code,
                    status.HTTP_405_METHOD_NOT_ALLOWED,
                    f"HTTP {method.upper()} to {BRANDING_URL} must return 405 Method Not Allowed.",
                )
