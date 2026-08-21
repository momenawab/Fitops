"""API tests for Package activate/deactivate (Story 5.2).

Validates:
- Authorization: Coach/Owner per API §8 — an ACTIVE OWNER and an ACTIVE COACH are both allowed
- The 404 family: no membership, INACTIVE membership, SUSPENDED workspace and CLIENT-only are
  indistinguishable from each other
- Core behaviour: activate sets is_active True, deactivate sets it False, in the database
- Idempotency: repeating either call returns 200 and is not an error
- Only is_active changes — the other six fields are untouched
- Story 5.1 preservation: PATCH still accepts is_active and the list filter agrees
- Object isolation: a cross-workspace id is byte-identical to a non-existent id, never 403
- Method handling: only POST is allowed
- Architecture guards: coaching exposes {"Package"}, billing exposes no models
"""

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


def package_detail_url(pk) -> str:
    """Returns the detail URL for a package."""
    return f"{PACKAGES_URL}/{pk}"


def activate_url(pk) -> str:
    """Returns the activate URL for a package."""
    return f"{PACKAGES_URL}/{pk}/activate"


def deactivate_url(pk) -> str:
    """Returns the deactivate URL for a package."""
    return f"{PACKAGES_URL}/{pk}/deactivate"


class BasePackageStateTestCase(TestCase):
    """Base case providing a client, cache reset, model handles and entity factories."""

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

    def _owner_with_package(self, is_active=True):
        """Creates an authenticated ACTIVE OWNER and a package in their workspace."""
        user = self._create_user()
        workspace = self._create_workspace()
        self._create_membership(user=user, workspace=workspace, role="OWNER", status="ACTIVE")
        package = self._create_package(workspace=workspace, is_active=is_active)
        self.client.force_authenticate(user=user)
        return user, workspace, package

    def assert_error_envelope(self, response, expected_status, expected_code=None):
        """Asserts the API §2 error envelope; `fields` is only present for VALIDATION_ERROR."""
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


class PackageStateAuthorizationTests(BasePackageStateTestCase):
    """Verifies Coach/Owner authorization on both state endpoints."""

    def test_unauthenticated_activate_and_deactivate_are_rejected(self):
        """Asserts both routes reject an unauthenticated caller with the envelope."""
        package = self._create_package()
        for url in (activate_url(package.id), deactivate_url(package.id)):
            with self.subTest(url=url):
                response = self.client.post(url)
                self.assertIn(
                    response.status_code,
                    [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
                )
                self.assertEqual(set(response.json().keys()), {"error"})

    def test_active_owner_is_authorised_on_both_endpoints(self):
        """Asserts an ACTIVE OWNER receives 200 from activate and deactivate."""
        _, _, package = self._owner_with_package(is_active=False)
        self.assertEqual(self.client.post(activate_url(package.id)).status_code, status.HTTP_200_OK)
        self.assertEqual(
            self.client.post(deactivate_url(package.id)).status_code, status.HTTP_200_OK
        )

    def test_active_coach_is_authorised_on_both_endpoints(self):
        """Guards the Coach/Owner rule: a COACH receiving 403 here would be a regression.

        API §8 marks the Package block Coach/Owner, unlike Stories 4.2 and 4.3 which are
        OWNER-only. Tightening these endpoints to OWNER-only would lock out legitimate coaches.
        """
        user = self._create_user()
        workspace = self._create_workspace()
        self._create_membership(user=user, workspace=workspace, role="COACH", status="ACTIVE")
        package = self._create_package(workspace=workspace, is_active=False)
        self.client.force_authenticate(user=user)

        activate = self.client.post(activate_url(package.id))
        self.assertEqual(activate.status_code, status.HTTP_200_OK)
        self.assertIs(activate.json()["is_active"], True)

        deactivate = self.client.post(deactivate_url(package.id))
        self.assertEqual(deactivate.status_code, status.HTTP_200_OK)
        self.assertIs(deactivate.json()["is_active"], False)

    def test_four_unauthorized_scenarios_are_indistinguishable(self):
        """Asserts the four no-qualifying-membership cases return identical 404 responses.

        Compares the four real responses to each other rather than to an invented string, so a
        future change that distinguishes them fails immediately.
        """
        responses = []

        no_membership_user = self._create_user()
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)
        self.client.force_authenticate(user=no_membership_user)
        responses.append(self.client.post(activate_url(package.id)))

        inactive_user = self._create_user()
        inactive_ws = self._create_workspace()
        self._create_membership(
            user=inactive_user, workspace=inactive_ws, role="OWNER", status="INACTIVE"
        )
        inactive_pkg = self._create_package(workspace=inactive_ws)
        self.client.force_authenticate(user=inactive_user)
        responses.append(self.client.post(activate_url(inactive_pkg.id)))

        suspended_user = self._create_user()
        suspended_ws = self._create_workspace(status="SUSPENDED")
        self._create_membership(
            user=suspended_user, workspace=suspended_ws, role="OWNER", status="ACTIVE"
        )
        suspended_pkg = self._create_package(workspace=suspended_ws)
        self.client.force_authenticate(user=suspended_user)
        responses.append(self.client.post(activate_url(suspended_pkg.id)))

        client_user = self._create_user()
        client_ws = self._create_workspace()
        self._create_membership(
            user=client_user, workspace=client_ws, role="CLIENT", status="ACTIVE"
        )
        client_pkg = self._create_package(workspace=client_ws)
        self.client.force_authenticate(user=client_user)
        responses.append(self.client.post(activate_url(client_pkg.id)))

        first = responses[0]
        self.assertEqual(first.status_code, status.HTTP_404_NOT_FOUND)
        for other in responses[1:]:
            self.assertEqual(other.status_code, first.status_code)
            self.assertEqual(other.json()["error"]["code"], first.json()["error"]["code"])
            self.assertEqual(other.json()["error"]["message"], first.json()["error"]["message"])


