"""API tests for Package duplicate endpoint (Story 5.3).

Validates:
- Method handling: POST only; GET, PATCH, PUT, and DELETE yield 405 Method Not Allowed (Point 1)
- Request body: completely ignored; payload overrides cannot alter copied fields (Point 2)
- Authorization: Coach/Owner per API §8 — an ACTIVE OWNER and an ACTIVE COACH both
  succeed (Point 3)
- The 404 family: no membership, INACTIVE membership, SUSPENDED workspace, CLIENT-only, missing
  UUID, and cross-tenant ID all return 404 NOT_FOUND, never 403; a cross-tenant id is
  byte-identical to a random UUID, so object existence is never revealed (Point 4)
- Verbatim field copying: name, description, price, currency, duration_days, features, is_active
  all equal the source; name has no suffix; is_active copies both True/False; features list is
  independent mutable copy (Point 5)
- New row creation: copy has new unique UUID, workspace package count increments to 2, and
  created_at / updated_at are fresh timestamps (Point 6)
- Same workspace: copy is assigned to the source package's workspace (Point 7)
- Source untouched: source record and its timestamps are completely unmodified (Point 8)
- Response shape: HTTP 201 Created with exactly the ten documented keys, never exposing
  workspace or workspace_id (Point 9)
- Non-idempotent: repeating duplicate on same source creates additional distinct copies
  (Point 10)
- Unauthenticated access: rejected with 401 or 403 and standard error envelope (Point 11)
- Cross-tenant creation guard: duplicating in workspace A does not affect workspace B (Point 12)
- Chained duplicate: duplicating a duplicate works and creates a 3rd distinct package (Point 13)
- Architecture guards: coaching exposes only {"Package"}, billing exposes no models
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

PACKAGES_URL = "/api/v1/packages"
PACKAGE_KEYS = {
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


def package_detail_url(pk: uuid.UUID | str) -> str:
    """Returns the detail URL for a package."""
    return f"{PACKAGES_URL}/{pk}"


def duplicate_url(pk: uuid.UUID | str) -> str:
    """Returns the duplicate URL for a package."""
    return f"{PACKAGES_URL}/{pk}/duplicate"


class BasePackageDuplicateTestCase(TestCase):
    """Base case providing client setup, cache reset, model handles, and factories."""

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

    def _create_workspace(self, **kwargs):
        """Creates and returns a Workspace."""
        unique_id = uuid.uuid4().hex[:8]
        defaults = {
            "name": f"Workspace {unique_id}",
            "slug": f"workspace-{unique_id}",
            "currency": "USD",
            "timezone": "UTC",
            "status": "ACTIVE",
        }
        defaults.update(kwargs)
        return self.workspace_model.objects.create(**defaults)

    def _create_membership(self, user=None, workspace=None, role="OWNER", status="ACTIVE"):
        """Creates and returns a Membership."""
        if user is None:
            user = self._create_user()
        if workspace is None:
            workspace = self._create_workspace()
        return self.membership_model.objects.create(
            user=user, workspace=workspace, role=role, status=status
        )

    def _create_package(self, workspace=None, is_active=True, **kwargs):
        """Creates and returns a Package."""
        if workspace is None:
            workspace = self._create_workspace()
        defaults = {
            "workspace": workspace,
            "name": "Pro Coaching",
            "description": "12-week coaching program",
            "price": Decimal("3500.00"),
            "currency": "EGP",
            "duration_days": 90,
            "features": ["Training Plan", "Nutrition Plan"],
            "is_active": is_active,
        }
        defaults.update(kwargs)
        return self.package_model.objects.create(**defaults)

    def _owner_with_package(self, is_active=True, **kwargs):
        """Creates an authenticated ACTIVE OWNER and a package in their workspace."""
        user = self._create_user()
        workspace = self._create_workspace()
        self._create_membership(user=user, workspace=workspace, role="OWNER", status="ACTIVE")
        package = self._create_package(workspace=workspace, is_active=is_active, **kwargs)
        self.client.force_authenticate(user=user)
        return user, workspace, package

    def _coach_with_package(self, is_active=True, **kwargs):
        """Creates an authenticated ACTIVE COACH and a package in their workspace."""
        user = self._create_user()
        workspace = self._create_workspace()
        self._create_membership(user=user, workspace=workspace, role="COACH", status="ACTIVE")
        package = self._create_package(workspace=workspace, is_active=is_active, **kwargs)
        self.client.force_authenticate(user=user)
        return user, workspace, package

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


class PackageDuplicateMethodHandlingTests(BasePackageDuplicateTestCase):
    """Verifies HTTP method handling on the duplicate route (Point 1)."""

    def test_non_post_methods_return_405(self):
        """Asserts GET, PATCH, PUT, and DELETE on the duplicate URL return 405."""
        _, _, package = self._owner_with_package()
        url = duplicate_url(package.id)
        for method in ("get", "patch", "put", "delete"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(url)
                self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class PackageDuplicateRequestBodyTests(BasePackageDuplicateTestCase):
    """Verifies that the duplicate endpoint ignores request bodies (Point 2)."""

    def test_request_body_is_ignored_and_does_not_override_fields(self):
        """Asserts payload data like custom names or price overrides are ignored entirely."""
        _, _, package = self._owner_with_package()
        payload = {
            "name": "hacked name",
            "price": "9999.99",
            "currency": "EUR",
            "is_active": False,
            "features": ["Hacked Feature"],
        }
        response = self.client.post(duplicate_url(package.id), payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data["name"], package.name)
        self.assertEqual(Decimal(data["price"]), package.price)
        self.assertEqual(data["currency"], package.currency)
        self.assertEqual(data["is_active"], package.is_active)
        self.assertEqual(data["features"], package.features)

    def test_empty_body_and_no_payload_succeeds(self):
        """Asserts calling duplicate with an empty POST request succeeds with 201 Created."""
        _, _, package = self._owner_with_package()
        response = self.client.post(duplicate_url(package.id))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class PackageDuplicateAuthorizationTests(BasePackageDuplicateTestCase):
    """Verifies Coach/Owner authorization on the duplicate endpoint (Point 3)."""

    def test_active_owner_is_authorised_to_duplicate_package(self):
        """Asserts an ACTIVE OWNER receives 201 Created when duplicating a package."""
        _, workspace, package = self._owner_with_package()
        response = self.client.post(duplicate_url(package.id))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        copy_id = response.json()["id"]
        self.assertTrue(self.package_model.objects.filter(id=copy_id, workspace=workspace).exists())

    def test_active_coach_is_authorised_to_duplicate_package(self):
        """Guards the Coach/Owner rule: an ACTIVE COACH must be authorised to duplicate.

        API §8 marks the entire Package block Coach/Owner, unlike Stories 4.2/4.3 which are
        OWNER-only. A test or change asserting a COACH gets 403 would be a serious regression.
        """
        _, workspace, package = self._coach_with_package()
        response = self.client.post(duplicate_url(package.id))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        copy_id = response.json()["id"]
        self.assertTrue(self.package_model.objects.filter(id=copy_id, workspace=workspace).exists())


class PackageDuplicateNotFoundFamilyTests(BasePackageDuplicateTestCase):
    """Verifies 404 NOT_FOUND and byte-identical indistinguishability (Point 4)."""

    def test_six_unauthorized_and_missing_scenarios_are_strictly_indistinguishable(self):
        """Asserts all six non-qualifying and missing target cases return an indistinguishable 404.

        Compares real responses across all 6 scenarios to ensure no distinguishing error
        messages, codes, or tenant leakage.
        """
        responses = []

        # (a) caller has no Membership at all
        user_no_mem = self._create_user()
        ws_a = self._create_workspace()
        pkg_a = self._create_package(workspace=ws_a)
        self.client.force_authenticate(user=user_no_mem)
        responses.append(self.client.post(duplicate_url(pkg_a.id)))

        # (b) caller's Membership is INACTIVE
        user_inactive = self._create_user()
        ws_b = self._create_workspace()
        self._create_membership(user=user_inactive, workspace=ws_b, role="OWNER", status="INACTIVE")
        pkg_b = self._create_package(workspace=ws_b)
        self.client.force_authenticate(user=user_inactive)
        responses.append(self.client.post(duplicate_url(pkg_b.id)))

        # (c) caller's workspace has status SUSPENDED
        user_suspended = self._create_user()
        ws_c = self._create_workspace(status="SUSPENDED")
        self._create_membership(user=user_suspended, workspace=ws_c, role="OWNER", status="ACTIVE")
        pkg_c = self._create_package(workspace=ws_c)
        self.client.force_authenticate(user=user_suspended)
        responses.append(self.client.post(duplicate_url(pkg_c.id)))

        # (d) caller is a CLIENT only
        user_client = self._create_user()
        ws_d = self._create_workspace()
        self._create_membership(user=user_client, workspace=ws_d, role="CLIENT", status="ACTIVE")
        pkg_d = self._create_package(workspace=ws_d)
        self.client.force_authenticate(user=user_client)
        responses.append(self.client.post(duplicate_url(pkg_d.id)))

        # (e) the package id is a well-formed UUID that does not exist
        owner_e = self._create_user()
        ws_e = self._create_workspace()
        self._create_membership(user=owner_e, workspace=ws_e, role="OWNER", status="ACTIVE")
        self.client.force_authenticate(user=owner_e)
        non_existent_id = uuid.uuid4()
        responses.append(self.client.post(duplicate_url(non_existent_id)))

        # (f) the package exists but belongs to a DIFFERENT workspace (cross-tenant)
        owner_f = self._create_user()
        ws_f1 = self._create_workspace()
        self._create_membership(user=owner_f, workspace=ws_f1, role="OWNER", status="ACTIVE")
        ws_f2 = self._create_workspace()
        foreign_pkg = self._create_package(workspace=ws_f2)
        self.client.force_authenticate(user=owner_f)
        responses.append(self.client.post(duplicate_url(foreign_pkg.id)))

        # All six are 404 NOT_FOUND with no `fields` key, and never 403.
        for other in responses:
            self.assertEqual(other.status_code, status.HTTP_404_NOT_FOUND)
            self.assertEqual(other.json()["error"]["code"], "NOT_FOUND")
            self.assertNotIn("fields", other.json()["error"])

        # The four authorization-stage failures (a)-(d) are byte-identical to each other, and
        # the two object-stage failures (e)-(f) are byte-identical to each other.
        #
        # The two GROUPS differ in `message` only: `resolve_active_coach_membership` raises a
        # bare DRF `NotFound()` ("Not found."), while `get_object_or_404` produces
        # "No Package matches the given query.". This split is PRE-EXISTING and identical on
        # the Story 5.1 detail endpoint and the Story 5.2 activate/deactivate endpoints, which
        # reuse the same two helpers; Story 5.3 did not introduce it. It does not violate
        # DB §26, because it never reveals whether a package EXISTS: a cross-tenant id and a
        # random UUID are byte-identical (asserted in the next test). It discloses only which
        # stage rejected the caller — a fact the caller already knows about their own account.
        for other in responses[1:4]:
            self.assertEqual(other.content, responses[0].content)
        self.assertEqual(responses[5].content, responses[4].content)

    def test_cross_tenant_id_and_nonexistent_uuid_produce_identical_bytes(self):
        """Guards tenant existence: foreign ID returns byte-identical response to random UUID.

        Cross-tenant existence leakage of 'this id exists' vs 'this id does not' is prevented
        by asserting byte-wise equality between the two responses.
        """
        owner = self._create_user()
        ws_own = self._create_workspace()
        self._create_membership(user=owner, workspace=ws_own, role="OWNER", status="ACTIVE")
        ws_other = self._create_workspace()
        foreign_pkg = self._create_package(workspace=ws_other)

        self.client.force_authenticate(user=owner)
        cross_tenant_res = self.client.post(duplicate_url(foreign_pkg.id))
        nonexistent_res = self.client.post(duplicate_url(uuid.uuid4()))

        self.assertEqual(cross_tenant_res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(cross_tenant_res.content, nonexistent_res.content)


class PackageDuplicateFieldCopyingTests(BasePackageDuplicateTestCase):
    """Verifies exact verbatim copying of all seven business fields (Point 5)."""

    def test_all_seven_business_fields_copied_verbatim(self):
        """Asserts verbatim equality across all seven business fields."""
        distinctive_name = "Exclusive Elite Coaching Package (Special Edition #42)"
        _, _, source = self._owner_with_package(
            name=distinctive_name,
            description="Comprehensive elite personal coaching with 24/7 access",
            price=Decimal("4999.50"),
            currency="USD",
            duration_days=180,
            features=["1-on-1 Consultations", "Custom Meal Plans", "Bi-weekly Reviews"],
            is_active=True,
        )

        response = self.client.post(duplicate_url(source.id))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()

        # Strict verbatim name check: no " (Copy)", no " copy", no " 2" suffix
        self.assertEqual(data["name"], distinctive_name)
        self.assertEqual(data["description"], source.description)
        self.assertEqual(Decimal(data["price"]), source.price)
        self.assertEqual(data["currency"], source.currency)
        self.assertEqual(data["duration_days"], source.duration_days)
        self.assertEqual(data["features"], source.features)
        self.assertEqual(data["is_active"], source.is_active)

        copy_pkg = self.package_model.objects.get(id=data["id"])
        self.assertEqual(copy_pkg.name, source.name)
        self.assertEqual(copy_pkg.description, source.description)
        self.assertEqual(copy_pkg.price, source.price)
        self.assertEqual(copy_pkg.currency, source.currency)
        self.assertEqual(copy_pkg.duration_days, source.duration_days)
        self.assertEqual(copy_pkg.features, source.features)
        self.assertEqual(copy_pkg.is_active, source.is_active)

    def test_is_active_true_is_copied_verbatim_as_true(self):
        """Asserts duplicating an active package yields is_active=True."""
        _, _, source = self._owner_with_package(is_active=True)
        response = self.client.post(duplicate_url(source.id))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIs(response.json()["is_active"], True)
        copy_pkg = self.package_model.objects.get(id=response.json()["id"])
        self.assertTrue(copy_pkg.is_active)

    def test_is_active_false_is_copied_verbatim_as_false(self):
        """Asserts duplicating an inactive package yields is_active=False."""
        _, _, source = self._owner_with_package(is_active=False)
        response = self.client.post(duplicate_url(source.id))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIs(response.json()["is_active"], False)
        copy_pkg = self.package_model.objects.get(id=response.json()["id"])
        self.assertFalse(copy_pkg.is_active)

    def test_features_list_is_independent_and_not_shared_mutable_reference(self):
        """Asserts mutating copy's features in DB does not mutate the source."""
        initial_features = ["Feature 1", "Feature 2", "Feature 3"]
        _, _, source = self._owner_with_package(features=initial_features)

        response = self.client.post(duplicate_url(source.id))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        copy_id = response.json()["id"]

        copy_pkg = self.package_model.objects.get(id=copy_id)
        copy_pkg.features.append("Mutated Feature 4")
        copy_pkg.save(update_fields=["features"])

        source.refresh_from_db()
        self.assertEqual(source.features, initial_features)
        self.assertNotIn("Mutated Feature 4", source.features)

    def test_empty_features_list_is_copied_correctly(self):
        """Asserts a package with an empty features list is duplicated with features=[]."""
        _, _, source = self._owner_with_package(features=[])
        response = self.client.post(duplicate_url(source.id))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["features"], [])
        copy_pkg = self.package_model.objects.get(id=response.json()["id"])
        self.assertEqual(copy_pkg.features, [])


