"""API tests for Package CRUD (Story 5.1 / Task B).

Validates:
- Access control & permissions: unauthenticated requests across all five methods (GET list, POST,
  GET detail, PATCH, DELETE) are rejected with 401/403 and the standard API §2 error envelope.
- Authorization (Coach/Owner): ACTIVE OWNER and ACTIVE COACH are both authorised across all five
  endpoints (POST 201, GET list 200, GET detail 200, PATCH 200, DELETE 204).
- 404 family & indistinguishability: callers with no membership, INACTIVE membership,
  SUSPENDED workspace, or CLIENT-only role receive identical 404 NOT_FOUND responses
  without revealing workspace existence across list and create operations.
- Model contract: Package defines exactly the eleven documented concrete fields, explicitly
  declares a UUID primary key (UUIDField, primary_key=True), inherits WorkspaceScopedModel,
  uses DecimalField for price, JSONField for features, defaults is_active to True, contains no
  deletion fields (no archived_at, deleted_at, is_deleted), and coaching app exposes {"Package"}.
- POST /api/v1/packages contract: creates row in caller's Workspace, returns exactly the ten
  non-workspace keys, price round-trips as decimal string, features round-trips as JSON array of
  strings, is_active defaults True when omitted, and invalid/missing fields return 400
  VALIDATION_ERROR with appropriate fields dictionary.
- GET /api/v1/packages list contract: paginated response (count, next, previous, results),
  scoped strictly to caller's Workspace, supports ?is_active=true|false filter, supports
  case-insensitive ?search= on name, and ensures search and filter exclude cross-tenant rows.
- GET /api/v1/packages/{id} detail contract: returns 200 with the ten documented keys.
- PATCH /api/v1/packages/{id} contract: partial updates leave omitted fields untouched, allows
  replacing features and updating price, while cross-workspace target remains immutable.
- DELETE /api/v1/packages/{id} contract: 204 No Content, hard-deletes row from database (not
  merely deactivating it), returns 404 on repeat call, and cross-workspace target survives.
- Object isolation: cross-workspace ID and non-existent random UUID produce byte-identical
  404 NOT_FOUND responses (never 403) across GET detail, PATCH, and DELETE.
- Rate limiting: package endpoints are unthrottled under normal burst operations.
- Contract preservation guards: GET /api/v1/workspace preserves eleven keys and billing app
  defines zero models.
"""

import uuid
from decimal import Decimal

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import models
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

PACKAGES_URL = "/api/v1/packages"
WORKSPACE_URL = "/api/v1/workspace"

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

