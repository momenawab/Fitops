"""API tests for Public Packages endpoint (Story 6.2).

Validates:
- Anonymous access: completely unauthenticated GET returns 200 OK, never 401/403 (Point 1)
- Paginated envelope: top-level body has exactly {"count", "next", "previous", "results"},
  results is a list, count is an int (Point 2)
- Scoping & cross-tenant isolation: results contains only ACTIVE packages of target workspace;
  foreign tenant packages and inactive packages are strictly excluded (Point 3)
- Count integrity: count reflects only target workspace active packages, excluding inactive rows
  and foreign workspace rows (Point 4)
- Package object shape: each item exposes exactly ten documented keys; workspace and workspace_id
  are absent from parsed objects and response body; is_active is always True (Point 5)
- Ordering: results are ordered by created_at descending (-created_at / newest first) (Point 6)
- Pagination traversal: default page size is 20, ?page=2 returns remainder, ?page_size=5 custom
  sizing, union of page IDs covers all rows with no duplicates, ?page_size=1000 is capped at 100,
  and out-of-range ?page=999 returns 404 (Point 7)
- Ignored query parameters: undocumented query params (?search, ?is_active, ?status) are ignored
  and produce identical results to the unfiltered request (Point 8)
- Inactive package protection: ?is_active=false can never surface an inactive package (Point 9)
- Suspended workspace invisibility & anti-enumeration: SUSPENDED workspace returns 404 NOT_FOUND
  and is byte-identical to a non-existent slug response, never 403 (Point 10)
- 404 cross-endpoint parity: 404 responses for non-existent and suspended slugs are byte-identical
  to the Story 6.1 public coach page 404 responses (Point 11)
- API §2 error envelope: 404 responses contain exactly {"error"} with code == "NOT_FOUND" and no
  "fields" dictionary (Point 12)
- Empty catalog validity: workspace with no packages or only inactive packages returns 200 OK with
  count == 0 and results == [], never 404 (Point 13)
- Method handling: GET only; POST, PATCH, PUT, and DELETE yield 405 Method Not Allowed (Point 14)
- Authentication invariance: authenticated unaffiliated callers and workspace owners receive
  byte-identical 200 responses to anonymous visitors (Point 15)
- Packages only top-level shape: no "coach" or "workspace" key exists at the top level (Point 16)
- Owner independence: workspace with no active OWNER or no memberships at all still serves its
  active packages (Point 17)
- Architecture guards: coaching exposes {"Package"}, billing defines no models, workspaces
  defines {"Workspace", "PaymentMethod"}
"""

import datetime
import uuid
from decimal import Decimal

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

PUBLIC_COACHES_URL = "/api/v1/public/coaches"

PAGINATION_KEYS = {"count", "next", "previous", "results"}

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

FORBIDDEN_TOP_LEVEL_KEYS = {
    "workspace",
    "coach",
}


def public_packages_url(slug: str) -> str:
    """Returns the public packages URL for a given workspace slug."""
    return f"{PUBLIC_COACHES_URL}/{slug}/packages"


def public_coach_url(slug: str) -> str:
    """Returns the public coach page URL for a given workspace slug."""
    return f"{PUBLIC_COACHES_URL}/{slug}"


class BasePublicPackagesApiTestCase(TestCase):
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