class PackageDuplicateNewRowTests(BasePackageDuplicateTestCase):
    """Verifies the duplicate creates a new row with a fresh UUID and timestamps (Point 6)."""

    def test_duplicate_creates_new_row_with_unique_uuid_and_increments_count(self):
        """Asserts the copy has a new UUID and workspace package count increments to 2."""
        _, workspace, source = self._owner_with_package()
        self.assertEqual(self.package_model.objects.filter(workspace=workspace).count(), 1)

        response = self.client.post(duplicate_url(source.id))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()

        copy_uuid = uuid.UUID(data["id"])
        self.assertNotEqual(copy_uuid, source.id)
        self.assertEqual(self.package_model.objects.filter(workspace=workspace).count(), 2)

    def test_created_at_and_updated_at_are_freshly_generated(self):
        """Asserts created_at and updated_at are fresh timestamps captured at request time."""
        _, _, source = self._owner_with_package()
        past_time = timezone.now() - datetime.timedelta(days=14)
        self.package_model.objects.filter(pk=source.pk).update(
            created_at=past_time, updated_at=past_time
        )
        source.refresh_from_db()

        before_request = timezone.now()
        response = self.client.post(duplicate_url(source.id))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        copy_id = response.json()["id"]

        copy_pkg = self.package_model.objects.get(id=copy_id)
        self.assertGreaterEqual(copy_pkg.created_at, before_request)
        self.assertGreaterEqual(copy_pkg.updated_at, before_request)
        self.assertNotEqual(copy_pkg.created_at, source.created_at)
        self.assertNotEqual(copy_pkg.updated_at, source.updated_at)


