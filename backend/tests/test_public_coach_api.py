"""API tests for Public Coach Page endpoint (Story 6.1).

Validates:
- Method handling: GET only; POST, PATCH, PUT, and DELETE yield 405 Method Not Allowed (Point 14)
- Anonymous access: completely unauthenticated GET returns 200 OK, never 401 or 403 (Point 1)
- Top-level response shape: exactly the three keys {"workspace", "coach", "packages"} (Point 2)
- Workspace public fields: exactly seven keys (name, slug, description, brand_color, logo,
  profile_image, whatsapp_number); internal/sensitive fields (id, status, currency, timezone,
  created_at, updated_at) are absent; workspace UUID never leaks in response text (Point 3)
- Coach public fields: exactly four keys (bio, profile_image, website_url, instagram_url)
  (Point 4)
- Hard security boundary: no User model fields (email, first/last name, phone, user UUID,
  platform_role) ever leak into coach object or raw response text (Point 5)
- Missing profile handling: returns 200 with "coach": null when owner has no CoachProfile or
  workspace has no active owner; never 404 or 500 (Point 6)
- Workspace owner role selection: coach profile belongs strictly to the ACTIVE OWNER, never a
  COACH or CLIENT member; inactive owner membership returns "coach": null (Point 7)
- Package scoping & cross-tenant isolation: packages contains only ACTIVE packages of target
  workspace; inactive packages and foreign tenant packages are excluded (Point 8)
- Package object shape: each package exposes exactly ten documented keys; workspace and
  workspace_id are absent from parsed dictionary and response body (Point 9)
- Empty package list: workspace with no active packages returns 200 with "packages": []
  (Point 10)
- Unpaginated composite structure: packages is a plain JSON list; count, next, previous, and
  results do not exist at top level (Point 11)
- Suspended workspace invisibility & anti-enumeration: SUSPENDED workspace returns 404 NOT_FOUND
  and is byte-identical to a non-existent slug response, never 403 (Point 12)
- API §2 error envelope: 404 responses contain exactly {"error"} with code == "NOT_FOUND" and
  no "fields" dictionary (Point 13)
- Authentication neutrality: authenticated unaffiliated callers and workspace owners receive
  byte-identical 200 responses to anonymous visitors (Point 15)
- Image fields & media safety: logo and profile_image return null when unset; when set, safe URL
  strings without local filesystem paths (Point 16)
- Architecture guards: coaching exposes only {"Package"}, billing defines no models, workspaces
  defines {"Workspace", "PaymentMethod"}
"""

import io
import os
import shutil
import tempfile
import uuid
from decimal import Decimal

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient

PUBLIC_COACHES_URL = "/api/v1/public/coaches"

TOP_LEVEL_KEYS = {"workspace", "coach", "packages"}

EXPECTED_WORKSPACE_KEYS = {
    "name",
    "slug",
    "description",
    "brand_color",
    "logo",
    "profile_image",
    "whatsapp_number",
}

FORBIDDEN_WORKSPACE_KEYS = {
    "id",
    "status",
    "currency",
    "timezone",
    "created_at",
    "updated_at",
}

EXPECTED_COACH_KEYS = {
    "bio",
    "profile_image",
    "website_url",
    "instagram_url",
}

FORBIDDEN_USER_KEYS = {
    "id",
    "email",
    "first_name",
    "last_name",
    "phone",
    "platform_role",
    "password",
    "is_active",
    "email_verified_at",
}

EXPECTED_PACKAGE_KEYS = {
    "id",
    "name",
    "description",
    "price",
    "currency",
    "duration_days",
    "features",
    "is_active",
    "created_at",
    "updated_at",
}

FORBIDDEN_PACKAGE_KEYS = {
    "workspace",
    "workspace_id",
}


def public_coach_url(slug: str) -> str:
    """Returns the public coach page URL for a given workspace slug."""
    return f"{PUBLIC_COACHES_URL}/{slug}"


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