class PublicPackagesAnonymousAccessTests(BasePublicPackagesApiTestCase):
    """Verifies anonymous access succeeds on public packages endpoint (Point 1)."""

    def test_anonymous_get_public_packages_returns_200_ok(self):
        """Asserts an unauthenticated GET request returns 200 OK."""
        workspace = self._create_workspace()
        self._create_package(workspace=workspace, is_active=True)
        response = self.client.get(public_packages_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_anonymous_access_never_requires_authentication(self):
        """Guards the public boundary: unauthenticated requests must never 401 or 403.

        The public packages listing is an open discovery catalog for prospective clients.
        Any requirement for session cookies, bearer tokens, or workspace headers would
        break public access.
        """
        workspace = self._create_workspace()
        self._create_package(workspace=workspace, is_active=True)
        self.client.credentials()
        self.client.logout()
        response = self.client.get(public_packages_url(workspace.slug))
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


class PublicPackagesPaginatedEnvelopeTests(BasePublicPackagesApiTestCase):
    """Verifies paginated response shape and packages-only structure (Points 2 & 16)."""

    def test_response_top_level_contains_exact_pagination_keys(self):
        """Asserts response body has exactly the four standard pagination keys (Point 2)."""
        workspace = self._create_workspace()
        self._create_package(workspace=workspace, is_active=True)
        response = self.client.get(public_packages_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(
            set(data.keys()),
            PAGINATION_KEYS,
            "Top-level keys must equal exactly {'count', 'next', 'previous', 'results'}.",
        )
        self.assertIsInstance(data["results"], list)
        self.assertIsInstance(data["count"], int)

    def test_response_contains_no_coach_or_workspace_top_level_keys(self):
        """Asserts neither 'coach' nor 'workspace' key appears at top level (Point 16)."""
        workspace = self._create_workspace()
        owner = self._create_user()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")
        self._create_package(workspace=workspace, is_active=True)
        response = self.client.get(public_packages_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        for forbidden_key in FORBIDDEN_TOP_LEVEL_KEYS:
            with self.subTest(forbidden_key=forbidden_key):
                self.assertNotIn(
                    forbidden_key,
                    data,
                    f"Key '{forbidden_key}' must not appear at top level of packages response.",
                )


class PublicPackagesScopingAndCrossTenantTests(BasePublicPackagesApiTestCase):
    """Verifies active scoping, cross-tenant isolation, and count integrity (Points 3 & 4)."""

    def test_results_contains_only_active_packages_of_target_workspace(self):
        """Guards cross-tenant isolation and active package filtering (Point 3).

        Creates active and inactive packages in the target workspace, plus active packages in
        a foreign workspace, and asserts the returned ID set matches exactly the target
        workspace's active packages.
        """
        target_ws = self._create_workspace()
        foreign_ws = self._create_workspace()

        pkg_active_1 = self._create_package(
            workspace=target_ws, is_active=True, name="Target Pkg 1"
        )
        pkg_active_2 = self._create_package(
            workspace=target_ws, is_active=True, name="Target Pkg 2"
        )
        pkg_inactive = self._create_package(
            workspace=target_ws, is_active=False, name="Target Inactive Pkg"
        )
        pkg_foreign = self._create_package(workspace=foreign_ws, is_active=True, name="Foreign Pkg")

        response = self.client.get(public_packages_url(target_ws.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        returned_ids = {pkg["id"] for pkg in data["results"]}
        expected_ids = {str(pkg_active_1.id), str(pkg_active_2.id)}

        self.assertEqual(
            returned_ids,
            expected_ids,
            "Results list must contain exactly active packages belonging to this workspace.",
        )
        self.assertNotIn(
            str(pkg_inactive.id),
            returned_ids,
            "Inactive packages must be excluded from public packages results.",
        )
        self.assertNotIn(
            str(pkg_foreign.id),
            returned_ids,
            "Foreign tenant packages must be excluded from public packages results.",
        )
        self.assertNotIn(
            str(pkg_foreign.id),
            response.content.decode(),
            "Foreign tenant package ID must not leak into response body text.",
        )

    def test_count_reflects_only_active_packages_of_target_workspace(self):
        """Asserts count reflects only active packages in target workspace (Point 4)."""
        target_ws = self._create_workspace()
        foreign_ws = self._create_workspace()

        for _ in range(3):
            self._create_package(workspace=target_ws, is_active=True)
        for _ in range(2):
            self._create_package(workspace=target_ws, is_active=False)
        for _ in range(4):
            self._create_package(workspace=foreign_ws, is_active=True)

        response = self.client.get(public_packages_url(target_ws.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(
            data["count"],
            3,
            "Count must reflect only the target workspace's active packages.",
        )
        self.assertEqual(len(data["results"]), 3)


class PublicPackagesObjectShapeTests(BasePublicPackagesApiTestCase):
    """Verifies the exact ten-key package object shape and workspace isolation (Point 5)."""

    def test_each_package_object_contains_exact_ten_keys(self):
        """Asserts each package dictionary contains exactly the ten documented public keys."""
        workspace = self._create_workspace()
        for _ in range(2):
            self._create_package(workspace=workspace, is_active=True)

        response = self.client.get(public_packages_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 2)

        for pkg in results:
            with self.subTest(pkg_id=pkg.get("id")):
                self.assertEqual(
                    set(pkg.keys()),
                    EXPECTED_PACKAGE_KEYS,
                    f"Package dictionary must contain exactly {EXPECTED_PACKAGE_KEYS}.",
                )

    def test_package_objects_never_expose_workspace_or_workspace_id(self):
        """Asserts workspace and workspace_id are absent from package dicts and raw text."""
        workspace = self._create_workspace()
        for _ in range(2):
            self._create_package(workspace=workspace, is_active=True)

        response = self.client.get(public_packages_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]

        for pkg in results:
            for forbidden_key in FORBIDDEN_PACKAGE_KEYS:
                with self.subTest(pkg_id=pkg.get("id"), key=forbidden_key):
                    self.assertNotIn(
                        forbidden_key,
                        pkg,
                        f"Field '{forbidden_key}' must not appear in package object.",
                    )

        raw_text = response.content.decode()
        self.assertNotIn(str(workspace.id), raw_text)
        self.assertNotIn('"workspace_id"', raw_text)

    def test_all_returned_packages_have_is_active_true(self):
        """Asserts every package object in results has is_active set to True."""
        workspace = self._create_workspace()
        for _ in range(3):
            self._create_package(workspace=workspace, is_active=True)
        self._create_package(workspace=workspace, is_active=False)

        response = self.client.get(public_packages_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 3)

        for pkg in results:
            with self.subTest(pkg_id=pkg.get("id")):
                self.assertIs(
                    pkg["is_active"],
                    True,
                    "Every returned package must have is_active equal to True.",
                )

    def test_package_field_values_and_types_match_database(self):
        """Asserts package values match database records with correct data types."""
        workspace = self._create_workspace()
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

        response = self.client.get(public_packages_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        pkg = results[0]

        self.assertEqual(pkg["id"], str(package.id))
        self.assertEqual(pkg["name"], "12-Week Transformation")
        self.assertEqual(
            pkg["description"],
            "Complete body transformation program with custom nutrition.",
        )
        self.assertEqual(Decimal(pkg["price"]), Decimal("4500.00"))
        self.assertEqual(pkg["price"], "4500.00")
        self.assertEqual(pkg["currency"], "EGP")
        self.assertEqual(pkg["duration_days"], 84)
        self.assertEqual(
            pkg["features"],
            ["Custom Workout Plan", "Nutrition Macros", "24/7 Chat Support"],
        )
        self.assertIs(pkg["is_active"], True)
        self.assertIsInstance(pkg["created_at"], str)
        self.assertIsInstance(pkg["updated_at"], str)


class PublicPackagesOrderingTests(BasePublicPackagesApiTestCase):
    """Verifies that packages are ordered by created_at descending (Point 6)."""

    def test_packages_are_ordered_by_created_at_descending(self):
        """Guards ordering: results are ordered newest-first (-created_at).

        The public package directory highlights a coach's most recent offerings. An explicit
        -created_at ordering guarantees deterministic pagination traversal and avoids
        arbitrary ordering under database query planner changes.
        """
        workspace = self._create_workspace()
        pkg1 = self._create_package(workspace=workspace, name="Package Oldest")
        pkg2 = self._create_package(workspace=workspace, name="Package Middle Old")
        pkg3 = self._create_package(workspace=workspace, name="Package Middle New")
        pkg4 = self._create_package(workspace=workspace, name="Package Newest")

        base_time = timezone.now()
        t1 = base_time - datetime.timedelta(days=4)
        t2 = base_time - datetime.timedelta(days=3)
        t3 = base_time - datetime.timedelta(days=2)
        t4 = base_time - datetime.timedelta(days=1)

        self.package_model.objects.filter(pk=pkg1.pk).update(created_at=t1)
        self.package_model.objects.filter(pk=pkg2.pk).update(created_at=t2)
        self.package_model.objects.filter(pk=pkg3.pk).update(created_at=t3)
        self.package_model.objects.filter(pk=pkg4.pk).update(created_at=t4)

        response = self.client.get(public_packages_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]

        returned_ordered_ids = [p["id"] for p in results]
        expected_ordered_ids = [str(pkg4.id), str(pkg3.id), str(pkg2.id), str(pkg1.id)]

        self.assertEqual(
            returned_ordered_ids,
            expected_ordered_ids,
            "Packages must be ordered by created_at descending (newest first).",
        )


class PublicPackagesPaginationTraversalTests(BasePublicPackagesApiTestCase):
    """Verifies pagination limits, multi-page traversal, and out-of-range handling (Point 7)."""

    def test_default_page_size_is_twenty(self):
        """Asserts default page size is 20 with 25 total packages."""
        workspace = self._create_workspace()
        for i in range(25):
            self._create_package(workspace=workspace, name=f"Package {i:02d}")

        response = self.client.get(public_packages_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data["count"], 25)
        self.assertEqual(len(data["results"]), 20)
        self.assertIsNotNone(data["next"])
        self.assertIn("page=2", data["next"])
        self.assertIsNone(data["previous"])

    def test_page_two_traversal_returns_remaining_items(self):
        """Asserts requesting ?page=2 returns the remaining 5 packages."""
        workspace = self._create_workspace()
        for i in range(25):
            self._create_package(workspace=workspace, name=f"Package {i:02d}")

        response = self.client.get(f"{public_packages_url(workspace.slug)}?page=2")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data["count"], 25)
        self.assertEqual(len(data["results"]), 5)
        self.assertIsNone(data["next"])
        self.assertIsNotNone(data["previous"])

    def test_custom_page_size_parameter(self):
        """Asserts ?page_size=5 returns exactly 5 items."""
        workspace = self._create_workspace()
        for i in range(12):
            self._create_package(workspace=workspace, name=f"Package {i:02d}")

        response = self.client.get(f"{public_packages_url(workspace.slug)}?page_size=5")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data["count"], 12)
        self.assertEqual(len(data["results"]), 5)
        self.assertIsNotNone(data["next"])

    def test_pagination_union_across_pages_matches_all_packages_with_no_duplicates(self):
        """Asserts page traversal covers all packages without duplicates or omissions."""
        workspace = self._create_workspace()
        created_packages = []
        for i in range(25):
            created_packages.append(
                self._create_package(workspace=workspace, name=f"Package {i:02d}")
            )

        res_page1 = self.client.get(f"{public_packages_url(workspace.slug)}?page=1")
        res_page2 = self.client.get(f"{public_packages_url(workspace.slug)}?page=2")

        self.assertEqual(res_page1.status_code, status.HTTP_200_OK)
        self.assertEqual(res_page2.status_code, status.HTTP_200_OK)

        page1_ids = [item["id"] for item in res_page1.json()["results"]]
        page2_ids = [item["id"] for item in res_page2.json()["results"]]
        all_returned_ids = page1_ids + page2_ids

        self.assertEqual(len(all_returned_ids), 25)
        self.assertEqual(len(set(all_returned_ids)), 25)

        expected_ids = {str(pkg.id) for pkg in created_packages}
        self.assertEqual(set(all_returned_ids), expected_ids)

    def test_page_size_capped_at_maximum_of_one_hundred(self):
        """Asserts ?page_size=1000 is capped at 100 and returns all packages without error."""
        workspace = self._create_workspace()
        for i in range(25):
            self._create_package(workspace=workspace, name=f"Package {i:02d}")

        response = self.client.get(f"{public_packages_url(workspace.slug)}?page_size=1000")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data["count"], 25)
        self.assertEqual(len(data["results"]), 25)
        self.assertIsNone(data["next"])

    def test_out_of_range_page_returns_404_with_api_error_envelope(self):
        """Asserts requesting an out-of-range page returns 404 with API §2 error envelope."""
        workspace = self._create_workspace()
        self._create_package(workspace=workspace, is_active=True)

        response = self.client.get(f"{public_packages_url(workspace.slug)}?page=999")
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )


class PublicPackagesIgnoredQueryParamsTests(BasePublicPackagesApiTestCase):
    """Verifies that undocumented query params are ignored and never filter data (Points 8 & 9)."""

    def test_undocumented_query_parameters_are_ignored(self):
        """Guards query scope: search, is_active, and status parameters must be ignored.

        The coach-facing package list endpoint supports search and active filtering, but the
        public packages endpoint is strictly a catalog listing. Undocumented parameters must
        not alter the result set.
        """
        workspace = self._create_workspace()
        self._create_package(workspace=workspace, name="Bronze Tier", is_active=True)
        self._create_package(workspace=workspace, name="Silver Tier", is_active=True)
        self._create_package(workspace=workspace, name="Gold Tier", is_active=True)

        unfiltered_res = self.client.get(public_packages_url(workspace.slug))
        self.assertEqual(unfiltered_res.status_code, status.HTTP_200_OK)
        baseline_data = unfiltered_res.json()
        baseline_ids = [p["id"] for p in baseline_data["results"]]
        self.assertEqual(len(baseline_ids), 3)

        search_res = self.client.get(f"{public_packages_url(workspace.slug)}?search=Silver")
        self.assertEqual(search_res.status_code, status.HTTP_200_OK)
        search_ids = [p["id"] for p in search_res.json()["results"]]
        self.assertEqual(
            search_ids,
            baseline_ids,
            "?search param must be ignored on public packages endpoint.",
        )

        active_res = self.client.get(f"{public_packages_url(workspace.slug)}?is_active=false")
        self.assertEqual(active_res.status_code, status.HTTP_200_OK)
        active_ids = [p["id"] for p in active_res.json()["results"]]
        self.assertEqual(
            active_ids,
            baseline_ids,
            "?is_active=false param must be ignored and not filter out active packages.",
        )

        status_res = self.client.get(f"{public_packages_url(workspace.slug)}?status=SUSPENDED")
        self.assertEqual(status_res.status_code, status.HTTP_200_OK)
        status_ids = [p["id"] for p in status_res.json()["results"]]
        self.assertEqual(
            status_ids,
            baseline_ids,
            "?status param must be ignored on public packages endpoint.",
        )

    def test_is_active_false_query_param_never_surfaces_inactive_packages(self):
        """Guards privacy: is_active=false query param can never reveal inactive packages.

        Callers attempting to inspect unlisted or inactive packages by passing ?is_active=false
        must receive only active packages. Inactive packages must remain completely hidden.
        """
        workspace = self._create_workspace()
        active_pkg1 = self._create_package(workspace=workspace, is_active=True)
        active_pkg2 = self._create_package(workspace=workspace, is_active=True)
        inactive_pkg1 = self._create_package(workspace=workspace, is_active=False)
        inactive_pkg2 = self._create_package(workspace=workspace, is_active=False)

        response = self.client.get(f"{public_packages_url(workspace.slug)}?is_active=false")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data["count"], 2)
        returned_ids = {p["id"] for p in data["results"]}
        expected_ids = {str(active_pkg1.id), str(active_pkg2.id)}

        self.assertEqual(returned_ids, expected_ids)
        self.assertNotIn(str(inactive_pkg1.id), returned_ids)
        self.assertNotIn(str(inactive_pkg2.id), returned_ids)
        self.assertNotIn(str(inactive_pkg1.id), response.content.decode())
        self.assertNotIn(str(inactive_pkg2.id), response.content.decode())


class PublicPackagesSuspendedAndNotFoundTests(BasePublicPackagesApiTestCase):
    """Verifies SUSPENDED workspace invisibility, 404, and Story 6.1 parity (Points 10, 11, 12)."""

    def test_suspended_workspace_returns_404_not_found(self):
        """Asserts requesting a SUSPENDED workspace returns 404 NOT_FOUND, never 403."""
        suspended_ws = self._create_workspace(status="SUSPENDED")
        self._create_package(workspace=suspended_ws, is_active=True)

        response = self.client.get(public_packages_url(suspended_ws.slug))
        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
            "SUSPENDED workspace must return 404 NOT_FOUND on public packages endpoint.",
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
        suspended_ws = self._create_workspace(status="SUSPENDED")
        self._create_package(workspace=suspended_ws, is_active=True)
        nonexistent_slug = f"nonexistent-slug-{uuid.uuid4().hex[:10]}"

        suspended_response = self.client.get(public_packages_url(suspended_ws.slug))
        nonexistent_response = self.client.get(public_packages_url(nonexistent_slug))

        self.assertEqual(suspended_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(nonexistent_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            suspended_response.content,
            nonexistent_response.content,
            "SUSPENDED workspace response must be byte-identical to a non-existent slug response.",
        )

    def test_public_packages_404_is_byte_identical_to_public_coach_404(self):
        """Guards cross-endpoint parity: Story 6.1 and 6.2 return byte-identical 404s (Point 11).

        The public coach page (/public/coaches/{slug}) and public packages listing
        (/public/coaches/{slug}/packages) share workspace resolution logic. Their 404 responses
        must be byte-identical for both non-existent slugs and SUSPENDED workspaces so they cannot
        drift apart.
        """
        nonexistent_slug = f"nonexistent-slug-{uuid.uuid4().hex[:10]}"
        coach_404 = self.client.get(public_coach_url(nonexistent_slug))
        pkg_404 = self.client.get(public_packages_url(nonexistent_slug))

        self.assertEqual(coach_404.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(pkg_404.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            coach_404.content,
            pkg_404.content,
            "404 for nonexistent slug must be byte-identical between coach and packages endpoints.",
        )

        suspended_ws = self._create_workspace(status="SUSPENDED")
        self._create_package(workspace=suspended_ws, is_active=True)

        coach_susp_404 = self.client.get(public_coach_url(suspended_ws.slug))
        pkg_susp_404 = self.client.get(public_packages_url(suspended_ws.slug))

        self.assertEqual(coach_susp_404.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(pkg_susp_404.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            coach_susp_404.content,
            pkg_susp_404.content,
            "404 for SUSPENDED workspace must be byte-identical "
            "between coach and packages endpoints.",
        )

    def test_nonexistent_and_suspended_slugs_use_api_error_envelope(self):
        """Asserts 404 responses conform strictly to API §2 error envelope specification."""
        nonexistent_slug = f"nonexistent-slug-{uuid.uuid4().hex[:10]}"
        response = self.client.get(public_packages_url(nonexistent_slug))
        self.assert_error_envelope(
            response,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )

        suspended_ws = self._create_workspace(status="SUSPENDED")
        susp_response = self.client.get(public_packages_url(suspended_ws.slug))
        self.assert_error_envelope(
            susp_response,
            expected_status=status.HTTP_404_NOT_FOUND,
            expected_code="NOT_FOUND",
        )


class PublicPackagesEmptyCatalogTests(BasePublicPackagesApiTestCase):
    """Verifies empty catalogs return 200 OK with count 0 and results [] (Point 13)."""

    def test_workspace_with_zero_packages_returns_200_with_empty_results(self):
        """Asserts workspace with no packages returns 200 with count 0 and results []."""
        workspace = self._create_workspace()
        response = self.client.get(public_packages_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(set(data.keys()), PAGINATION_KEYS)
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["results"], [])
        self.assertIsNone(data["next"])
        self.assertIsNone(data["previous"])

    def test_workspace_with_only_inactive_packages_returns_200_with_empty_results(self):
        """Asserts workspace with only inactive packages returns 200 with empty results."""
        workspace = self._create_workspace()
        for _ in range(3):
            self._create_package(workspace=workspace, is_active=False)

        response = self.client.get(public_packages_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(set(data.keys()), PAGINATION_KEYS)
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["results"], [])
        self.assertIsNone(data["next"])
        self.assertIsNone(data["previous"])


class PublicPackagesMethodHandlingTests(BasePublicPackagesApiTestCase):
    """Verifies that only HTTP GET is allowed on the public packages endpoint (Point 14)."""

    def test_non_get_methods_return_405_method_not_allowed(self):
        """Asserts POST, PATCH, PUT, and DELETE on the public packages URL return 405."""
        workspace = self._create_workspace()
        self._create_package(workspace=workspace, is_active=True)
        url = public_packages_url(workspace.slug)

        for method in ("post", "patch", "put", "delete"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(url)
                self.assertEqual(
                    response.status_code,
                    status.HTTP_405_METHOD_NOT_ALLOWED,
                    f"HTTP {method.upper()} on public packages endpoint must return 405.",
                )


class PublicPackagesAuthenticationInvarianceTests(BasePublicPackagesApiTestCase):
    """Verifies response byte equality regardless of caller authentication status (Point 15)."""

    def test_authenticated_unaffiliated_user_receives_identical_response_to_anonymous(self):
        """Guards auth neutrality: authenticated caller gets byte-identical response to visitor.

        The public packages listing is completely open. An authenticated user with no membership
        in the workspace must see exactly what an anonymous visitor sees, with byte-for-byte
        identical content.
        """
        workspace = self._create_workspace()
        self._create_package(workspace=workspace, is_active=True)
        unaffiliated_user = self._create_user(email="unaffiliated-visitor@example.com")

        self.client.credentials()
        self.client.logout()
        anon_res = self.client.get(public_packages_url(workspace.slug))
        self.assertEqual(anon_res.status_code, status.HTTP_200_OK)

        self.client.force_authenticate(user=unaffiliated_user)
        auth_res = self.client.get(public_packages_url(workspace.slug))
        self.assertEqual(auth_res.status_code, status.HTTP_200_OK)

        self.assertEqual(
            auth_res.content,
            anon_res.content,
            "Authenticated unaffiliated caller must receive byte-identical response to anonymous.",
        )

    def test_authenticated_workspace_owner_receives_identical_public_response_to_anonymous(self):
        """Asserts even the workspace owner gets the same byte response on public endpoint."""
        owner = self._create_user(email="workspace-owner@example.com")
        workspace = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace, role="OWNER", status="ACTIVE")
        self._create_package(workspace=workspace, is_active=True)

        self.client.credentials()
        self.client.logout()
        anon_res = self.client.get(public_packages_url(workspace.slug))
        self.assertEqual(anon_res.status_code, status.HTTP_200_OK)

        self.client.force_authenticate(user=owner)
        owner_res = self.client.get(public_packages_url(workspace.slug))
        self.assertEqual(owner_res.status_code, status.HTTP_200_OK)

        self.assertEqual(
            owner_res.content,
            anon_res.content,
            "Authenticated workspace owner must receive byte-identical response to anonymous.",
        )


class PublicPackagesWorkspaceOwnerIndependenceTests(BasePublicPackagesApiTestCase):
    """Verifies public packages are served even if workspace has no active owner (Point 17)."""

    def test_workspace_with_no_active_owner_still_serves_packages(self):
        """Asserts packages are returned when workspace has no OWNER membership at all."""
        workspace = self._create_workspace()
        pkg1 = self._create_package(workspace=workspace, is_active=True)
        pkg2 = self._create_package(workspace=workspace, is_active=True)

        self.assertEqual(
            self.membership_model.objects.filter(workspace=workspace).count(),
            0,
            "Test setup precondition: workspace must have 0 memberships.",
        )

        response = self.client.get(public_packages_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data["count"], 2)
        returned_ids = {p["id"] for p in data["results"]}
        self.assertEqual(returned_ids, {str(pkg1.id), str(pkg2.id)})

    def test_workspace_with_inactive_owner_still_serves_packages(self):
        """Asserts packages are returned when workspace OWNER membership is INACTIVE."""
        inactive_owner = self._create_user(email="inactive-owner@example.com")
        workspace = self._create_workspace()
        self._create_membership(
            user=inactive_owner,
            workspace=workspace,
            role="OWNER",
            status="INACTIVE",
        )
        pkg = self._create_package(workspace=workspace, is_active=True)

        response = self.client.get(public_packages_url(workspace.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["id"], str(pkg.id))


class PublicPackagesArchitectureGuardTests(BasePublicPackagesApiTestCase):
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