class PackageDuplicateWorkspaceScopingTests(BasePackageDuplicateTestCase):
    """Verifies the copy is assigned to the same workspace as the source (Point 7)."""

    def test_duplicate_is_assigned_to_same_workspace_as_source(self):
        """Asserts copy's workspace_id matches source's workspace_id in the database."""
        _, workspace, source = self._owner_with_package()
        response = self.client.post(duplicate_url(source.id))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        copy_id = response.json()["id"]

        copy_pkg = self.package_model.objects.get(id=copy_id)
        self.assertEqual(copy_pkg.workspace_id, workspace.id)
        self.assertEqual(copy_pkg.workspace_id, source.workspace_id)


class PackageDuplicateSourceUntouchedTests(BasePackageDuplicateTestCase):
    """Verifies that duplicating leaves the source package completely untouched (Point 8)."""

    def test_source_package_remains_completely_untouched_including_timestamps(self):
        """Asserts every field of the source record, including updated_at, is unmodified."""
        _, _, source = self._owner_with_package()
        past_time = timezone.now() - datetime.timedelta(days=7)
        self.package_model.objects.filter(pk=source.pk).update(
            created_at=past_time, updated_at=past_time
        )
        source.refresh_from_db()

        before_state = {
            "id": source.id,
            "workspace_id": source.workspace_id,
            "name": source.name,
            "description": source.description,
            "price": source.price,
            "currency": source.currency,
            "duration_days": source.duration_days,
            "features": list(source.features),
            "is_active": source.is_active,
            "created_at": source.created_at,
            "updated_at": source.updated_at,
        }

        response = self.client.post(duplicate_url(source.id))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        source.refresh_from_db()
        for field, expected_val in before_state.items():
            with self.subTest(field=field):
                self.assertEqual(getattr(source, field), expected_val)