class BasePublicCoachApiTestCase(TestCase):
    """Base case providing client setup, cache reset, media isolation, and factories."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.client = APIClient()
        self.user_model = get_user_model()
        self.workspace_model = apps.get_model("workspaces", "Workspace")
        self.membership_model = apps.get_model("accounts", "Membership")
        self.coach_profile_model = apps.get_model("accounts", "CoachProfile")
        self.package_model = apps.get_model("coaching", "Package")

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
        """Creates and returns an email-verified user."""
        if email is None:
            email = f"user-{uuid.uuid4().hex[:8]}@example.com"
        kwargs.setdefault("email_verified_at", timezone.now())
        return self.user_model.objects.create_user(email=email, password=password, **kwargs)

    def _create_workspace(self, name=None, slug=None, **kwargs):
        """Creates and returns a Workspace."""
        unique_id = uuid.uuid4().hex[:8]
        if name is None:
            name = f"Workspace {unique_id}"
        if slug is None:
            slug = f"workspace-{unique_id}"
        defaults = {
            "name": name,
            "slug": slug,
            "description": "Premium fitness coaching and workout programs.",
            "brand_color": "#1A2B3C",
            "currency": "USD",
            "timezone": "UTC",
            "whatsapp_number": "+1234567890",
            "status": "ACTIVE",
        }
        defaults.update(kwargs)
        return self.workspace_model.objects.create(**defaults)

    def _create_membership(
        self, user=None, workspace=None, role="OWNER", status="ACTIVE", **kwargs
    ):
        """Creates and returns a Membership."""
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

    def _create_coach_profile(self, user=None, **kwargs):
        """Creates and returns a CoachProfile."""
        if user is None:
            user = self._create_user()
        defaults = {
            "user": user,
            "bio": "Certified strength & conditioning specialist with 10+ years experience.",
            "website_url": "https://example.com/coach",
            "instagram_url": "https://instagram.com/coach_example",
        }
        defaults.update(kwargs)
        return self.coach_profile_model.objects.create(**defaults)

    def _create_package(self, workspace=None, is_active=True, **kwargs):
        """Creates and returns a Package."""
        if workspace is None:
            workspace = self._create_workspace()
        unique_id = uuid.uuid4().hex[:8]
        defaults = {
            "workspace": workspace,
            "name": f"Pro Coaching {unique_id}",
            "description": "Comprehensive personalized training and nutrition plan.",
            "price": Decimal("2500.00"),
            "currency": "USD",
            "duration_days": 60,
            "features": ["Personalized Workout Plan", "Weekly Check-ins", "Dietary Guidance"],
            "is_active": is_active,
        }
        defaults.update(kwargs)
        return self.package_model.objects.create(**defaults)

    def _setup_public_workspace(
        self,
        workspace_kwargs=None,
        user_kwargs=None,
        coach_profile_kwargs=None,
        package_count=2,
    ):
        """Helper to create a public workspace with owner, profile, and active packages."""
        u_kwargs = user_kwargs or {}
        owner = self._create_user(**u_kwargs)

        w_kwargs = workspace_kwargs or {}
        workspace = self._create_workspace(**w_kwargs)

        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        cp_kwargs = coach_profile_kwargs or {}
        coach_profile = self._create_coach_profile(user=owner, **cp_kwargs)

        packages = []
        for _ in range(package_count):
            packages.append(self._create_package(workspace=workspace, is_active=True))

        return owner, workspace, coach_profile, packages

    def assert_error_envelope(self, response, expected_status, expected_code=None):
        """Asserts the API §2 error envelope; fields is only present for VALIDATION_ERROR."""
        self.assertEqual(response.status_code, expected_status)
        data = response.json()
        self.assertEqual(set(data.keys()), {"error"})
        error = data["error"]
        self.assertIsInstance(error, dict)
        if expected_code is not None:
            self.assertEqual(error.get("code"), expected_code)
        self.assertIsInstance(error.get("message"), str)
        if expected_code != "VALIDATION_ERROR":
            self.assertNotIn("fields", error)


class PublicCoachAnonymousAccessTests(BasePublicCoachApiTestCase):
    """Verifies anonymous access succeeds on public coach endpoint (Point 1)."""

    def test_anonymous_get_public_coach_returns_200_ok(self):
        """Asserts an unauthenticated GET request returns 200 OK."""
        _, workspace, _, _ = self._setup_public_workspace()
        response = self.client.get(public_coach_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_anonymous_access_never_requires_authentication(self):
        """Guards the public boundary: unauthenticated requests must never 401 or 403.

        This is the first fully public endpoint in the codebase. Any requirement for auth tokens,
        session cookies, or workspace headers would break the public coach page.
        """
        _, workspace, _, _ = self._setup_public_workspace()
        self.client.credentials()
        self.client.logout()
        response = self.client.get(public_coach_url(workspace.slug))
        self.assertNotEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
            "Public endpoint must not return 401 Unauthorized for anonymous callers.",
        )
        self.assertNotEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
            "Public endpoint must not return 403 Forbidden for anonymous callers.",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class PublicCoachResponseTopLevelShapeTests(BasePublicCoachApiTestCase):
    """Verifies top-level response shape and unpaginated structure (Points 2 & 11)."""

    def test_response_top_level_contains_exact_three_keys(self):
        """Asserts response body has exactly the key set {'workspace', 'coach', 'packages'}."""
        _, workspace, _, _ = self._setup_public_workspace()
        response = self.client.get(public_coach_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(
            set(data.keys()),
            TOP_LEVEL_KEYS,
            "Top-level keys must equal exactly {'workspace', 'coach', 'packages'}.",
        )

    def test_response_is_not_paginated_and_packages_is_plain_list(self):
        """Asserts response is unpaginated: packages is a list and no pagination keys exist."""
        _, workspace, _, _ = self._setup_public_workspace(package_count=3)
        response = self.client.get(public_coach_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertIsInstance(data["packages"], list)
        self.assertEqual(len(data["packages"]), 3)

        for forbidden_key in ("count", "next", "previous", "results"):
            with self.subTest(forbidden_key=forbidden_key):
                self.assertNotIn(
                    forbidden_key,
                    data,
                    f"Pagination key '{forbidden_key}' must not appear in composed response.",
                )


class PublicCoachWorkspaceExposedFieldsTests(BasePublicCoachApiTestCase):
    """Verifies workspace field exposure, exclusions, and UUID security (Point 3)."""

    def test_workspace_object_contains_exact_seven_keys(self):
        """Asserts workspace object exposes exactly the seven documented public keys."""
        _, workspace, _, _ = self._setup_public_workspace()
        response = self.client.get(public_coach_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("workspace", data)
        self.assertIsInstance(data["workspace"], dict)
        self.assertEqual(
            set(data["workspace"].keys()),
            EXPECTED_WORKSPACE_KEYS,
            f"Workspace object must expose exactly {EXPECTED_WORKSPACE_KEYS}.",
        )

    def test_workspace_internal_and_sensitive_fields_are_absent(self):
        """Asserts id, status, currency, timezone, created_at, updated_at are not in workspace."""
        _, workspace, _, _ = self._setup_public_workspace()
        response = self.client.get(public_coach_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ws_data = response.json()["workspace"]
        for field in FORBIDDEN_WORKSPACE_KEYS:
            with self.subTest(field=field):
                self.assertNotIn(
                    field,
                    ws_data,
                    f"Internal/sensitive field '{field}' must not be exposed in workspace.",
                )

    def test_workspace_uuid_does_not_appear_in_raw_response_text(self):
        """Asserts the workspace's internal UUID string is nowhere in raw response body."""
        _, workspace, _, _ = self._setup_public_workspace()
        response = self.client.get(public_coach_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        raw_text = response.content.decode()
        self.assertNotIn(
            str(workspace.id),
            raw_text,
            "Workspace UUID must not leak into the public response body text.",
        )

    def test_workspace_field_values_match_database_state(self):
        """Asserts exposed workspace fields match stored values in the database."""
        _, workspace, _, _ = self._setup_public_workspace(
            workspace_kwargs={
                "name": "Olympia Fitness Hub",
                "slug": "olympia-fitness-hub",
                "description": "Elite conditioning and powerlifting facility.",
                "brand_color": "#FF4500",
                "whatsapp_number": "+201001234567",
            }
        )
        response = self.client.get(public_coach_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ws_data = response.json()["workspace"]
        self.assertEqual(ws_data["name"], "Olympia Fitness Hub")
        self.assertEqual(ws_data["slug"], "olympia-fitness-hub")
        self.assertEqual(ws_data["description"], "Elite conditioning and powerlifting facility.")
        self.assertEqual(ws_data["brand_color"], "#FF4500")
        self.assertEqual(ws_data["whatsapp_number"], "+201001234567")


class PublicCoachExposedFieldsTests(BasePublicCoachApiTestCase):
    """Verifies coach object public keys and field values (Point 4)."""

    def test_coach_object_contains_exact_four_keys(self):
        """Asserts coach object exposes exactly the four documented keys."""
        _, workspace, _, _ = self._setup_public_workspace()
        response = self.client.get(public_coach_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("coach", data)
        self.assertIsInstance(data["coach"], dict)
        self.assertEqual(
            set(data["coach"].keys()),
            EXPECTED_COACH_KEYS,
            f"Coach object must expose exactly {EXPECTED_COACH_KEYS}.",
        )

    def test_coach_field_values_match_database_state(self):
        """Asserts exposed coach fields match the coach profile values in the database."""
        _, workspace, _, _ = self._setup_public_workspace(
            coach_profile_kwargs={
                "bio": "Former Olympic athlete turned elite strength coach.",
                "website_url": "https://olympiacoach.com",
                "instagram_url": "https://instagram.com/olympiacoach",
            }
        )
        response = self.client.get(public_coach_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        coach_data = response.json()["coach"]
        self.assertEqual(coach_data["bio"], "Former Olympic athlete turned elite strength coach.")
        self.assertEqual(coach_data["website_url"], "https://olympiacoach.com")
        self.assertEqual(coach_data["instagram_url"], "https://instagram.com/olympiacoach")


class PublicCoachUserSecurityBoundaryTests(BasePublicCoachApiTestCase):
    """Verifies hard security boundary: no User model fields or PII are exposed (Point 5)."""

    def test_user_personal_data_and_uuid_are_never_leaked_in_response(self):
        """Guards hard security boundary: owner User fields and UUID must never leak.

        Public coach pages expose the CoachProfile (bio, links, image) and Workspace branding.
        Under no circumstances should the underlying User entity (email, first/last names,
        phone, password hash, user ID, platform role) appear in the API output.
        """
        distinctive_email = f"secret-owner-{uuid.uuid4().hex[:6]}@classified-domain.org"
        distinctive_first = "DistinctiveOwnerFirstName"
        distinctive_last = "DistinctiveOwnerLastName"
        distinctive_phone = "+999123456789"

        owner, workspace, _, _ = self._setup_public_workspace(
            user_kwargs={
                "email": distinctive_email,
                "first_name": distinctive_first,
                "last_name": distinctive_last,
                "phone": distinctive_phone,
            }
        )

        response = self.client.get(public_coach_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        raw_text = response.content.decode()

        self.assertNotIn(distinctive_email, raw_text, "User email leaked in response body.")
        self.assertNotIn(distinctive_first, raw_text, "User first_name leaked in response body.")
        self.assertNotIn(distinctive_last, raw_text, "User last_name leaked in response body.")
        self.assertNotIn(distinctive_phone, raw_text, "User phone leaked in response body.")
        self.assertNotIn(str(owner.id), raw_text, "User UUID leaked in response body.")

    def test_coach_object_does_not_contain_user_model_fields(self):
        """Asserts user fields (email, names, phone, id, platform_role) are absent from coach."""
        _, workspace, _, _ = self._setup_public_workspace()
        response = self.client.get(public_coach_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        coach_data = response.json()["coach"]

        for user_key in FORBIDDEN_USER_KEYS:
            with self.subTest(user_key=user_key):
                self.assertNotIn(
                    user_key,
                    coach_data,
                    f"User model field '{user_key}' must not be present in coach object.",
                )


class PublicCoachMissingProfileTests(BasePublicCoachApiTestCase):
    """Verifies coach is null when profile or active owner membership is absent (Point 6)."""

    def test_active_owner_without_coach_profile_returns_200_with_coach_null(self):
        """Asserts 200 OK with 'coach': null when owner has no CoachProfile row (Point 6a)."""
        owner = self._create_user()
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")
        self._create_package(workspace=workspace, is_active=True)

        self.assertFalse(self.coach_profile_model.objects.filter(user=owner).exists())

        response = self.client.get(public_coach_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(set(data.keys()), TOP_LEVEL_KEYS)
        self.assertIsNone(data["coach"], "Coach must be null when Owner has no CoachProfile.")
        self.assertEqual(set(data["workspace"].keys()), EXPECTED_WORKSPACE_KEYS)
        self.assertEqual(len(data["packages"]), 1)

    def test_workspace_without_active_owner_membership_returns_200_with_coach_null(self):
        """Asserts 200 OK with 'coach': null when workspace has no active OWNER (Point 6b)."""
        workspace = self._create_workspace()
        self._create_package(workspace=workspace, is_active=True)

        self.assertEqual(self.membership_model.objects.filter(workspace=workspace).count(), 0)

        response = self.client.get(public_coach_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(set(data.keys()), TOP_LEVEL_KEYS)
        self.assertIsNone(data["coach"], "Coach must be null when workspace has no active OWNER.")
        self.assertEqual(set(data["workspace"].keys()), EXPECTED_WORKSPACE_KEYS)
        self.assertEqual(len(data["packages"]), 1)

    def test_missing_coach_profile_does_not_404_or_500(self):
        """Guards resilience: workspace without coach profile must not return 404 or 500.

        The workspace and its packages remain publicly discoverable even if the coach
        has not yet filled out their personal bio/profile.
        """
        workspace = self._create_workspace()
        response = self.client.get(public_coach_url(workspace.slug))
        self.assertNotIn(
            response.status_code,
            [status.HTTP_404_NOT_FOUND, status.HTTP_500_INTERNAL_SERVER_ERROR],
            "Missing coach profile must not result in 404 or 500 error.",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class PublicCoachRoleSelectionTests(BasePublicCoachApiTestCase):
    """Verifies that coach profile shown belongs strictly to the ACTIVE OWNER (Point 7)."""

    def test_only_active_owner_coach_profile_is_exposed_not_coach_or_client(self):
        """Guards role selection: only ACTIVE OWNER bio is returned, never COACH or CLIENT.

        In a multi-user workspace with multiple coaches and clients who also have CoachProfile
        records, the public page represents the workspace business owner. Coach or client
        profiles must not overwrite or leak into the public coach page.
        """
        workspace = self._create_workspace()

        # The COACH and CLIENT memberships are created BEFORE the OWNER on purpose. The view
        # picks one membership with .first() on an unordered queryset, so if the role filter
        # were ever dropped, insertion order would return the COACH here and this test would
        # fail loudly. Creating the OWNER first would let insertion order mask that bug.
        coach_user = self._create_user(email="coach-role-test@example.com")
        self._create_membership(user=coach_user, workspace=workspace, role="COACH", status="ACTIVE")
        coach_bio = "UNAUTHORIZED_COACH_MEMBER_BIO_KEY_456"
        self._create_coach_profile(user=coach_user, bio=coach_bio)

        client_user = self._create_user(email="client-role-test@example.com")
        self._create_membership(
            user=client_user, workspace=workspace, role="CLIENT", status="ACTIVE"
        )
        client_bio = "UNAUTHORIZED_CLIENT_MEMBER_BIO_KEY_789"
        self._create_coach_profile(user=client_user, bio=client_bio)

        owner_user = self._create_user(email="owner-role-test@example.com")
        self._create_membership(user=owner_user, workspace=workspace, role="OWNER", status="ACTIVE")
        owner_bio = "THE_GENUINE_OWNER_COACH_BIO_KEY_123"
        self._create_coach_profile(user=owner_user, bio=owner_bio)

        response = self.client.get(public_coach_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertIsNotNone(data["coach"])
        self.assertEqual(data["coach"]["bio"], owner_bio)

        raw_text = response.content.decode()
        self.assertNotIn(
            coach_bio,
            raw_text,
            "COACH member's bio must not appear in the public coach response.",
        )
        self.assertNotIn(
            client_bio,
            raw_text,
            "CLIENT member's bio must not appear in the public coach response.",
        )

    def test_earliest_active_owner_is_chosen_deterministically(self):
        """Guards determinism: with two ACTIVE OWNERs the earliest-joined one is always shown.

        Nothing in the schema forbids a workspace having two ACTIVE OWNER memberships —
        Membership is unique on (user, workspace), not on (workspace, role). Without an
        explicit ordering the view would return an arbitrary row, so the public page could
        show a different coach from one request to the next. This pins the earliest owner.
        """
        workspace = self._create_workspace()

        first_owner = self._create_user(email="first-owner@example.com")
        self._create_membership(user=first_owner, workspace=workspace, role="OWNER")
        first_bio = "FIRST_OWNER_BIO_MUST_WIN_111"
        self._create_coach_profile(user=first_owner, bio=first_bio)

        second_owner = self._create_user(email="second-owner@example.com")
        self._create_membership(user=second_owner, workspace=workspace, role="OWNER")
        second_bio = "SECOND_OWNER_BIO_MUST_LOSE_222"
        self._create_coach_profile(user=second_owner, bio=second_bio)

        for _ in range(3):
            response = self.client.get(public_coach_url(workspace.slug))
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.json()["coach"]["bio"], first_bio)
            self.assertNotIn(second_bio, response.content.decode())

    def test_inactive_owner_coach_profile_is_not_exposed(self):
        """Asserts an INACTIVE OWNER membership does not expose its coach profile."""
        workspace = self._create_workspace()
        inactive_owner = self._create_user(email="inactive-owner@example.com")
        self._create_membership(
            user=inactive_owner, workspace=workspace, role="OWNER", status="INACTIVE"
        )
        self._create_coach_profile(
            user=inactive_owner, bio="Inactive owner profile that must remain hidden."
        )

        response = self.client.get(public_coach_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertIsNone(
            data["coach"],
            "Coach must be null when OWNER membership status is INACTIVE.",
        )
        self.assertNotIn(
            "Inactive owner profile that must remain hidden.",
            response.content.decode(),
        )


class PublicCoachPackageScopingAndCrossTenantTests(BasePublicCoachApiTestCase):
    """Verifies active package scoping, tenant isolation, and empty packages (Points 8 & 10)."""

    def test_packages_contains_only_active_packages_of_requested_workspace(self):
        """Guards cross-tenant isolation and active package filtering.

        Creates active and inactive packages in target workspace, plus active packages in
        another workspace, and asserts the response contains exactly the active packages
        of the target workspace.
        """
        # package_count=0 so the workspace holds only the packages this test creates, keeping
        # the strict set equality below meaningful rather than accidentally short by two.
        _, target_ws, _, _ = self._setup_public_workspace(package_count=0)
        other_ws = self._create_workspace()

        pkg_active_1 = self._create_package(
            workspace=target_ws, is_active=True, name="Target Pkg 1"
        )
        pkg_active_2 = self._create_package(
            workspace=target_ws, is_active=True, name="Target Pkg 2"
        )
        pkg_inactive = self._create_package(
            workspace=target_ws, is_active=False, name="Target Inactive Pkg"
        )

        pkg_foreign = self._create_package(workspace=other_ws, is_active=True, name="Foreign Pkg")

        response = self.client.get(public_coach_url(target_ws.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        returned_ids = {pkg["id"] for pkg in data["packages"]}
        expected_ids = {str(pkg_active_1.id), str(pkg_active_2.id)}

        self.assertEqual(
            returned_ids,
            expected_ids,
            "Packages list must contain exactly active packages belonging to this workspace.",
        )
        self.assertNotIn(
            str(pkg_inactive.id),
            returned_ids,
            "Inactive packages must be excluded from public response.",
        )
        self.assertNotIn(
            str(pkg_foreign.id),
            returned_ids,
            "Foreign tenant packages must be excluded from public response.",
        )

    def test_inactive_packages_in_same_workspace_are_excluded(self):
        """Asserts inactive packages in the same workspace are omitted from response."""
        _, workspace, _, _ = self._setup_public_workspace()
        active_pkg = self._create_package(workspace=workspace, is_active=True)
        inactive_pkg = self._create_package(workspace=workspace, is_active=False)

        response = self.client.get(public_coach_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = {p["id"] for p in response.json()["packages"]}

        self.assertIn(str(active_pkg.id), returned_ids)
        self.assertNotIn(str(inactive_pkg.id), returned_ids)

    def test_active_packages_from_other_workspaces_are_excluded(self):
        """Cross-tenant guard: foreign workspace packages never leak into response."""
        _, ws_a, _, _ = self._setup_public_workspace()
        ws_b = self._create_workspace()
        pkg_b = self._create_package(workspace=ws_b, is_active=True)

        response = self.client.get(public_coach_url(ws_a.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = {p["id"] for p in response.json()["packages"]}

        self.assertNotIn(str(pkg_b.id), returned_ids)
        self.assertNotIn(str(pkg_b.id), response.content.decode())

    def test_workspace_with_no_active_packages_returns_empty_list(self):
        """Asserts workspace with no active packages returns 200 with packages [] (Point 10)."""
        owner = self._create_user()
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")
        self._create_coach_profile(user=owner)
        self._create_package(workspace=workspace, is_active=False)

        response = self.client.get(public_coach_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(set(data.keys()), TOP_LEVEL_KEYS)
        self.assertEqual(data["packages"], [])
        self.assertIsInstance(data["packages"], list)


class PublicCoachPackageObjectShapeTests(BasePublicCoachApiTestCase):
    """Verifies the exact ten-key package object shape and workspace isolation (Point 9)."""

    def test_each_package_object_contains_exact_ten_keys(self):
        """Asserts each package dictionary contains exactly the ten documented public keys."""
        _, workspace, _, _ = self._setup_public_workspace(package_count=2)
        response = self.client.get(public_coach_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        packages = response.json()["packages"]
        self.assertGreaterEqual(len(packages), 1)

        for pkg in packages:
            with self.subTest(pkg_id=pkg.get("id")):
                self.assertEqual(
                    set(pkg.keys()),
                    EXPECTED_PACKAGE_KEYS,
                    f"Package dictionary must contain exactly {EXPECTED_PACKAGE_KEYS}.",
                )

    def test_package_objects_never_expose_workspace_or_workspace_id(self):
        """Asserts workspace and workspace_id are absent from package dicts and raw text."""
        _, workspace, _, _ = self._setup_public_workspace(package_count=2)
        response = self.client.get(public_coach_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        packages = response.json()["packages"]

        for pkg in packages:
            for forbidden_key in FORBIDDEN_PACKAGE_KEYS:
                with self.subTest(pkg_id=pkg.get("id"), key=forbidden_key):
                    self.assertNotIn(
                        forbidden_key,
                        pkg,
                        f"Field '{forbidden_key}' must not appear in package object.",
                    )

    def test_package_field_values_and_types_match_database(self):
        """Asserts package values match database records with correct data types."""
        owner = self._create_user()
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")
        package = self._create_package(
            workspace=workspace,
            name="12-Week Transformation",
            description="Complete body transformation program with custom nutrition.",
            price=Decimal("4500.00"),
            currency="EGP",
            duration_days=84,
            features=["Custom Workout Plan", "Nutrition Macros", "24/7 Chat Support"],
            is_active=True,
        )

        response = self.client.get(public_coach_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        packages = response.json()["packages"]
        self.assertEqual(len(packages), 1)
        pkg = packages[0]

        self.assertEqual(pkg["id"], str(package.id))
        self.assertEqual(pkg["name"], "12-Week Transformation")
        self.assertEqual(
            pkg["description"],
            "Complete body transformation program with custom nutrition.",
        )
        self.assertEqual(Decimal(pkg["price"]), Decimal("4500.00"))
        self.assertEqual(pkg["currency"], "EGP")
        self.assertEqual(pkg["duration_days"], 84)
        self.assertEqual(
            pkg["features"],
            ["Custom Workout Plan", "Nutrition Macros", "24/7 Chat Support"],
        )
        self.assertIs(pkg["is_active"], True)
        self.assertIn("created_at", pkg)
        self.assertIn("updated_at", pkg)


class PublicCoachSuspendedAndNotFoundTests(BasePublicCoachApiTestCase):
    """Verifies SUSPENDED workspace invisibility, 404, and error envelope (Points 12 & 13)."""

    def test_suspended_workspace_returns_404_not_found(self):
        """Asserts requesting a SUSPENDED workspace returns 404 NOT_FOUND, never 403."""
        owner = self._create_user()
        suspended_ws = self._create_workspace(status="SUSPENDED")
        self._create_membership(user=owner, workspace=suspended_ws, role="OWNER", status="ACTIVE")
        self._create_coach_profile(user=owner)
        self._create_package(workspace=suspended_ws, is_active=True)

        response = self.client.get(public_coach_url(suspended_ws.slug))
        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
            "SUSPENDED workspace must return 404 NOT_FOUND on public page.",
        )
        self.assertNotEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
            "SUSPENDED workspace must never return 403 Forbidden.",
        )

    def test_suspended_workspace_is_byte_identical_to_nonexistent_slug(self):
        """Guards anti-enumeration: SUSPENDED workspace is byte-identical 404 to non-existent.

        A public visitor must not be able to determine whether a slug belongs to an existing
        but suspended workspace or does not exist at all. Direct byte equality on
        response.content prevents any timing, message, or metadata leakage.
        """
        owner = self._create_user()
        suspended_ws = self._create_workspace(status="SUSPENDED")
        self._create_membership(user=owner, workspace=suspended_ws, role="OWNER", status="ACTIVE")
        self._create_coach_profile(user=owner)
        self._create_package(workspace=suspended_ws, is_active=True)

        nonexistent_slug = f"nonexistent-slug-{uuid.uuid4().hex[:10]}"

        suspended_response = self.client.get(public_coach_url(suspended_ws.slug))
        nonexistent_response = self.client.get(public_coach_url(nonexistent_slug))

        self.assertEqual(suspended_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(nonexistent_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            suspended_response.content,
            nonexistent_response.content,
            "SUSPENDED workspace response must be byte-identical to a non-existent slug response.",
        )

    def test_nonexistent_and_suspended_slugs_use_api_error_envelope(self):
        """Asserts 404 responses conform strictly to API §2 error envelope specification."""
        nonexistent_slug = f"nonexistent-slug-{uuid.uuid4().hex[:10]}"
        response = self.client.get(public_coach_url(nonexistent_slug))
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )


class PublicCoachMethodHandlingTests(BasePublicCoachApiTestCase):
    """Verifies that only HTTP GET is allowed on the public coach endpoint (Point 14)."""

    def test_non_get_methods_return_405_method_not_allowed(self):
        """Asserts POST, PATCH, PUT, and DELETE on the public coach URL return 405."""
        _, workspace, _, _ = self._setup_public_workspace()
        url = public_coach_url(workspace.slug)
        for method in ("post", "patch", "put", "delete"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(url)
                self.assertEqual(
                    response.status_code,
                    status.HTTP_405_METHOD_NOT_ALLOWED,
                    f"HTTP {method.upper()} on public coach page must return 405.",
                )


class PublicCoachAuthenticationInvarianceTests(BasePublicCoachApiTestCase):
    """Verifies response byte equality regardless of caller authentication status (Point 15)."""

    def test_authenticated_unaffiliated_user_receives_identical_response_to_anonymous(self):
        """Guards auth neutrality: authenticated user gets byte-identical response to visitor.

        The public coach page is fully open and unauthenticated. An authenticated user who
        has no membership in this workspace must see exactly what an anonymous visitor sees,
        with byte-for-byte identical content.
        """
        _, workspace, _, _ = self._setup_public_workspace()
        unaffiliated_user = self._create_user(email="unaffiliated-visitor@example.com")

        self.client.credentials()
        self.client.logout()
        anon_res = self.client.get(public_coach_url(workspace.slug))
        self.assertEqual(anon_res.status_code, status.HTTP_200_OK)

        self.client.force_authenticate(user=unaffiliated_user)
        auth_res = self.client.get(public_coach_url(workspace.slug))
        self.assertEqual(auth_res.status_code, status.HTTP_200_OK)

        self.assertEqual(
            auth_res.content,
            anon_res.content,
            "Authenticated unaffiliated caller must receive byte-identical response to anonymous.",
        )

    def test_authenticated_owner_receives_identical_public_response_to_anonymous(self):
        """Asserts even the workspace owner gets the same byte response on public endpoint."""
        owner, workspace, _, _ = self._setup_public_workspace()

        self.client.credentials()
        self.client.logout()
        anon_res = self.client.get(public_coach_url(workspace.slug))
        self.assertEqual(anon_res.status_code, status.HTTP_200_OK)

        self.client.force_authenticate(user=owner)
        owner_res = self.client.get(public_coach_url(workspace.slug))
        self.assertEqual(owner_res.status_code, status.HTTP_200_OK)

        self.assertEqual(
            owner_res.content,
            anon_res.content,
            "Authenticated workspace owner must receive byte-identical response to anonymous.",
        )


class PublicCoachMediaUrlTests(BasePublicCoachApiTestCase):
    """Verifies null values for unset images and safe URL strings for set images (Point 16)."""

    def test_unset_workspace_and_coach_images_return_null(self):
        """Asserts logo and profile_image fields are null in the response when unset."""
        owner = self._create_user()
        workspace = self._create_workspace(logo="", profile_image="")
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")
        self._create_coach_profile(user=owner, profile_image="")

        response = self.client.get(public_coach_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertIsNone(data["workspace"]["logo"])
        self.assertIsNone(data["workspace"]["profile_image"])
        self.assertIsNone(data["coach"]["profile_image"])

    def test_set_workspace_and_coach_images_return_safe_url_strings(self):
        """Asserts populated image fields return safe URL strings without filesystem leaks."""
        owner = self._create_user()
        workspace = self._create_workspace()
        workspace.logo = make_test_image(filename="workspace_logo.png")
        workspace.profile_image = make_test_image(filename="workspace_profile.png")
        workspace.save()

        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")
        coach_profile = self._create_coach_profile(user=owner)
        coach_profile.profile_image = make_test_image(filename="coach_profile.png")
        coach_profile.save()

        response = self.client.get(public_coach_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        ws_logo = data["workspace"]["logo"]
        ws_profile = data["workspace"]["profile_image"]
        coach_profile_img = data["coach"]["profile_image"]

        self.assertIsNotNone(ws_logo)
        self.assertIsNotNone(ws_profile)
        self.assertIsNotNone(coach_profile_img)

        for img_url, label in [
            (ws_logo, "Workspace logo"),
            (ws_profile, "Workspace profile_image"),
            (coach_profile_img, "Coach profile_image"),
        ]:
            with self.subTest(image_label=label):
                self.assertIsInstance(img_url, str)
                self.assertFalse(
                    img_url.startswith("/Users/"),
                    f"{label} URL must not start with local /Users/ path.",
                )
                self.assertFalse(
                    img_url.startswith("/private/"),
                    f"{label} URL must not start with /private/ system path.",
                )
                self.assertNotIn(
                    "media_root",
                    img_url.lower(),
                    f"{label} URL must not contain 'media_root'.",
                )


class PublicCoachArchitectureGuardTests(BasePublicCoachApiTestCase):
    """Verifies no unapproved models or cross-Epic model leakages (Architecture Guards)."""

    def test_coaching_app_exposes_only_package(self):
        """Asserts the coaching app model set contains only Package."""
        names = {m.__name__ for m in apps.get_app_config("coaching").get_models()}
        self.assertEqual(names, {"Package"})

    def test_billing_app_defines_no_models(self):
        """Asserts billing app defines no models ahead of Epic 22."""
        names = {m.__name__ for m in apps.get_app_config("billing").get_models()}
        self.assertEqual(names, set())

    def test_workspace_app_model_set_is_approved(self):
        """Asserts workspaces app exposes only approved models."""
        names = {m.__name__ for m in apps.get_app_config("workspaces").get_models()}
        self.assertEqual(names, {"Workspace", "PaymentMethod"})