EXPECTED_PACKAGE_FIELDS = {
    "id",
    "workspace",
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

FORBIDDEN_DELETION_FIELDS = {
    "archived_at",
    "deleted_at",
    "is_deleted",
    "deleted",
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


def package_detail_url(pk: uuid.UUID | str) -> str:
    """Returns the URL for a specific package detail endpoint."""
    return f"{PACKAGES_URL}/{pk}"


class BasePackagesApiTestCase(TestCase):
    """Base test case providing client setup, cache reset, model access, and entity factories."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.client = APIClient()
        self.user_model = get_user_model()
        self.workspace_model = apps.get_model("workspaces", "Workspace")
        self.membership_model = apps.get_model("accounts", "Membership")
        self.package_model = apps.get_model("coaching", "Package")

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

    def _create_package(
        self,
        workspace=None,
        name="Pro Coaching",
        description="12-week coaching program",
        price=Decimal("3500.00"),
        currency="EGP",
        duration_days=90,
        features=None,
        is_active=True,
        **kwargs,
    ):
        """Creates and returns a Package directly in the database."""
        if workspace is None:
            workspace = self._create_workspace()
        if features is None:
            features = ["Training Plan", "Nutrition Plan", "Weekly Check-ins"]
        defaults = {
            "workspace": workspace,
            "name": name,
            "description": description,
            "price": price if isinstance(price, Decimal) else Decimal(str(price)),
            "currency": currency,
            "duration_days": duration_days,
            "features": features,
            "is_active": is_active,
        }
        defaults.update(kwargs)
        return self.package_model.objects.create(**defaults)

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
        # API §2: `fields` is emitted only for VALIDATION_ERROR.
        # NOT_FOUND and PERMISSION_DENIED carry no `fields` key.
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
                "Non-validation errors (PERMISSION_DENIED, NOT_FOUND, RATE_LIMITED) "
                "must not carry 'fields'.",
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


class PackagesAccessAndAuthorizationTests(BasePackagesApiTestCase):
    """Verifies authentication and Coach/Owner authorization on Package endpoints."""

    def test_unauthenticated_requests_on_all_methods_return_401_or_403_with_error_envelope(self):
        """Asserts unauthenticated requests on all five endpoints return 401/403 with envelope."""
        random_id = uuid.uuid4()
        detail_url = package_detail_url(random_id)

        # GET list
        get_list_res = self.client.get(PACKAGES_URL)
        self.assertIn(
            get_list_res.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )
        self.assertEqual(set(get_list_res.json().keys()), {"error"})

        # POST create
        post_res = self.client.post(
            PACKAGES_URL,
            {
                "name": "Unauthorized Package",
                "description": "Program",
                "price": "1000.00",
                "currency": "USD",
                "duration_days": 30,
            },
            format="json",
        )
        self.assertIn(
            post_res.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )
        self.assertEqual(set(post_res.json().keys()), {"error"})

        # GET detail
        get_detail_res = self.client.get(detail_url)
        self.assertIn(
            get_detail_res.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )
        self.assertEqual(set(get_detail_res.json().keys()), {"error"})

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

    def test_active_owner_is_authorised_on_all_five_endpoints(self):
        """Asserts caller with an ACTIVE OWNER membership is authorised on all 5 endpoints."""
        owner = self._create_user(email="owner.packages.all@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        # Decoy workspace to guarantee multi-tenant scoping
        self._create_membership(role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)

        # 1. POST -> 201 Created
        post_response = self.client.post(
            PACKAGES_URL,
            {
                "name": "Pro Coaching",
                "description": "12-week coaching program",
                "price": "3500.00",
                "currency": "EGP",
                "duration_days": 90,
                "features": ["Training Plan", "Nutrition Plan", "Weekly Check-ins"],
            },
            format="json",
        )
        self.assertEqual(post_response.status_code, status.HTTP_201_CREATED)
        created_id = post_response.json()["id"]

        # 2. GET list -> 200 OK (paginated)
        get_list_response = self.client.get(PACKAGES_URL)
        self.assertEqual(get_list_response.status_code, status.HTTP_200_OK)
        list_data = get_list_response.json()
        self.assertIn("results", list_data)
        returned_ids = [item["id"] for item in list_data["results"]]
        self.assertIn(created_id, returned_ids)

        # 3. GET detail -> 200 OK
        get_detail_response = self.client.get(package_detail_url(created_id))
        self.assertEqual(get_detail_response.status_code, status.HTTP_200_OK)
        self.assertEqual(get_detail_response.json()["id"], created_id)

        # 4. PATCH detail -> 200 OK
        patch_response = self.client.patch(
            package_detail_url(created_id),
            {"name": "Pro Coaching Updated by Owner"},
            format="json",
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_response.json()["name"], "Pro Coaching Updated by Owner")

        # 5. DELETE detail -> 204 No Content
        delete_response = self.client.delete(package_detail_url(created_id))
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)

    def test_active_coach_is_authorised_on_all_five_endpoints(self):
        """Asserts caller with an ACTIVE COACH membership is authorised on all 5 endpoints.

        API §8 Package CRUD explicitly specifies 'Coach/Owner' permission across package endpoints,
        matching Story 4.4 and unlike the OWNER-only restriction of Stories 4.2/4.3.
        """
        coach = self._create_user(email="coach.packages.all@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=coach, workspace=workspace, role="COACH", status="ACTIVE")

        # Decoy workspace to guarantee multi-tenant scoping
        self._create_membership(role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=coach)

        # 1. POST -> 201 Created
        post_response = self.client.post(
            PACKAGES_URL,
            {
                "name": "Coach Program",
                "description": "8-week intensive coaching",
                "price": "2400.00",
                "currency": "EGP",
                "duration_days": 60,
                "features": ["Weekly Calls", "Form Review"],
            },
            format="json",
        )
        self.assertEqual(post_response.status_code, status.HTTP_201_CREATED)
        created_id = post_response.json()["id"]

        # 2. GET list -> 200 OK (paginated)
        get_list_response = self.client.get(PACKAGES_URL)
        self.assertEqual(get_list_response.status_code, status.HTTP_200_OK)
        list_data = get_list_response.json()
        self.assertIn("results", list_data)
        returned_ids = [item["id"] for item in list_data["results"]]
        self.assertIn(created_id, returned_ids)

        # 3. GET detail -> 200 OK
        get_detail_response = self.client.get(package_detail_url(created_id))
        self.assertEqual(get_detail_response.status_code, status.HTTP_200_OK)
        self.assertEqual(get_detail_response.json()["id"], created_id)

        # 4. PATCH detail -> 200 OK
        patch_response = self.client.patch(
            package_detail_url(created_id),
            {"description": "Updated coaching description by Coach"},
            format="json",
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            patch_response.json()["description"],
            "Updated coaching description by Coach",
        )

        # 5. DELETE detail -> 204 No Content
        delete_response = self.client.delete(package_detail_url(created_id))
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)

    def test_active_coach_can_create_package_201(self):
        """Asserts ACTIVE COACH receives 201 when creating a package."""
        coach = self._create_user(email="coach.create.pkg@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=coach, workspace=workspace, role="COACH", status="ACTIVE")
        self._create_membership(role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=coach)
        response = self.client.post(
            PACKAGES_URL,
            {
                "name": "Strength & Hypertrophy",
                "description": "Hypertrophy focus",
                "price": "1800.00",
                "currency": "USD",
                "duration_days": 45,
                "features": ["Workout Logs"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertSetEqual(set(data.keys()), EXPECTED_PACKAGE_KEYS)
        self.assertEqual(data["name"], "Strength & Hypertrophy")
        self.assertTrue(
            self.package_model.objects.filter(pk=data["id"], workspace=workspace).exists(),
            "Package must be created in the coach's workspace.",
        )

    def test_active_coach_can_get_packages_list_200(self):
        """Asserts ACTIVE COACH receives 200 when listing packages."""
        coach = self._create_user(email="coach.list.pkg@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=coach, workspace=workspace, role="COACH", status="ACTIVE")
        pkg = self._create_package(workspace=workspace, name="Coach Listed Package")

        self.client.force_authenticate(user=coach)
        response = self.client.get(PACKAGES_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json().get("results", [])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], str(pkg.id))

    def test_active_coach_can_get_package_detail_200(self):
        """Asserts ACTIVE COACH receives 200 when getting package detail."""
        coach = self._create_user(email="coach.detail.pkg@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=coach, workspace=workspace, role="COACH", status="ACTIVE")
        pkg = self._create_package(workspace=workspace, name="Coach Detail Package")

        self.client.force_authenticate(user=coach)
        response = self.client.get(package_detail_url(pkg.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "Coach Detail Package")

    def test_active_coach_can_patch_package_200(self):
        """Asserts ACTIVE COACH receives 200 when updating a package."""
        coach = self._create_user(email="coach.patch.pkg@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=coach, workspace=workspace, role="COACH", status="ACTIVE")
        pkg = self._create_package(workspace=workspace, name="Original Name")

        self.client.force_authenticate(user=coach)
        response = self.client.patch(
            package_detail_url(pkg.id),
            {"name": "Patched By Coach"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        pkg.refresh_from_db()
        self.assertEqual(pkg.name, "Patched By Coach")

    def test_active_coach_can_delete_package_204(self):
        """Asserts ACTIVE COACH receives 204 when deleting a package."""
        coach = self._create_user(email="coach.del.pkg@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=coach, workspace=workspace, role="COACH", status="ACTIVE")
        pkg = self._create_package(workspace=workspace, name="To Be Deleted")

        self.client.force_authenticate(user=coach)
        response = self.client.delete(package_detail_url(pkg.id))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(self.package_model.objects.filter(pk=pkg.id).exists())


class PackagesNoQualifyingMembershipTests(BasePackagesApiTestCase):
    """Verifies 404 NOT_FOUND and indistinguishability across non-qualifying users."""

    def test_no_membership_get_returns_404_not_found(self):
        """Asserts user with no membership receives 404 NOT_FOUND on GET packages."""
        user = self._create_user(email="nomem.pkg.get@example.com")
        self._create_membership(role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=user)
        response = self.client.get(PACKAGES_URL)
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )

    def test_inactive_membership_get_returns_404_not_found(self):
        """Asserts user with INACTIVE membership receives 404 NOT_FOUND on GET packages."""
        user = self._create_user(email="inactive.pkg.get@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=user, workspace=workspace, role="OWNER", status="INACTIVE")

        self.client.force_authenticate(user=user)
        response = self.client.get(PACKAGES_URL)
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )

    def test_suspended_workspace_get_returns_404_not_found(self):
        """Asserts caller in a SUSPENDED workspace receives 404 NOT_FOUND on GET packages."""
        user = self._create_user(email="suspended.pkg.get@example.com")
        workspace = self._create_workspace(status="SUSPENDED")
        self._create_membership(user=user, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=user)
        response = self.client.get(PACKAGES_URL)
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )

    def test_client_only_membership_get_returns_404_not_found(self):
        """Asserts user with only CLIENT membership receives 404 NOT_FOUND on GET packages."""
        user = self._create_user(email="client.pkg.get@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=user, workspace=workspace, role="CLIENT", status="ACTIVE")

        self.client.force_authenticate(user=user)
        response = self.client.get(PACKAGES_URL)
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )

    def test_four_non_qualifying_scenarios_on_get_list_are_strictly_indistinguishable(self):
        """Asserts GET responses across all 4 non-qualifying cases are identical to each other."""
        # 1. No membership
        user_no_mem = self._create_user(email="indist.nomem.pkg.get@example.com")

        # 2. Inactive membership
        user_inactive = self._create_user(email="indist.inactive.pkg.get@example.com")
        ws_inactive = self._create_workspace()
        self._create_membership(
            user=user_inactive, workspace=ws_inactive, role="OWNER", status="INACTIVE"
        )

        # 3. Suspended workspace
        user_suspended = self._create_user(email="indist.suspended.pkg.get@example.com")
        ws_suspended = self._create_workspace(status="SUSPENDED")
        self._create_membership(
            user=user_suspended, workspace=ws_suspended, role="OWNER", status="ACTIVE"
        )

        # 4. Client-only membership
        user_client = self._create_user(email="indist.client.pkg.get@example.com")
        ws_client = self._create_workspace()
        self._create_membership(
            user=user_client, workspace=ws_client, role="CLIENT", status="ACTIVE"
        )

        # Collect real responses
        self.client.force_authenticate(user=user_no_mem)
        res_no_mem = self.client.get(PACKAGES_URL)

        self.client.force_authenticate(user=user_inactive)
        res_inactive = self.client.get(PACKAGES_URL)

        self.client.force_authenticate(user=user_suspended)
        res_suspended = self.client.get(PACKAGES_URL)

        self.client.force_authenticate(user=user_client)
        res_client = self.client.get(PACKAGES_URL)

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
        user_no_mem = self._create_user(email="indist.nomem.pkg.post@example.com")

        user_inactive = self._create_user(email="indist.inactive.pkg.post@example.com")
        ws_inactive = self._create_workspace()
        self._create_membership(
            user=user_inactive, workspace=ws_inactive, role="OWNER", status="INACTIVE"
        )

        user_suspended = self._create_user(email="indist.suspended.pkg.post@example.com")
        ws_suspended = self._create_workspace(status="SUSPENDED")
        self._create_membership(
            user=user_suspended, workspace=ws_suspended, role="OWNER", status="ACTIVE"
        )

        user_client = self._create_user(email="indist.client.pkg.post@example.com")
        ws_client = self._create_workspace()
        self._create_membership(
            user=user_client, workspace=ws_client, role="CLIENT", status="ACTIVE"
        )

        payload = {
            "name": "Indistinguishable Package",
            "description": "12-week program",
            "price": "3500.00",
            "currency": "EGP",
            "duration_days": 90,
            "features": ["Plan A", "Plan B"],
        }

        self.client.force_authenticate(user=user_no_mem)
        res_no_mem = self.client.post(PACKAGES_URL, payload, format="json")

        self.client.force_authenticate(user=user_inactive)
        res_inactive = self.client.post(PACKAGES_URL, payload, format="json")

        self.client.force_authenticate(user=user_suspended)
        res_suspended = self.client.post(PACKAGES_URL, payload, format="json")

        self.client.force_authenticate(user=user_client)
        res_client = self.client.post(PACKAGES_URL, payload, format="json")

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


class PackageModelContractTests(BasePackagesApiTestCase):
    """Verifies Package model schema contract, fields, typing, UUID PK, and defaults."""

    def test_package_concrete_fields_set_equality(self):
        """Asserts Package defines exactly the eleven documented concrete fields."""
        concrete_fields = {field.name for field in self.package_model._meta.concrete_fields}
        self.assertSetEqual(
            concrete_fields,
            EXPECTED_PACKAGE_FIELDS,
            "Package concrete fields must exactly match the authoritative schema contract.",
        )

    def test_package_primary_key_is_explicit_uuid_field(self):
        """Asserts Package primary key is an explicit UUIDField (API §25 Rule 13).

        A BigAutoField would expose integer IDs in URLs, violating API §25 Rule 13.
        """
        pk_field = self.package_model._meta.pk
        self.assertIsInstance(
            pk_field,
            models.UUIDField,
            "Package primary key must be an explicit models.UUIDField.",
        )
        self.assertTrue(pk_field.primary_key, "Primary key flag must be True.")
        self.assertFalse(pk_field.editable, "UUID primary key must not be editable.")
        self.assertEqual(pk_field.name, "id", "Primary key field name must be 'id'.")

    def test_package_field_types_and_defaults(self):
        """Asserts Package field types, decimal precision, JSON default, and active default."""
        price_field = self.package_model._meta.get_field("price")
        self.assertIsInstance(
            price_field,
            models.DecimalField,
            "Package.price must be a models.DecimalField.",
        )
        self.assertEqual(price_field.max_digits, 10)
        self.assertEqual(price_field.decimal_places, 2)

        features_field = self.package_model._meta.get_field("features")
        self.assertIsInstance(
            features_field,
            models.JSONField,
            "Package.features must be a models.JSONField.",
        )
        self.assertEqual(features_field.default, list)

        duration_field = self.package_model._meta.get_field("duration_days")
        self.assertIsInstance(
            duration_field,
            (models.PositiveIntegerField, models.IntegerField),
            "Package.duration_days must be an integer field.",
        )

        currency_field = self.package_model._meta.get_field("currency")
        self.assertIsInstance(
            currency_field,
            models.CharField,
            "Package.currency must be a models.CharField.",
        )
        self.assertEqual(currency_field.max_length, 3)

        name_field = self.package_model._meta.get_field("name")
        self.assertIsInstance(name_field, models.CharField)

        description_field = self.package_model._meta.get_field("description")
        self.assertIsInstance(description_field, models.TextField)

        is_active_field = self.package_model._meta.get_field("is_active")
        self.assertIsInstance(is_active_field, models.BooleanField)
        self.assertTrue(is_active_field.default, "Package.is_active must default to True.")

    def test_package_has_no_soft_deletion_or_archive_fields(self):
        """Asserts Package defines no soft-deletion or archive fields (DELETE is hard delete)."""
        concrete_fields = {field.name for field in self.package_model._meta.concrete_fields}
        self.assertTrue(
            concrete_fields.isdisjoint(FORBIDDEN_DELETION_FIELDS),
            f"Package must not contain deletion/archive fields like {FORBIDDEN_DELETION_FIELDS}.",
        )

    def test_coaching_app_exposes_exactly_package_model(self):
        """Asserts coaching app defines exactly {'Package'} in Story 5.1."""
        coaching_app = apps.get_app_config("coaching")
        concrete_model_names = {model._meta.object_name for model in coaching_app.get_models()}
        self.assertSetEqual(
            concrete_model_names,
            {"Package"},
            "coaching app must expose exactly {'Package'}.",
        )

    def test_package_inherits_workspace_scoped_model_and_tenant_queryset(self):
        """Asserts Package inherits WorkspaceScopedModel and TenantQuerySet scoping."""
        workspace_a = self._create_workspace(name="WS A Scoped")
        workspace_b = self._create_workspace(name="WS B Scoped")

        pkg_a = self._create_package(workspace=workspace_a, name="Package A")
        pkg_b = self._create_package(workspace=workspace_b, name="Package B")

        # TenantQuerySet.for_workspace scoping check
        qs_a = self.package_model.objects.for_workspace(workspace_a)
        self.assertEqual(qs_a.count(), 1)
        self.assertEqual(qs_a.first().pk, pkg_a.pk)
        self.assertFalse(qs_a.filter(pk=pkg_b.pk).exists())

        # Unscoped queryset check
        all_pks = set(self.package_model.objects.unscoped().values_list("pk", flat=True))
        self.assertTrue({pkg_a.pk, pkg_b.pk}.issubset(all_pks))


class PackagesPostEndpointTests(BasePackagesApiTestCase):
    """Verifies POST /api/v1/packages creation, whole-key response shape, and validation."""

    def test_post_valid_json_creates_row_in_callers_workspace_with_ten_keys(self):
        """Asserts valid POST returns 201 with exactly 10 keys in caller's workspace."""
        owner = self._create_user(email="pkg.post.valid@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        # Decoy workspace to test tenant attachment
        self._create_membership(role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        payload = {
            "name": "Pro Coaching",
            "description": "12-week coaching program",
            "price": "3500.00",
            "currency": "EGP",
            "duration_days": 90,
            "features": ["Training Plan", "Nutrition Plan", "Weekly Check-ins"],
        }
        response = self.client.post(PACKAGES_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertSetEqual(
            set(data.keys()),
            EXPECTED_PACKAGE_KEYS,
            "POST response body must contain exactly the ten documented model keys.",
        )
        self.assertNotIn("workspace", data)
        self.assertNotIn("workspace_id", data)
        self.assertEqual(data["name"], "Pro Coaching")
        self.assertEqual(data["description"], "12-week coaching program")
        self.assertEqual(data["price"], "3500.00")
        self.assertEqual(data["currency"], "EGP")
        self.assertEqual(data["duration_days"], 90)
        self.assertEqual(
            data["features"],
            ["Training Plan", "Nutrition Plan", "Weekly Check-ins"],
        )
        self.assertTrue(data["is_active"])

        # Verify database row
        pkg = self.package_model.objects.get(pk=data["id"])
        self.assertEqual(pkg.workspace_id, workspace.id)
        self.assertEqual(pkg.name, "Pro Coaching")
        self.assertEqual(pkg.price, Decimal("3500.00"))
        self.assertEqual(pkg.duration_days, 90)

    def test_post_price_round_trips_as_decimal_string(self):
        """Asserts price is returned as a decimal string, never a float (API §1)."""
        owner = self._create_user(email="pkg.post.price@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        response = self.client.post(
            PACKAGES_URL,
            {
                "name": "Custom Price Program",
                "description": "Program description",
                "price": "199.99",
                "currency": "USD",
                "duration_days": 30,
                "features": ["Feature A"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertIsInstance(data["price"], str)
        self.assertEqual(data["price"], "199.99")

        pkg = self.package_model.objects.get(pk=data["id"])
        self.assertEqual(pkg.price, Decimal("199.99"))

    def test_post_features_round_trips_as_json_array_of_strings(self):
        """Asserts features round-trips as a JSON array of strings."""
        owner = self._create_user(email="pkg.post.feat@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        features_list = ["Custom Workouts", "Macro Coaching", "Video Feedback", "24/7 Chat"]
        response = self.client.post(
            PACKAGES_URL,
            {
                "name": "Feature Rich Package",
                "description": "Comprehensive coaching",
                "price": "499.00",
                "currency": "USD",
                "duration_days": 60,
                "features": features_list,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data["features"], features_list)

        pkg = self.package_model.objects.get(pk=data["id"])
        self.assertEqual(pkg.features, features_list)

    def test_post_omitted_is_active_defaults_to_true(self):
        """Asserts is_active defaults to True when omitted from the POST request payload."""
        owner = self._create_user(email="pkg.post.defaultactive@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        response = self.client.post(
            PACKAGES_URL,
            {
                "name": "Default Active Package",
                "description": "Default active check",
                "price": "500.00",
                "currency": "USD",
                "duration_days": 30,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertTrue(data["is_active"], "Response is_active must default to True.")

        pkg = self.package_model.objects.get(pk=data["id"])
        self.assertTrue(pkg.is_active, "Database is_active must default to True.")

    def test_post_missing_name_returns_400_validation_error(self):
        """Asserts omitting required 'name' field returns 400 VALIDATION_ERROR."""
        owner = self._create_user(email="pkg.post.noname@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        response = self.client.post(
            PACKAGES_URL,
            {
                "description": "Missing name",
                "price": "1000.00",
                "currency": "USD",
                "duration_days": 30,
            },
            format="json",
        )
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_400_BAD_REQUEST,
            expected_code="VALIDATION_ERROR",
            expected_field="name",
        )
        self.assertEqual(self.package_model.objects.count(), 0)

    def test_post_missing_price_returns_400_validation_error(self):
        """Asserts omitting required 'price' field returns 400 VALIDATION_ERROR."""
        owner = self._create_user(email="pkg.post.noprice@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        response = self.client.post(
            PACKAGES_URL,
            {
                "name": "Missing Price Package",
                "description": "No price supplied",
                "currency": "USD",
                "duration_days": 30,
            },
            format="json",
        )
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_400_BAD_REQUEST,
            expected_code="VALIDATION_ERROR",
            expected_field="price",
        )
        self.assertEqual(self.package_model.objects.count(), 0)

    def test_post_missing_duration_days_returns_400_validation_error(self):
        """Asserts omitting required 'duration_days' returns 400 VALIDATION_ERROR."""
        owner = self._create_user(email="pkg.post.noduration@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        response = self.client.post(
            PACKAGES_URL,
            {
                "name": "Missing Duration Package",
                "description": "No duration supplied",
                "price": "1000.00",
                "currency": "USD",
            },
            format="json",
        )
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_400_BAD_REQUEST,
            expected_code="VALIDATION_ERROR",
            expected_field="duration_days",
        )
        self.assertEqual(self.package_model.objects.count(), 0)

    def test_post_invalid_currency_returns_400_validation_error(self):
        """Asserts currency exceeding 3 characters returns 400 VALIDATION_ERROR."""
        owner = self._create_user(email="pkg.post.badcurr@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        response = self.client.post(
            PACKAGES_URL,
            {
                "name": "Bad Currency Package",
                "description": "Currency toolong",
                "price": "1000.00",
                "currency": "TOOLONG",
                "duration_days": 30,
            },
            format="json",
        )
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_400_BAD_REQUEST,
            expected_code="VALIDATION_ERROR",
            expected_field="currency",
        )
        self.assertEqual(self.package_model.objects.count(), 0)

    def test_post_invalid_price_format_returns_400_validation_error(self):
        """Asserts non-numeric price string returns 400 VALIDATION_ERROR with 'price'."""
        owner = self._create_user(email="pkg.post.badprice@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        response = self.client.post(
            PACKAGES_URL,
            {
                "name": "Bad Price Package",
                "description": "Invalid decimal",
                "price": "invalid-decimal",
                "currency": "USD",
                "duration_days": 30,
            },
            format="json",
        )
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_400_BAD_REQUEST,
            expected_code="VALIDATION_ERROR",
            expected_field="price",
        )
        self.assertEqual(self.package_model.objects.count(), 0)


class PackagesGetListEndpointTests(BasePackagesApiTestCase):
    """Verifies GET /api/v1/packages pagination, search, filter, and tenant scoping."""

    def test_get_list_returns_only_callers_workspace_packages_paginated(self):
        """Asserts GET returns only caller's Workspace packages wrapped in standard pagination."""
        owner_a = self._create_user(email="owner.a.pkglist@example.com")
        ws_a = self._create_workspace(name="Gym A")
        self._create_membership(user=owner_a, workspace=ws_a, role="OWNER", status="ACTIVE")

        owner_b = self._create_user(email="owner.b.pkglist@example.com")
        ws_b = self._create_workspace(name="Gym B")
        self._create_membership(user=owner_b, workspace=ws_b, role="OWNER", status="ACTIVE")

        pkg_a1 = self._create_package(workspace=ws_a, name="Gym A Bronze")
        pkg_a2 = self._create_package(workspace=ws_a, name="Gym A Silver")
        pkg_b1 = self._create_package(workspace=ws_b, name="Gym B Bronze")
        pkg_b2 = self._create_package(workspace=ws_b, name="Gym B Gold")

        self.client.force_authenticate(user=owner_a)
        response = self.client.get(PACKAGES_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertSetEqual(
            set(data.keys()),
            {"count", "next", "previous", "results"},
            "Response must match standard pagination structure {count, next, previous, results}.",
        )
        self.assertEqual(data["count"], 2)
        self.assertIsNone(data["next"])
        self.assertIsNone(data["previous"])
        self.assertEqual(len(data["results"]), 2)

        returned_ids = {item["id"] for item in data["results"]}
        self.assertSetEqual(
            returned_ids,
            {str(pkg_a1.id), str(pkg_a2.id)},
            "GET response must contain only Workspace A package IDs.",
        )
        self.assertNotIn(str(pkg_b1.id), returned_ids)
        self.assertNotIn(str(pkg_b2.id), returned_ids)

        for item in data["results"]:
            self.assertSetEqual(
                set(item.keys()),
                EXPECTED_PACKAGE_KEYS,
                "Each package item must contain exactly the ten documented keys.",
            )
            self.assertNotIn("workspace", item)

    def test_get_list_returns_empty_paginated_response_when_no_packages(self):
        """Asserts GET returns empty paginated payload when caller's workspace has no packages."""
        owner_a = self._create_user(email="owner.empty.pkg.a@example.com")
        ws_a = self._create_workspace(name="Gym A Empty")
        self._create_membership(user=owner_a, workspace=ws_a, role="OWNER", status="ACTIVE")

        owner_b = self._create_user(email="owner.empty.pkg.b@example.com")
        ws_b = self._create_workspace(name="Gym B NonEmpty")
        self._create_membership(user=owner_b, workspace=ws_b, role="OWNER", status="ACTIVE")
        self._create_package(workspace=ws_b, name="Gym B Package")

        self.client.force_authenticate(user=owner_a)
        response = self.client.get(PACKAGES_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["count"], 0)
        self.assertIsNone(data["next"])
        self.assertIsNone(data["previous"])
        self.assertEqual(data["results"], [])

    def test_get_list_active_inactive_filtering(self):
        """Asserts ?is_active=true|false filters correctly, and absent param returns both."""
        owner_a = self._create_user(email="owner.a.filter@example.com")
        ws_a = self._create_workspace(name="Gym A Filter")
        self._create_membership(user=owner_a, workspace=ws_a, role="OWNER", status="ACTIVE")

        # Workspace A packages
        pkg_active1 = self._create_package(workspace=ws_a, name="Active 1", is_active=True)
        pkg_active2 = self._create_package(workspace=ws_a, name="Active 2", is_active=True)
        pkg_inactive = self._create_package(workspace=ws_a, name="Inactive 1", is_active=False)

        # Workspace B decoy packages
        ws_b = self._create_workspace(name="Gym B Filter Decoy")
        self._create_membership(workspace=ws_b, role="OWNER", status="ACTIVE")
        self._create_package(workspace=ws_b, name="WS B Active", is_active=True)
        self._create_package(workspace=ws_b, name="WS B Inactive", is_active=False)

        self.client.force_authenticate(user=owner_a)

        # 1. ?is_active=true -> only active
        res_active = self.client.get(f"{PACKAGES_URL}?is_active=true")
        self.assertEqual(res_active.status_code, status.HTTP_200_OK)
        data_active = res_active.json()
        self.assertEqual(data_active["count"], 2)
        returned_active_ids = {item["id"] for item in data_active["results"]}
        self.assertSetEqual(
            returned_active_ids,
            {str(pkg_active1.id), str(pkg_active2.id)},
        )

        # 2. ?is_active=false -> only inactive
        res_inactive = self.client.get(f"{PACKAGES_URL}?is_active=false")
        self.assertEqual(res_inactive.status_code, status.HTTP_200_OK)
        data_inactive = res_inactive.json()
        self.assertEqual(data_inactive["count"], 1)
        self.assertEqual(data_inactive["results"][0]["id"], str(pkg_inactive.id))

        # 3. Absent param -> all 3
        res_all = self.client.get(PACKAGES_URL)
        self.assertEqual(res_all.status_code, status.HTTP_200_OK)
        data_all = res_all.json()
        self.assertEqual(data_all["count"], 3)

    def test_get_list_search_by_name_case_insensitive(self):
        """Asserts ?search= performs case-insensitive match on name and excludes non-matches."""
        owner = self._create_user(email="owner.search@example.com")
        workspace = self._create_workspace(name="Gym Search")
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        pkg1 = self._create_package(workspace=workspace, name="Pro Elite Coaching")
        pkg2 = self._create_package(workspace=workspace, name="Beginner Fitness Plan")
        self._create_package(workspace=workspace, name="Nutrition Only")

        self.client.force_authenticate(user=owner)

        # Search lowercase 'pro'
        res_pro = self.client.get(f"{PACKAGES_URL}?search=pro")
        self.assertEqual(res_pro.status_code, status.HTTP_200_OK)
        data_pro = res_pro.json()
        self.assertEqual(data_pro["count"], 1)
        self.assertEqual(data_pro["results"][0]["id"], str(pkg1.id))

        # Search uppercase 'PLAN'
        res_plan = self.client.get(f"{PACKAGES_URL}?search=PLAN")
        self.assertEqual(res_plan.status_code, status.HTTP_200_OK)
        data_plan = res_plan.json()
        self.assertEqual(data_plan["count"], 1)
        self.assertEqual(data_plan["results"][0]["id"], str(pkg2.id))

    def test_get_list_search_and_filter_are_strictly_scoped_to_callers_workspace(self):
        """Asserts search and filter queries never return matching packages from other tenants."""
        owner_a = self._create_user(email="owner.a.scopedsearch@example.com")
        ws_a = self._create_workspace(name="Gym A Scoped")
        self._create_membership(user=owner_a, workspace=ws_a, role="OWNER", status="ACTIVE")

        owner_b = self._create_user(email="owner.b.scopedsearch@example.com")
        ws_b = self._create_workspace(name="Gym B Scoped")
        self._create_membership(user=owner_b, workspace=ws_b, role="OWNER", status="ACTIVE")

        # WS A has one matching package
        pkg_a = self._create_package(workspace=ws_a, name="Crossfit Champion", is_active=True)

        # WS B has matching active and inactive packages with identical names
        self._create_package(workspace=ws_b, name="Crossfit Champion", is_active=True)
        self._create_package(workspace=ws_b, name="Crossfit Champion", is_active=False)

        self.client.force_authenticate(user=owner_a)

        # Scoped search
        res_search = self.client.get(f"{PACKAGES_URL}?search=Crossfit")
        self.assertEqual(res_search.status_code, status.HTTP_200_OK)
        data_search = res_search.json()
        self.assertEqual(data_search["count"], 1)
        self.assertEqual(data_search["results"][0]["id"], str(pkg_a.id))

        # Combined search and filter
        res_combined = self.client.get(f"{PACKAGES_URL}?search=Crossfit&is_active=true")
        self.assertEqual(res_combined.status_code, status.HTTP_200_OK)
        data_combined = res_combined.json()
        self.assertEqual(data_combined["count"], 1)
        self.assertEqual(data_combined["results"][0]["id"], str(pkg_a.id))

    def test_get_list_pagination_page_traversal(self):
        """Asserts FitOpsPageNumberPagination (PAGE_SIZE 20) handles page traversal cleanly."""
        owner = self._create_user(email="owner.pagination@example.com")
        workspace = self._create_workspace(name="Gym Large Catalog")
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        # Create 25 packages in caller's workspace
        for i in range(25):
            self._create_package(
                workspace=workspace,
                name=f"Package {i:02d}",
                price=Decimal("100.00") + Decimal(i),
            )

        # Decoy packages in another workspace
        ws_decoy = self._create_workspace(name="Gym Decoy Catalog")
        self._create_membership(workspace=ws_decoy, role="OWNER", status="ACTIVE")
        for i in range(5):
            self._create_package(workspace=ws_decoy, name=f"Decoy Package {i}")

        self.client.force_authenticate(user=owner)

        # Page 1
        page1_res = self.client.get(PACKAGES_URL)
        self.assertEqual(page1_res.status_code, status.HTTP_200_OK)
        page1_data = page1_res.json()
        self.assertEqual(page1_data["count"], 25)
        self.assertEqual(len(page1_data["results"]), 20)
        self.assertIsNotNone(page1_data["next"])
        self.assertIn("page=2", page1_data["next"])
        self.assertIsNone(page1_data["previous"])

        # Page 2
        page2_res = self.client.get(f"{PACKAGES_URL}?page=2")
        self.assertEqual(page2_res.status_code, status.HTTP_200_OK)
        page2_data = page2_res.json()
        self.assertEqual(page2_data["count"], 25)
        self.assertEqual(len(page2_data["results"]), 5)
        self.assertIsNone(page2_data["next"])
        self.assertIsNotNone(page2_data["previous"])


class PackagesDetailPatchDeleteEndpointTests(BasePackagesApiTestCase):
    """Verifies GET detail, partial PATCH updates, and permanent hard DELETE operations."""

    def test_get_detail_returns_200_with_ten_keys(self):
        """Asserts GET /api/v1/packages/{id} returns 200 with exactly the ten documented keys."""
        owner = self._create_user(email="owner.detail@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        pkg = self._create_package(
            workspace=workspace,
            name="Pro Coaching Detail",
            description="Detailed 12-week program",
            price=Decimal("3500.00"),
            currency="EGP",
            duration_days=90,
            features=["Plan A", "Plan B"],
            is_active=True,
        )

        self.client.force_authenticate(user=owner)
        response = self.client.get(package_detail_url(pkg.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertSetEqual(set(data.keys()), EXPECTED_PACKAGE_KEYS)
        self.assertEqual(data["id"], str(pkg.id))
        self.assertEqual(data["name"], "Pro Coaching Detail")
        self.assertEqual(data["description"], "Detailed 12-week program")
        self.assertEqual(data["price"], "3500.00")
        self.assertEqual(data["currency"], "EGP")
        self.assertEqual(data["duration_days"], 90)
        self.assertEqual(data["features"], ["Plan A", "Plan B"])
        self.assertTrue(data["is_active"])

    def test_patch_partial_update_modifies_targeted_fields_and_preserves_others(self):
        """Asserts partial PATCH updates only targeted fields and leaves others unchanged."""
        owner = self._create_user(email="owner.patch.partial@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        pkg = self._create_package(
            workspace=workspace,
            name="Original Name",
            description="Original Description",
            price=Decimal("3500.00"),
            currency="EGP",
            duration_days=90,
            features=["Original Feature"],
            is_active=True,
        )

        self.client.force_authenticate(user=owner)
        response = self.client.patch(
            package_detail_url(pkg.id),
            {"name": "Updated Name"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertSetEqual(set(data.keys()), EXPECTED_PACKAGE_KEYS)
        self.assertEqual(data["name"], "Updated Name")
        self.assertEqual(data["description"], "Original Description")
        self.assertEqual(data["price"], "3500.00")
        self.assertEqual(data["currency"], "EGP")
        self.assertEqual(data["duration_days"], 90)
        self.assertEqual(data["features"], ["Original Feature"])
        self.assertTrue(data["is_active"])

        pkg.refresh_from_db()
        self.assertEqual(pkg.name, "Updated Name")
        self.assertEqual(pkg.description, "Original Description")
        self.assertEqual(pkg.price, Decimal("3500.00"))

    def test_patch_features_replacement(self):
        """Asserts features JSON array can be completely replaced via PATCH."""
        owner = self._create_user(email="owner.patch.feat@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        pkg = self._create_package(
            workspace=workspace,
            features=["Old Feature 1", "Old Feature 2"],
        )

        self.client.force_authenticate(user=owner)
        new_features = ["New Feature A", "New Feature B", "New Feature C"]
        response = self.client.patch(
            package_detail_url(pkg.id),
            {"features": new_features},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["features"], new_features)

        pkg.refresh_from_db()
        self.assertEqual(pkg.features, new_features)

    def test_patch_price_and_duration_updates(self):
        """Asserts price and duration_days can be updated with proper decimal formatting."""
        owner = self._create_user(email="owner.patch.pricedur@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        pkg = self._create_package(
            workspace=workspace,
            price=Decimal("1000.00"),
            duration_days=30,
        )

        self.client.force_authenticate(user=owner)
        response = self.client.patch(
            package_detail_url(pkg.id),
            {"price": "1450.50", "duration_days": 45},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["price"], "1450.50")
        self.assertEqual(data["duration_days"], 45)

        pkg.refresh_from_db()
        self.assertEqual(pkg.price, Decimal("1450.50"))
        self.assertEqual(pkg.duration_days, 45)

    def test_delete_succeeds_204_and_hard_deletes_row_from_database(self):
        """Asserts DELETE returns 204 and permanently removes the row from the database."""
        owner = self._create_user(email="owner.del.hard@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        pkg = self._create_package(workspace=workspace, name="Hard Delete Target")

        self.client.force_authenticate(user=owner)
        response = self.client.delete(package_detail_url(pkg.id))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # Confirm hard delete: row is gone from both scoped and unscoped querysets
        self.assertFalse(
            self.package_model.objects.filter(pk=pkg.id).exists(),
            "Package row must no longer exist in standard scoped queryset.",
        )
        self.assertFalse(
            self.package_model.objects.unscoped().filter(pk=pkg.id).exists(),
            "Package row must be permanently hard-deleted (not soft-deleted).",
        )

    def test_delete_twice_returns_404_on_second_call(self):
        """Asserts deleting an already deleted package returns 404 NOT_FOUND."""
        owner = self._create_user(email="owner.deltwice.pkg@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        pkg = self._create_package(workspace=workspace, name="Delete Twice Target")

        self.client.force_authenticate(user=owner)
        first_delete = self.client.delete(package_detail_url(pkg.id))
        self.assertEqual(first_delete.status_code, status.HTTP_204_NO_CONTENT)

        second_delete = self.client.delete(package_detail_url(pkg.id))
        self.assert_error_envelope(
            second_delete,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )

    def test_delete_hard_deletes_active_package_and_does_not_merely_deactivate(self):
        """Asserts DELETE on an active package permanently removes it rather than deactivating."""
        owner = self._create_user(email="owner.del.active@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        pkg = self._create_package(workspace=workspace, is_active=True, name="Active Before Del")

        self.client.force_authenticate(user=owner)
        response = self.client.delete(package_detail_url(pkg.id))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # Prove no row exists in any state in the database
        self.assertFalse(
            self.package_model.objects.unscoped().filter(pk=pkg.id).exists(),
            "DELETE must permanently remove the row, not merely set is_active=False.",
        )


class PackagesObjectIsolationTests(BasePackagesApiTestCase):
    """Verifies cross-workspace IDs and non-existent random UUIDs produce identical 404s."""

    def test_cross_workspace_id_and_nonexistent_uuid_produce_indistinguishable_404_on_get_detail(
        self,
    ):
        """Asserts cross-workspace ID and random UUID produce byte-identical 404s on GET detail."""
        owner_a = self._create_user(email="iso.owner.a.get@example.com")
        ws_a = self._create_workspace(name="Gym A")
        self._create_membership(user=owner_a, workspace=ws_a, role="OWNER", status="ACTIVE")

        owner_b = self._create_user(email="iso.owner.b.get@example.com")
        ws_b = self._create_workspace(name="Gym B")
        self._create_membership(user=owner_b, workspace=ws_b, role="OWNER", status="ACTIVE")

        pkg_b = self._create_package(workspace=ws_b, name="WS B Secret Package")
        non_existent_id = uuid.uuid4()

        self.client.force_authenticate(user=owner_a)

        # Cross-workspace request
        res_cross = self.client.get(package_detail_url(pkg_b.id))

        # Non-existent UUID request
        res_nonexistent = self.client.get(package_detail_url(non_existent_id))

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

    def test_cross_workspace_id_and_nonexistent_uuid_produce_indistinguishable_404_on_patch(
        self,
    ):
        """Asserts cross-workspace ID and random UUID produce byte-identical 404s on PATCH."""
        owner_a = self._create_user(email="iso.owner.a.patch@example.com")
        ws_a = self._create_workspace(name="Gym A")
        self._create_membership(user=owner_a, workspace=ws_a, role="OWNER", status="ACTIVE")

        owner_b = self._create_user(email="iso.owner.b.patch@example.com")
        ws_b = self._create_workspace(name="Gym B")
        self._create_membership(user=owner_b, workspace=ws_b, role="OWNER", status="ACTIVE")

        pkg_b = self._create_package(workspace=ws_b, name="WS B Package")
        non_existent_id = uuid.uuid4()

        self.client.force_authenticate(user=owner_a)

        res_cross = self.client.patch(
            package_detail_url(pkg_b.id),
            {"name": "Hacked Name"},
            format="json",
        )
        res_nonexistent = self.client.patch(
            package_detail_url(non_existent_id),
            {"name": "Hacked Name"},
            format="json",
        )

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

    def test_cross_workspace_id_and_nonexistent_uuid_produce_indistinguishable_404_on_delete(
        self,
    ):
        """Asserts cross-workspace ID and random UUID produce byte-identical 404s on DELETE."""
        owner_a = self._create_user(email="iso.owner.a.del@example.com")
        ws_a = self._create_workspace(name="Gym A")
        self._create_membership(user=owner_a, workspace=ws_a, role="OWNER", status="ACTIVE")

        owner_b = self._create_user(email="iso.owner.b.del@example.com")
        ws_b = self._create_workspace(name="Gym B")
        self._create_membership(user=owner_b, workspace=ws_b, role="OWNER", status="ACTIVE")

        pkg_b = self._create_package(workspace=ws_b, name="WS B Package")
        non_existent_id = uuid.uuid4()

        self.client.force_authenticate(user=owner_a)

        res_cross = self.client.delete(package_detail_url(pkg_b.id))
        res_nonexistent = self.client.delete(package_detail_url(non_existent_id))

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

    def test_cross_workspace_patch_leaves_target_workspace_package_unchanged(self):
        """Cross-tenant PATCH: attempting to update WS B item as Owner A returns 404 & no-op."""
        owner_a = self._create_user(email="owner.a.patch.noop@example.com")
        ws_a = self._create_workspace(name="Gym A")
        self._create_membership(user=owner_a, workspace=ws_a, role="OWNER", status="ACTIVE")

        owner_b = self._create_user(email="owner.b.patch.noop@example.com")
        ws_b = self._create_workspace(name="Gym B")
        self._create_membership(user=owner_b, workspace=ws_b, role="OWNER", status="ACTIVE")

        pkg_b = self._create_package(
            workspace=ws_b,
            name="Gym B Untouched Package",
            description="Gym B original description",
            price=Decimal("2000.00"),
        )

        self.client.force_authenticate(user=owner_a)
        response = self.client.patch(
            package_detail_url(pkg_b.id),
            {"name": "Tampered Name", "price": "1.00"},
            format="json",
        )
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )

        pkg_b.refresh_from_db()
        self.assertEqual(
            pkg_b.name,
            "Gym B Untouched Package",
            "Target package in Workspace B must remain untouched.",
        )
        self.assertEqual(
            pkg_b.price,
            Decimal("2000.00"),
            "Target package in Workspace B must remain untouched.",
        )

    def test_cross_workspace_delete_leaves_target_workspace_package_intact(self):
        """Cross-tenant DELETE: deleting WS B package as Owner A returns 404 and row survives."""
        owner_a = self._create_user(email="owner.a.del.intact@example.com")
        ws_a = self._create_workspace(name="Gym A")
        self._create_membership(user=owner_a, workspace=ws_a, role="OWNER", status="ACTIVE")

        owner_b = self._create_user(email="owner.b.del.intact@example.com")
        ws_b = self._create_workspace(name="Gym B")
        self._create_membership(user=owner_b, workspace=ws_b, role="OWNER", status="ACTIVE")

        pkg_a = self._create_package(workspace=ws_a, name="Package A")
        pkg_b = self._create_package(workspace=ws_b, name="Package B")

        self.client.force_authenticate(user=owner_a)
        response = self.client.delete(package_detail_url(pkg_b.id))
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )

        # Verify WS B's record survives intact in database
        self.assertTrue(
            self.package_model.objects.filter(pk=pkg_b.id).exists(),
            "Package in Workspace B must survive foreign delete attempt.",
        )
        self.assertTrue(
            self.package_model.objects.filter(pk=pkg_a.id).exists(),
            "Package in Workspace A must remain intact.",
        )


class PackagesContractPreservationAndArchitectureTests(BasePackagesApiTestCase):
    """Guards Story 4.1/4.2 11-key contracts, billing app model boundaries, and method dispatch."""

    def test_get_workspace_preserves_exact_eleven_keys_contract(self):
        """Contract preservation: GET /api/v1/workspace returns exactly the 11 established keys."""
        owner = self._create_user(email="guard.pkg.get@example.com")
        workspace = self._create_workspace(
            description="Guarded description",
            brand_color="#123456",
        )
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self.client.force_authenticate(user=owner)
        response = self.client.get(WORKSPACE_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertSetEqual(
            set(data.keys()),
            EXPECTED_WORKSPACE_KEYS,
            "GET /api/v1/workspace response keys must be exactly the 11 established keys.",
        )
        self.assertNotIn(
            "packages",
            data,
            "packages must not be present in GET /api/v1/workspace response.",
        )

    def test_billing_app_exposes_no_models(self):
        """Guards Epic 22 boundary: billing app must define zero models in Story 5.1."""
        billing_app = apps.get_app_config("billing")
        concrete_model_names = {model._meta.object_name for model in billing_app.get_models()}
        self.assertEqual(
            concrete_model_names,
            set(),
            "billing app must expose no models (deferred to Epic 22).",
        )

    def test_disallowed_http_methods_return_405_method_not_allowed(self):
        """Asserts disallowed HTTP methods on collection and detail return 405."""
        owner = self._create_user(email="pkg.methods@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        pkg = self._create_package(workspace=workspace, name="Package For 405")

        self.client.force_authenticate(user=owner)

        # Disallowed on collection (only GET and POST are allowed)
        for method in ["put", "delete"]:
            with self.subTest(endpoint=PACKAGES_URL, http_method=method):
                client_method = getattr(self.client, method)
                response = client_method(PACKAGES_URL)
                self.assertEqual(
                    response.status_code,
                    status.HTTP_405_METHOD_NOT_ALLOWED,
                    f"HTTP {method.upper()} to {PACKAGES_URL} must return 405.",
                )

        # Disallowed on detail (only GET, PATCH, and DELETE are allowed)
        detail_url = package_detail_url(pkg.id)
        for method in ["post", "put"]:
            with self.subTest(endpoint=detail_url, http_method=method):
                client_method = getattr(self.client, method)
                response = client_method(detail_url)
                self.assertEqual(
                    response.status_code,
                    status.HTTP_405_METHOD_NOT_ALLOWED,
                    f"HTTP {method.upper()} to {detail_url} must return 405.",
                )

    def test_packages_endpoints_are_not_rate_limited(self):
        """Asserts package endpoints remain unthrottled during burst requests (API §22)."""
        owner = self._create_user(email="pkg.unthrottled@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")

        self._create_package(workspace=workspace, name="Unthrottled Package")

        self.client.force_authenticate(user=owner)

        # Burst of 25 GET list requests must all succeed with 200 (no 429)
        for i in range(25):
            get_response = self.client.get(PACKAGES_URL)
            self.assertEqual(
                get_response.status_code,
                status.HTTP_200_OK,
                f"GET request {i + 1} must not be throttled.",
            )