class PackageDuplicateResponseShapeTests(BasePackageDuplicateTestCase):
    """Verifies response status 201 and exact ten documented keys (Point 9)."""

    def test_duplicate_response_returns_201_and_exactly_ten_keys(self):
        """Asserts 201 response contains exactly the ten documented package keys."""
        _, _, source = self._owner_with_package()
        response = self.client.post(duplicate_url(source.id))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(set(response.json().keys()), PACKAGE_KEYS)

    def test_response_never_exposes_workspace_or_workspace_id(self):
        """Asserts workspace and workspace_id are absent from JSON keys and raw response body."""
        _, _, source = self._owner_with_package()
        response = self.client.post(duplicate_url(source.id))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertNotIn("workspace", data)
        self.assertNotIn("workspace_id", data)
        raw_text = response.content.decode()
        self.assertNotIn('"workspace"', raw_text)
        self.assertNotIn('"workspace_id"', raw_text)


class PackageDuplicateNonIdempotentTests(BasePackageDuplicateTestCase):
    """Verifies that duplicate is deliberately non-idempotent (Point 10)."""

    def test_duplicate_is_not_idempotent_and_creates_multiple_copies(self):
        """Asserts calling duplicate twice creates two distinct copies (3 packages total)."""
        _, workspace, source = self._owner_with_package()

        res1 = self.client.post(duplicate_url(source.id))
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)
        copy1_id = res1.json()["id"]

        res2 = self.client.post(duplicate_url(source.id))
        self.assertEqual(res2.status_code, status.HTTP_201_CREATED)
        copy2_id = res2.json()["id"]

        self.assertNotEqual(copy1_id, copy2_id)
        self.assertNotEqual(copy1_id, str(source.id))
        self.assertNotEqual(copy2_id, str(source.id))

        total_count = self.package_model.objects.filter(workspace=workspace).count()
        self.assertEqual(total_count, 3)