class PackageStateCoreBehaviourTests(BasePackageStateTestCase):
    """Verifies the documented state transitions and response shape."""

    def test_activate_sets_is_active_true_in_database(self):
        """Asserts activate returns 200 with is_active true and persists it."""
        _, _, package = self._owner_with_package(is_active=False)
        response = self.client.post(activate_url(package.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIs(response.json()["is_active"], True)
        package.refresh_from_db()
        self.assertTrue(package.is_active)

    def test_deactivate_sets_is_active_false_in_database(self):
        """Asserts deactivate returns 200 with is_active false and persists it."""
        _, _, package = self._owner_with_package(is_active=True)
        response = self.client.post(deactivate_url(package.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIs(response.json()["is_active"], False)
        package.refresh_from_db()
        self.assertFalse(package.is_active)

    def test_activate_response_has_exactly_the_ten_documented_keys(self):
        """Asserts whole-key-set equality so a leaked extra field fails."""
        _, _, package = self._owner_with_package(is_active=False)
        response = self.client.post(activate_url(package.id))
        self.assertEqual(set(response.json().keys()), PACKAGE_KEYS)

    def test_deactivate_response_has_exactly_the_ten_documented_keys(self):
        """Asserts whole-key-set equality on the deactivate response."""
        _, _, package = self._owner_with_package(is_active=True)
        response = self.client.post(deactivate_url(package.id))
        self.assertEqual(set(response.json().keys()), PACKAGE_KEYS)

    def test_response_never_exposes_the_workspace_key(self):
        """Asserts the tenant id is never returned to the caller."""
        _, _, package = self._owner_with_package(is_active=False)
        body = self.client.post(activate_url(package.id)).content.decode()
        self.assertNotIn('"workspace"', body)


class PackageStateIdempotencyTests(BasePackageStateTestCase):
    """Verifies repeat calls are idempotent 200s rather than errors."""

    def test_activate_on_already_active_package_returns_200(self):
        """Asserts re-activating is a no-op 200, not a 409 or 400.

        No document defines an error for this case, so erroring would invent a semantic.
        """
        _, _, package = self._owner_with_package(is_active=True)
        response = self.client.post(activate_url(package.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIs(response.json()["is_active"], True)
        package.refresh_from_db()
        self.assertTrue(package.is_active)

    def test_deactivate_on_already_inactive_package_returns_200(self):
        """Asserts re-deactivating is a no-op 200, not a 409 or 400."""
        _, _, package = self._owner_with_package(is_active=False)
        response = self.client.post(deactivate_url(package.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIs(response.json()["is_active"], False)
        package.refresh_from_db()
        self.assertFalse(package.is_active)

    def test_repeated_activate_calls_remain_200(self):
        """Asserts three consecutive activate calls all return 200."""
        _, _, package = self._owner_with_package(is_active=False)
        for _ in range(3):
            self.assertEqual(
                self.client.post(activate_url(package.id)).status_code, status.HTTP_200_OK
            )


class PackageStateFieldIsolationTests(BasePackageStateTestCase):
    """Verifies these endpoints change only is_active."""

    def test_state_changes_leave_all_other_fields_untouched(self):
        """Guards against a blanket save clobbering unrelated fields.

        Captures the other six documented fields, round-trips deactivate then activate, and
        re-asserts every one of them from the database.
        """
        _, _, package = self._owner_with_package(is_active=True)
        before = {
            "name": package.name,
            "description": package.description,
            "price": package.price,
            "currency": package.currency,
            "duration_days": package.duration_days,
            "features": package.features,
        }

        self.assertEqual(
            self.client.post(deactivate_url(package.id)).status_code, status.HTTP_200_OK
        )
        self.assertEqual(self.client.post(activate_url(package.id)).status_code, status.HTTP_200_OK)

        package.refresh_from_db()
        for field, original in before.items():
            with self.subTest(field=field):
                self.assertEqual(getattr(package, field), original)


class PackageStateStoryFiftyOnePreservationTests(BasePackageStateTestCase):
    """Verifies Story 5.1 endpoints still behave as before."""

    def test_patch_still_accepts_is_active(self):
        """Asserts the state endpoints are an additional path, not a replacement."""
        _, _, package = self._owner_with_package(is_active=True)
        response = self.client.patch(
            package_detail_url(package.id), {"is_active": False}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIs(response.json()["is_active"], False)
        package.refresh_from_db()
        self.assertFalse(package.is_active)

    def test_get_detail_still_returns_the_ten_keys(self):
        """Asserts Story 5.1's detail contract is unchanged."""
        _, _, package = self._owner_with_package()
        response = self.client.get(package_detail_url(package.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(set(response.json().keys()), PACKAGE_KEYS)

    def test_list_filter_agrees_with_the_deactivate_endpoint(self):
        """Asserts a package deactivated via the endpoint appears under ?is_active=false."""
        _, _, package = self._owner_with_package(is_active=True)
        self.client.post(deactivate_url(package.id))

        response = self.client.get(f"{PACKAGES_URL}?is_active=false")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = [row["id"] for row in response.json()["results"]]
        self.assertIn(str(package.id), returned_ids)


class PackageStateObjectIsolationTests(BasePackageStateTestCase):
    """Verifies cross-workspace packages are invisible, never merely forbidden."""

    def _owner_and_foreign_package(self):
        """Creates an authenticated owner in workspace A and a package in workspace B."""
        owner = self._create_user()
        workspace_a = self._create_workspace()
        self._create_membership(user=owner, workspace=workspace_a, role="OWNER", status="ACTIVE")
        workspace_b = self._create_workspace()
        foreign = self._create_package(workspace=workspace_b, is_active=True)
        self.client.force_authenticate(user=owner)
        return foreign

    def test_activate_on_cross_workspace_package_returns_404_and_changes_nothing(self):
        """Asserts a foreign package is neither activated nor revealed."""
        foreign = self._owner_and_foreign_package()
        response = self.client.post(activate_url(foreign.id))
        self.assert_error_envelope(response, status.HTTP_404_NOT_FOUND, "NOT_FOUND")
        self.assertNotEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        foreign.refresh_from_db()
        self.assertTrue(foreign.is_active)

    def test_deactivate_on_cross_workspace_package_returns_404_and_changes_nothing(self):
        """Asserts a foreign package cannot be deactivated by another workspace's coach."""
        foreign = self._owner_and_foreign_package()
        response = self.client.post(deactivate_url(foreign.id))
        self.assert_error_envelope(response, status.HTTP_404_NOT_FOUND, "NOT_FOUND")
        foreign.refresh_from_db()
        self.assertTrue(foreign.is_active, "A cross-workspace deactivate must not take effect.")

    def test_cross_workspace_id_is_indistinguishable_from_a_random_uuid(self):
        """Guards tenant existence: the two responses must match exactly.

        Compares the two real responses to each other, never to an invented string.
        """
        foreign = self._owner_and_foreign_package()
        cross = self.client.post(deactivate_url(foreign.id))
        missing = self.client.post(deactivate_url(uuid.uuid4()))

        self.assertEqual(cross.status_code, missing.status_code)
        self.assertEqual(cross.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(cross.json()["error"]["code"], missing.json()["error"]["code"])
        self.assertEqual(cross.json()["error"]["message"], missing.json()["error"]["message"])

    def test_activate_cross_workspace_id_matches_random_uuid(self):
        """Asserts the same indistinguishability holds on the activate route."""
        foreign = self._owner_and_foreign_package()
        cross = self.client.post(activate_url(foreign.id))
        missing = self.client.post(activate_url(uuid.uuid4()))
        self.assertEqual(cross.status_code, missing.status_code)
        self.assertEqual(cross.json()["error"]["code"], missing.json()["error"]["code"])


class PackageStateMethodHandlingTests(BasePackageStateTestCase):
    """Verifies only POST is accepted on the state routes."""

    def test_non_post_methods_return_405(self):
        """Asserts GET, PATCH and DELETE are rejected on both routes."""
        _, _, package = self._owner_with_package()
        for url in (activate_url(package.id), deactivate_url(package.id)):
            for method in ("get", "patch", "delete"):
                with self.subTest(url=url, method=method):
                    response = getattr(self.client, method)(url)
                    self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class PackageStateArchitectureGuardTests(BasePackageStateTestCase):
    """Verifies no later-Epic model leaked in with this Story."""

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
