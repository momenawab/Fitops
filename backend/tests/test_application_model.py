"""Tests for the Application model schema contract, constraints, and scoping (Story 7.1).

Validates:
- Exact model location and registration under apps.applications (Point 1)
- Exact concrete field set specification (17 fields, set equality) (Point 2)
- UUID primary key typing and uniqueness (Point 3)
- Multi-tenant workspace scoping and cross-tenant query isolation (Point 4)
- Nullable User relationship for anonymous public submissions (Point 5)
- Status choices ({"SUBMITTED", "REVIEWING", "APPROVED", "REJECTED"}) and default (Point 6)
- Lifecycle status value persistence and round-tripping (Point 7)
- Required vs. optional field behavior and nullability contracts (Point 8)
- Unconstrained gender CharField with no choices (Point 9)
- High-precision DecimalField round-tripping for height and weight (Point 10)
- Automatic population and advancement of timestamps (Point 11)
- Foreign key relations to Workspace and Package, with PROTECT on package (Point 12)
- Architecture boundaries: applications defines only {Application}, commerce defines none (Point 13)
"""

import time
import uuid
from datetime import datetime
from decimal import Decimal

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import models
from django.db.models import ProtectedError
from django.test import TestCase
from django.utils import timezone

from common.models.tenant import WorkspaceScopedModel

EXPECTED_APPLICATION_FIELDS = {
    "id",
    "workspace",
    "package",
    "user",
    "status",
    "full_name",
    "email",
    "phone",
    "age",
    "gender",
    "height",
    "weight",
    "goal",
    "training_experience",
    "notes",
    "created_at",
    "updated_at",
}

EXPECTED_STATUS_CHOICES = {
    "SUBMITTED",
    "REVIEWING",
    "APPROVED",
    "REJECTED",
}