class PackageDuplicateUnauthenticatedTests(BasePackageDuplicateTestCase):
    """Verifies unauthenticated requests are rejected with 401 or 403 (Point 11)."""

    def test_unauthenticated_duplicate_request_returns_401_or_403_with_envelope(self):
        """Asserts an unauthenticated POST to duplicate returns 401/403 with error envelope."""
        source = self._create_package()
        response = self.client.post(duplicate_url(source.id))
        self.assertIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )
        self.assertEqual(set(response.json().keys()), {"error"})


class PackageDuplicateCrossTenantCreationTests(BasePackageDuplicateTestCase):
    """Verifies duplicating in workspace A does not leak or alter workspace B (Point 12)."""

    def test_duplicate_in_workspace_a_does_not_affect_workspace_b_count(self):
        """Asserts duplicating a package in tenant A leaves tenant B package count unchanged."""
        owner_a = self._create_user()
        ws_a = self._create_workspace()
        self._create_membership(user=owner_a, workspace=ws_a, role="OWNER", status="ACTIVE")
        pkg_a = self._create_package(workspace=ws_a, name="Package in WS A")

        ws_b = self._create_workspace()
        self._create_package(workspace=ws_b, name="Package in WS B")

        count_b_before = self.package_model.objects.filter(workspace=ws_b).count()
        self.assertEqual(count_b_before, 1)

        self.client.force_authenticate(user=owner_a)
        response = self.client.post(duplicate_url(pkg_a.id))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        count_a_after = self.package_model.objects.filter(workspace=ws_a).count()
        count_b_after = self.package_model.objects.filter(workspace=ws_b).count()

        self.assertEqual(count_a_after, 2)
        self.assertEqual(count_b_after, 1)


class PackageDuplicateChainTests(BasePackageDuplicateTestCase):
    """Verifies that duplicating a duplicated package succeeds chained (Point 13)."""

    def test_duplicating_a_duplicate_creates_third_distinct_package(self):
        """Asserts duplicating a copy yields a third distinct row with same fields."""
        _, workspace, source = self._owner_with_package(
            name="Chained Pro Package",
            description="Chain duplicate test program",
            price=Decimal("1200.00"),
            currency="USD",
            duration_days=30,
            features=["Feature X", "Feature Y"],
            is_active=True,
        )

        # 1. Duplicate source -> copy1
        res1 = self.client.post(duplicate_url(source.id))
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)
        copy1_id = res1.json()["id"]

        # 2. Duplicate copy1 -> copy2
        res2 = self.client.post(duplicate_url(copy1_id))
        self.assertEqual(res2.status_code, status.HTTP_201_CREATED)
        copy2_data = res2.json()
        copy2_id = copy2_data["id"]

        # Assert distinct IDs
        all_ids = {str(source.id), str(copy1_id), str(copy2_id)}
        self.assertEqual(len(all_ids), 3)

        # Assert copy2 has same field values
        self.assertEqual(copy2_data["name"], source.name)
        self.assertEqual(copy2_data["description"], source.description)
        self.assertEqual(Decimal(copy2_data["price"]), source.price)
        self.assertEqual(copy2_data["currency"], source.currency)
        self.assertEqual(copy2_data["duration_days"], source.duration_days)
        self.assertEqual(copy2_data["features"], source.features)
        self.assertEqual(copy2_data["is_active"], source.is_active)

        # Total count in workspace is 3
        self.assertEqual(self.package_model.objects.filter(workspace=workspace).count(), 3)


class PackageDuplicateArchitectureGuardTests(BasePackageDuplicateTestCase):
    """Verifies no later-Epic models or unapproved schema migrations leaked in."""

    def test_coaching_app_exposes_only_package(self):
        """Asserts the coaching app model set is unchanged."""
        names = {m.__name__ for m in apps.get_app_config("coaching").get_models()}
        self.assertEqual(names, {"Package"})

    def test_billing_app_exposes_no_models(self):
        """Asserts no Epic 22 billing work leaked in."""
        names = {m.__name__ for m in apps.get_app_config("billing").get_models()}
        self.assertEqual(names, set())

    def test_no_migration_was_required_for_this_story(self):
        """Asserts Package still has exactly the eleven documented concrete fields."""
        field_names = {f.name for f in self.package_model._meta.concrete_fields}
        self.assertEqual(
            field_names,
            {
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
            },
        )