class BaseApplicationModelTestCase(TestCase):
    """Base test case providing model resolution, cache resets, and factory helpers."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.application_model = apps.get_model("applications", "Application")
        self.workspace_model = apps.get_model("workspaces", "Workspace")
        self.package_model = apps.get_model("coaching", "Package")
        self.user_model = get_user_model()

    def _create_user(self, email=None, password="SecurePassword123!", **kwargs):
        """Creates and returns an email-verified user instance."""
        if email is None:
            email = f"user-{uuid.uuid4().hex[:8]}@example.com"
        kwargs.setdefault("email_verified_at", timezone.now())
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

    def _create_application(self, workspace=None, package=None, **kwargs):
        """Creates and returns an Application instance with valid foreign keys."""
        if workspace is None:
            workspace = self._create_workspace()
        if package is None:
            package = self._create_package(workspace=workspace)
        unique_id = uuid.uuid4().hex[:8]
        defaults = {
            "workspace": workspace,
            "package": package,
            "full_name": f"Applicant {unique_id}",
            "email": f"applicant-{unique_id}@example.com",
        }
        defaults.update(kwargs)
        return self.application_model.objects.create(**defaults)


class ApplicationModelResolutionAndAppTests(BaseApplicationModelTestCase):
    """Verifies that the Application model is registered in the correct app (Point 1)."""

    def test_application_model_resolves_and_belongs_to_applications_app(self):
        """Asserts Application is registered under apps.applications with correct app label."""
        self.assertEqual(
            self.application_model._meta.app_label,
            "applications",
            "Application model must belong to the 'applications' app.",
        )
        self.assertEqual(
            self.application_model._meta.object_name,
            "Application",
            "Application model class name must be 'Application'.",
        )


class ApplicationSchemaFieldContractTests(BaseApplicationModelTestCase):
    """Verifies concrete field set specification, typing, and relationships (Points 2, 9, 12)."""

    def test_exact_concrete_field_set(self):
        """Asserts Application defines exactly the 17 approved concrete fields (Point 2)."""
        concrete_fields = {field.name for field in self.application_model._meta.concrete_fields}
        self.assertSetEqual(
            concrete_fields,
            EXPECTED_APPLICATION_FIELDS,
            "Application concrete fields must match authoritative DB Architecture §11A schema.",
        )

    def test_required_and_optional_fields_are_marked_correctly(self):
        """Locks the required/optional split, which no approved document specifies.

        Field types and nullability follow the approved Story 2.3 ClientProfile precedent for
        the same intake data — an explicit Master decision. `blank` has no ORM effect, so a
        change here is invisible to behavioural model tests, yet Story 7.2's submission
        serializer will inherit it directly from the model. Asserting it here is what stops
        a required field silently becoming optional between Stories.
        """
        required = {"full_name", "email"}
        optional = {
            "phone",
            "age",
            "gender",
            "height",
            "weight",
            "goal",
            "training_experience",
            "notes",
        }

        for name in sorted(required):
            with self.subTest(field=name):
                field = self.application_model._meta.get_field(name)
                self.assertFalse(field.blank, f"Application.{name} must be required (blank=False).")

        for name in sorted(optional):
            with self.subTest(field=name):
                field = self.application_model._meta.get_field(name)
                self.assertTrue(field.blank, f"Application.{name} must be optional (blank=True).")

    def test_gender_field_is_char_field_with_no_choices(self):
        """Asserts gender is a plain CharField without fixed choices or enums (Point 9)."""
        gender_field = self.application_model._meta.get_field("gender")
        self.assertEqual(
            gender_field.get_internal_type(),
            "CharField",
            "Application.gender must report internal type 'CharField'.",
        )
        self.assertFalse(
            gender_field.choices,
            "Application.gender must not define choices; gender is open-ended per ClientProfile.",
        )

    def test_gender_accepts_and_round_trips_arbitrary_string(self):
        """Asserts arbitrary string values persist and round-trip on gender (Point 9)."""
        custom_gender = "non-binary-custom-identity"
        application = self._create_application(gender=custom_gender)
        refetched = self.application_model.objects.get(pk=application.pk)
        self.assertEqual(
            refetched.gender,
            custom_gender,
            "Arbitrary gender string must round-trip without validation errors.",
        )

    def test_workspace_field_is_foreign_key_to_workspace_model(self):
        """Asserts workspace is a non-null ForeignKey to Workspace model (Point 12)."""
        workspace_field = self.application_model._meta.get_field("workspace")
        self.assertEqual(
            workspace_field.get_internal_type(),
            "ForeignKey",
            "Application.workspace must report internal type 'ForeignKey'.",
        )
        self.assertEqual(
            workspace_field.related_model,
            self.workspace_model,
            "Application.workspace must target the Workspace model.",
        )
        self.assertFalse(
            workspace_field.null,
            "Application.workspace must be required (null=False).",
        )
        self.assertEqual(
            workspace_field.remote_field.on_delete,
            models.CASCADE,
            "Application.workspace on_delete must be models.CASCADE.",
        )

    def test_package_field_is_foreign_key_to_package_model(self):
        """Asserts package is a non-null ForeignKey to Package model (Point 12)."""
        package_field = self.application_model._meta.get_field("package")
        self.assertEqual(
            package_field.get_internal_type(),
            "ForeignKey",
            "Application.package must report internal type 'ForeignKey'.",
        )
        self.assertEqual(
            package_field.related_model,
            self.package_model,
            "Application.package must target the Package model.",
        )
        self.assertFalse(
            package_field.null,
            "Application.package must be required (null=False).",
        )
        self.assertEqual(
            package_field.remote_field.on_delete,
            models.PROTECT,
            "Application.package on_delete must be models.PROTECT.",
        )

    def test_deleting_a_package_with_applications_is_refused(self):
        """Guards applicant history: a package with applications cannot be hard-deleted.

        No approved document states an on_delete for Application.package, so this is an
        explicit Master decision. PROTECT is chosen over CASCADE because Story 5.1 made
        DELETE /packages/{id} a HARD delete, and API §8 says to "prefer soft deletion/archive
        when the package has historical orders" — the specs already treat destroying a package
        with downstream history as the thing to avoid. Under CASCADE a single hard delete would
        silently erase Application rows, which DB §11A calls first-class business records
        belonging to real applicants. PROTECT refuses the delete instead of destroying them.
        """
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)
        self._create_application(workspace=workspace, package=package)

        with self.assertRaises(ProtectedError):
            package.delete()

        self.assertTrue(self.package_model.objects.filter(pk=package.pk).exists())

    def test_a_package_without_applications_can_still_be_deleted(self):
        """Asserts PROTECT does not block deleting an unreferenced package (Story 5.1)."""
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)

        package.delete()

        self.assertFalse(self.package_model.objects.filter(pk=package.pk).exists())

    def test_application_package_reads_back_associated_package(self):
        """Asserts saved application reads back the exact associated package (Point 12)."""
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)
        application = self._create_application(workspace=workspace, package=package)

        refetched = self.application_model.objects.get(pk=application.pk)
        self.assertEqual(refetched.package, package)
        self.assertEqual(refetched.package_id, package.id)


class ApplicationPrimaryKeyTests(BaseApplicationModelTestCase):
    """Verifies UUID primary key typing, uniqueness, and configuration (Point 3)."""

    def test_id_field_is_uuid_primary_key(self):
        """Guards architectural rule: primary key must be UUIDField, not BigAutoField.

        WorkspaceScopedModel does NOT provide a primary key. A model subclass that omits
        an explicit primary key definition will silently receive an autoincrementing
        BigAutoField, violating API §25 Rule 13 (UUIDs for externally exposed identifiers).
        """
        pk_field = self.application_model._meta.pk
        self.assertTrue(
            pk_field.primary_key,
            "Application.id must be configured as a primary key.",
        )
        self.assertEqual(
            pk_field.get_internal_type(),
            "UUIDField",
            "Application.id must report internal type 'UUIDField', never BigAutoField.",
        )

    def test_saved_instance_id_is_uuid_instance(self):
        """Asserts saved application instance receives a valid uuid.UUID identifier."""
        application = self._create_application()
        self.assertIsInstance(
            application.pk,
            uuid.UUID,
            "Application.pk must be an instance of uuid.UUID.",
        )
        self.assertIsInstance(
            application.id,
            uuid.UUID,
            "Application.id must be an instance of uuid.UUID.",
        )

    def test_two_saved_applications_receive_distinct_uuid_ids(self):
        """Asserts distinct application instances receive distinct UUID primary keys."""
        app1 = self._create_application()
        app2 = self._create_application()
        self.assertNotEqual(
            app1.id,
            app2.id,
            "Two distinct Application instances must receive different UUID primary keys.",
        )


class ApplicationWorkspaceScopingTests(BaseApplicationModelTestCase):
    """Verifies WorkspaceScopedModel inheritance and cross-tenant isolation (Point 4)."""

    def test_is_subclass_of_workspace_scoped_model(self):
        """Guards architectural rule: Application must inherit from WorkspaceScopedModel."""
        self.assertTrue(
            issubclass(self.application_model, WorkspaceScopedModel),
            "Application must be a subclass of WorkspaceScopedModel.",
        )

    def test_manager_for_workspace_filters_strictly_by_workspace(self):
        """Guards cross-tenant isolation: for_workspace returns only target workspace records.

        Tenant isolation is a non-negotiable invariant. Applications created in Workspace A
        must never leak into queries scoped to Workspace B.
        """
        ws1 = self._create_workspace(slug="tenant-alpha")
        ws2 = self._create_workspace(slug="tenant-beta")
        pkg1 = self._create_package(workspace=ws1)
        pkg2 = self._create_package(workspace=ws2)

        app1 = self._create_application(workspace=ws1, package=pkg1)
        app2 = self._create_application(workspace=ws1, package=pkg1)
        app3 = self._create_application(workspace=ws2, package=pkg2)

        ws1_apps = self.application_model.objects.for_workspace(ws1)
        ws2_apps = self.application_model.objects.for_workspace(ws2)
        ws1_ids = set(ws1_apps.values_list("id", flat=True))
        ws2_ids = set(ws2_apps.values_list("id", flat=True))

        self.assertSetEqual(
            ws1_ids,
            {app1.id, app2.id},
            "for_workspace(ws1) must return exactly the applications belonging to Workspace 1.",
        )
        self.assertSetEqual(
            ws2_ids,
            {app3.id},
            "for_workspace(ws2) must return exactly the applications belonging to Workspace 2.",
        )
        self.assertNotIn(
            app3.id,
            ws1_ids,
            "Cross-tenant isolation failure: Workspace 2 application appeared in Workspace 1.",
        )
        self.assertNotIn(
            app1.id,
            ws2_ids,
            "Cross-tenant isolation failure: Workspace 1 application appeared in Workspace 2.",
        )


class ApplicationUserRelationshipTests(BaseApplicationModelTestCase):
    """Verifies nullable User foreign key supporting anonymous and logged-in users (Point 5)."""

    def test_user_field_is_nullable(self):
        """Guards anonymous submission: user field must be nullable (null=True).

        Per DB Architecture §11A, public coaching applications originate from
        anonymous visitors who do not yet possess a user account on FitOps.
        """
        user_field = self.application_model._meta.get_field("user")
        self.assertTrue(
            user_field.null,
            "Application.user must be nullable (null=True) to allow anonymous applications.",
        )
        self.assertEqual(
            user_field.get_internal_type(),
            "ForeignKey",
            "Application.user must report internal type 'ForeignKey'.",
        )
        self.assertEqual(
            user_field.related_model,
            self.user_model,
            "Application.user must target the AUTH_USER_MODEL.",
        )

    def test_application_saves_and_persists_with_user_none(self):
        """Asserts an Application saves successfully with user=None for anonymous visitors."""
        application = self._create_application(user=None)
        self.assertIsNotNone(application.pk)

        refetched = self.application_model.objects.get(pk=application.pk)
        self.assertIsNone(
            refetched.user,
            "Application.user must read back as None when created anonymously.",
        )
        self.assertIsNone(
            refetched.user_id,
            "Application.user_id must read back as None when created anonymously.",
        )

    def test_application_saves_and_persists_with_authenticated_user(self):
        """Asserts an Application can be associated with an existing User instance."""
        user = self._create_user()
        application = self._create_application(user=user)

        refetched = self.application_model.objects.get(pk=application.pk)
        self.assertEqual(
            refetched.user,
            user,
            "Application.user must match the associated User instance.",
        )
        self.assertEqual(
            refetched.user_id,
            user.id,
            "Application.user_id must match the associated User id.",
        )


class ApplicationStatusAndLifecycleTests(BaseApplicationModelTestCase):
    """Verifies status choices, default value, and lifecycle round-tripping (Points 6, 7)."""

    def test_status_choices_exact_set(self):
        """Asserts status choices are exactly the four documented values (Point 6)."""
        status_field = self.application_model._meta.get_field("status")
        stored_choices = {
            choice[0] if isinstance(choice, (list, tuple)) else choice
            for choice in status_field.choices
        }
        self.assertSetEqual(
            stored_choices,
            EXPECTED_STATUS_CHOICES,
            "Application.status choices must be exactly the four documented values.",
        )

    def test_status_defaults_to_submitted_on_creation(self):
        """Asserts creating an Application without status defaults to SUBMITTED (Point 6)."""
        status_field = self.application_model._meta.get_field("status")
        default_val = (
            status_field.default.value
            if hasattr(status_field.default, "value")
            else status_field.default
        )
        self.assertEqual(
            default_val,
            "SUBMITTED",
            "Application.status default must be 'SUBMITTED'.",
        )

        application = self._create_application()
        refetched = self.application_model.objects.get(pk=application.pk)
        self.assertEqual(
            refetched.status,
            "SUBMITTED",
            "Application saved without explicit status must default to 'SUBMITTED'.",
        )

    def test_all_documented_lifecycle_statuses_round_trip(self):
        """Asserts each documented lifecycle status can be saved and read back (Point 7)."""
        for expected_status in ("SUBMITTED", "REVIEWING", "APPROVED", "REJECTED"):
            with self.subTest(status=expected_status):
                application = self._create_application(status=expected_status)
                refetched = self.application_model.objects.get(pk=application.pk)
                self.assertEqual(
                    refetched.status,
                    expected_status,
                    f"Application status '{expected_status}' must persist and round-trip.",
                )


class ApplicationFieldNullabilityAndDefaultsTests(BaseApplicationModelTestCase):
    """Verifies required vs optional fields and database nullability contracts (Point 8)."""

    def test_minimal_application_creation_with_only_required_fields(self):
        """Asserts application saves with required fields; optionals default to empty or None."""
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)
        application = self.application_model.objects.create(
            workspace=workspace,
            package=package,
            full_name="Jane Doe",
            email="jane.doe@example.com",
        )
        self.assertIsNotNone(application.pk)

        refetched = self.application_model.objects.get(pk=application.pk)
        self.assertEqual(refetched.full_name, "Jane Doe")
        self.assertEqual(refetched.email, "jane.doe@example.com")

        # Optional text fields must default to empty strings
        self.assertEqual(refetched.phone, "")
        self.assertEqual(refetched.gender, "")
        self.assertEqual(refetched.goal, "")
        self.assertEqual(refetched.training_experience, "")
        self.assertEqual(refetched.notes, "")

        # Optional numeric and foreign key fields must default to None
        self.assertIsNone(refetched.age)
        self.assertIsNone(refetched.height)
        self.assertIsNone(refetched.weight)
        self.assertIsNone(refetched.user)
        self.assertIsNone(refetched.user_id)

    def test_full_application_creation_with_all_optional_fields_populated(self):
        """Asserts application persists and round-trips all optional fields when populated."""
        user = self._create_user()
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)
        application = self.application_model.objects.create(
            workspace=workspace,
            package=package,
            user=user,
            status="REVIEWING",
            full_name="Alex Morgan",
            email="alex.morgan@example.com",
            phone="+1234567890",
            age=29,
            gender="non-binary",
            height=Decimal("175.50"),
            weight=Decimal("72.25"),
            goal="Hypertrophy and strength",
            training_experience="4 years consistent weightlifting",
            notes="Prefers 4-day upper/lower split.",
        )

        refetched = self.application_model.objects.get(pk=application.pk)
        self.assertEqual(refetched.full_name, "Alex Morgan")
        self.assertEqual(refetched.email, "alex.morgan@example.com")
        self.assertEqual(refetched.phone, "+1234567890")
        self.assertEqual(refetched.age, 29)
        self.assertEqual(refetched.gender, "non-binary")
        self.assertEqual(refetched.height, Decimal("175.50"))
        self.assertEqual(refetched.weight, Decimal("72.25"))
        self.assertEqual(refetched.goal, "Hypertrophy and strength")
        self.assertEqual(refetched.training_experience, "4 years consistent weightlifting")
        self.assertEqual(refetched.notes, "Prefers 4-day upper/lower split.")
        self.assertEqual(refetched.user, user)
        self.assertEqual(refetched.status, "REVIEWING")


class ApplicationNumericPrecisionTests(BaseApplicationModelTestCase):
    """Verifies precise DecimalField round-tripping for height and weight (Point 10)."""

    def test_height_and_weight_decimal_precision_round_trip(self):
        """Asserts height and weight round-trip precisely as Decimals with no float drift."""
        test_height = Decimal("180.50")
        test_weight = Decimal("85.25")
        application = self._create_application(
            height=test_height,
            weight=test_weight,
        )

        refetched = self.application_model.objects.get(pk=application.pk)
        self.assertEqual(
            refetched.height,
            test_height,
            "Application.height must equal Decimal('180.50') exactly with no float drift.",
        )
        self.assertEqual(
            refetched.weight,
            test_weight,
            "Application.weight must equal Decimal('85.25') exactly with no float drift.",
        )
        self.assertIsInstance(
            refetched.height,
            Decimal,
            "Application.height must be an instance of Decimal.",
        )
        self.assertIsInstance(
            refetched.weight,
            Decimal,
            "Application.weight must be an instance of Decimal.",
        )


class ApplicationTimestampBehaviorTests(BaseApplicationModelTestCase):
    """Verifies timestamp initialization and auto-updating behavior (Point 11)."""

    def test_created_at_and_updated_at_populated_on_insert(self):
        """Asserts created_at and updated_at are populated datetime instances on creation."""
        before_create = timezone.now()
        application = self._create_application()

        self.assertIsNotNone(application.created_at)
        self.assertIsNotNone(application.updated_at)
        self.assertIsInstance(application.created_at, datetime)
        self.assertIsInstance(application.updated_at, datetime)
        self.assertGreaterEqual(
            application.created_at,
            before_create,
            "created_at must be greater than or equal to timestamp captured before creation.",
        )
        self.assertGreaterEqual(
            application.updated_at,
            before_create,
            "updated_at must be greater than or equal to timestamp captured before creation.",
        )

    def test_updated_at_advances_on_save_while_created_at_is_preserved(self):
        """Asserts updated_at advances on subsequent save while created_at remains constant."""
        application = self._create_application(notes="Initial applicant notes.")
        initial_created_at = application.created_at
        initial_updated_at = application.updated_at

        time.sleep(0.01)
        application.notes = "Updated applicant notes after coach evaluation."
        application.save()
        application.refresh_from_db()

        self.assertEqual(
            application.created_at,
            initial_created_at,
            "created_at must remain constant across subsequent updates.",
        )
        self.assertGreater(
            application.updated_at,
            initial_updated_at,
            "updated_at must advance to a later timestamp on subsequent save.",
        )


class ApplicationArchitectureGuardTests(TestCase):
    """Verifies architectural boundaries across applications and commerce apps (Point 13)."""

    def test_applications_app_exposes_exactly_application_model(self):
        """Guards architectural boundary: applications app must define only Application.

        Per ERD §19A, Order remains in commerce; the applications app invokes the Order
        creation flow rather than owning the Order model.
        """
        applications_app = apps.get_app_config("applications")
        concrete_model_names = {model._meta.object_name for model in applications_app.get_models()}
        self.assertSetEqual(
            concrete_model_names,
            {"Application"},
            "applications app must define exactly {'Application'}; no Order or other model.",
        )

    def test_commerce_app_exposes_only_the_order_model(self):
        """Guards the applications/commerce boundary: commerce owns Order and nothing more.

        This assertion originally read "commerce defines no models", which was correct while
        Epic 08 had not started — it existed to stop Story 7.1 pulling Order forward. Epic 08
        Story 8.1 has since landed the Order model legitimately, so the guard was narrowed
        rather than deleted: it now pins the boundary at exactly {"Order"}, which still fails
        loudly if Payment or Subscription (Stories 8.3+) appear early, and still fails if the
        applications app ever grows an Order of its own.
        """
        commerce_app = apps.get_app_config("commerce")
        concrete_model_names = {model._meta.object_name for model in commerce_app.get_models()}
        self.assertSetEqual(
            concrete_model_names,
            {"Order"},
            "commerce must expose exactly Order until Stories 8.3+ add Payment/Subscription.",
        )
