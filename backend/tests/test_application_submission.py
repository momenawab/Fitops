"""Tests for the Application submission serializer contract and validation rules (Story 7.2).

Validates:
- Full valid payload validation with all eleven submission fields (Point 1)
- Persistence and round-tripping of all fields, including Decimal precision (Point 2)
- Wire name contract: 'package_id' is accepted and resolves to Package (Point 3)
- Required vs. optional field splits matching model contract (Point 4)
- Email address format validation (Point 5)
- Server-controlled state guard: status is not client-settable (Point 6)
- Multi-tenant security guard: workspace is injected via context (Point 7)
- Anonymous intake guard: user is not client-settable (Point 8)
- Workspace scoping: package must belong to context workspace (Point 9)
- Active package requirement: package must have is_active=True (Point 10)
- Anti-enumeration: foreign and non-existent packages yield identical error (Point 11)
- Tenant isolation: creates exactly one Application in context workspace (Point 12)
- Atomicity: invalid submission creates no Application records (Point 13)
- Story boundary guard: creates no User, Membership, ClientProfile, or Order (Point 14)
- Architecture guard: applications app exposes exactly {'Application'} (Point 15)
"""

import uuid
from decimal import Decimal

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from apps.applications.serializers import ApplicationSubmissionSerializer


class BaseApplicationSubmissionTestCase(TestCase):
    """Base test case providing model resolution, cache resets, and factory helpers."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.application_model = apps.get_model("applications", "Application")
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
            "height": Decimal("172.50"),
            "weight": Decimal("65.25"),
            "goal": "Build functional strength and athletic performance",
            "training_experience": "3 years intermediate training",
            "notes": "Prefers morning workout sessions and high protein guidance.",
        }
        payload.update(overrides)
        return payload


class ApplicationSubmissionValidationAndPersistenceTests(BaseApplicationSubmissionTestCase):
    """Verifies payload validation, persistence, decimal precision, and wire keys (Points 1-3)."""

    def test_full_valid_payload_validates_with_all_eleven_fields(self):
        """Asserts a full valid payload with all eleven documented fields validates (Point 1)."""
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)
        payload = self._build_valid_payload(package)

        serializer = ApplicationSubmissionSerializer(data=payload, context={"workspace": workspace})

        self.assertTrue(
            serializer.is_valid(),
            f"Full valid payload must validate successfully; got errors: {serializer.errors}",
        )

    def test_create_persists_application_with_matching_values_and_decimal_precision(self):
        """Asserts create() persists Application with exact values and Decimal types (Point 2)."""
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)
        payload = self._build_valid_payload(
            package,
            full_name="Alex Morgan",
            email="alex.morgan@example.com",
            phone="+1987654321",
            age=29,
            gender="non-binary",
            height=Decimal("180.50"),
            weight=Decimal("85.25"),
            goal="Hypertrophy and strength progression",
            training_experience="4 years consistent weightlifting",
            notes="Prefers 4-day upper/lower split routine.",
        )

        serializer = ApplicationSubmissionSerializer(data=payload, context={"workspace": workspace})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        application = serializer.save()

        refetched = self.application_model.objects.get(pk=application.pk)
        self.assertEqual(refetched.full_name, "Alex Morgan")
        self.assertEqual(refetched.email, "alex.morgan@example.com")
        self.assertEqual(refetched.phone, "+1987654321")
        self.assertEqual(refetched.age, 29)
        self.assertEqual(refetched.gender, "non-binary")
        self.assertEqual(refetched.goal, "Hypertrophy and strength progression")
        self.assertEqual(refetched.training_experience, "4 years consistent weightlifting")
        self.assertEqual(refetched.notes, "Prefers 4-day upper/lower split routine.")
        self.assertEqual(refetched.package, package)
        self.assertEqual(refetched.package_id, package.id)
        self.assertEqual(refetched.workspace, workspace)
        self.assertEqual(refetched.workspace_id, workspace.id)

        # Decimal precision check with no float drift
        self.assertEqual(
            refetched.height,
            Decimal("180.50"),
            "Application.height must equal Decimal('180.50') exactly with no float drift.",
        )
        self.assertEqual(
            refetched.weight,
            Decimal("85.25"),
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

    def test_package_id_is_accepted_wire_name_and_links_package_relation(self):
        """Asserts 'package_id' is the wire name and links the Package instance (Point 3)."""
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)
        payload = self._build_valid_payload(package, package_id=str(package.id))

        serializer = ApplicationSubmissionSerializer(data=payload, context={"workspace": workspace})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        application = serializer.save()

        refetched = self.application_model.objects.get(pk=application.pk)
        self.assertEqual(
            refetched.package,
            package,
            "Application.package must resolve to the Package matching submitted package_id.",
        )
        self.assertEqual(refetched.package_id, package.id)

    def test_submitting_package_instead_of_package_id_fails_validation(self):
        """Asserts submitting 'package' instead of wire name 'package_id' fails (Point 3)."""
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)
        payload = self._build_valid_payload(package)
        payload.pop("package_id")
        payload["package"] = str(package.id)

        serializer = ApplicationSubmissionSerializer(data=payload, context={"workspace": workspace})
        self.assertFalse(
            serializer.is_valid(),
            "Payload using 'package' instead of 'package_id' must fail validation.",
        )
        self.assertIn(
            "package_id",
            serializer.errors,
            "Missing 'package_id' wire field must produce an error on 'package_id'.",
        )


class ApplicationSubmissionRequiredAndOptionalFieldsTests(BaseApplicationSubmissionTestCase):
    """Verifies required vs optional field splits and email address validation (Points 4, 5)."""

    def test_omitting_package_id_fails_validation(self):
        """Asserts omitting required 'package_id' field fails validation (Point 4)."""
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)
        payload = self._build_valid_payload(package)
        payload.pop("package_id")

        serializer = ApplicationSubmissionSerializer(data=payload, context={"workspace": workspace})
        self.assertFalse(serializer.is_valid())
        self.assertIn("package_id", serializer.errors)

    def test_omitting_full_name_fails_validation(self):
        """Asserts omitting required 'full_name' field fails validation (Point 4)."""
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)
        payload = self._build_valid_payload(package)
        payload.pop("full_name")

        serializer = ApplicationSubmissionSerializer(data=payload, context={"workspace": workspace})
        self.assertFalse(serializer.is_valid())
        self.assertIn("full_name", serializer.errors)

    def test_omitting_email_fails_validation(self):
        """Asserts omitting required 'email' field fails validation (Point 4)."""
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)
        payload = self._build_valid_payload(package)
        payload.pop("email")

        serializer = ApplicationSubmissionSerializer(data=payload, context={"workspace": workspace})
        self.assertFalse(serializer.is_valid())
        self.assertIn("email", serializer.errors)

    def test_minimal_payload_with_only_required_fields_validates_and_saves(self):
        """Asserts minimal payload with only package_id, full_name, email saves (Point 4)."""
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)
        minimal_payload = {
            "package_id": str(package.id),
            "full_name": "Minimal Applicant",
            "email": "minimal.applicant@example.com",
        }

        serializer = ApplicationSubmissionSerializer(
            data=minimal_payload, context={"workspace": workspace}
        )
        self.assertTrue(
            serializer.is_valid(),
            f"Minimal payload must validate; got errors: {serializer.errors}",
        )
        application = serializer.save()

        refetched = self.application_model.objects.get(pk=application.pk)
        self.assertEqual(refetched.full_name, "Minimal Applicant")
        self.assertEqual(refetched.email, "minimal.applicant@example.com")
        self.assertEqual(refetched.package, package)
        self.assertEqual(refetched.workspace, workspace)

        # Optional text fields must default to empty strings
        self.assertEqual(refetched.phone, "")
        self.assertEqual(refetched.gender, "")
        self.assertEqual(refetched.goal, "")
        self.assertEqual(refetched.training_experience, "")
        self.assertEqual(refetched.notes, "")

        # Optional numeric and FK fields must default to None
        self.assertIsNone(refetched.age)
        self.assertIsNone(refetched.height)
        self.assertIsNone(refetched.weight)
        self.assertIsNone(refetched.user)
        self.assertIsNone(refetched.user_id)

    def test_email_field_validates_email_address_format(self):
        """Asserts invalid email address format is rejected with error on 'email' (Point 5)."""
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)

        invalid_emails = [
            "not-an-email",
            "missingatsign.com",
            "@missinguser.com",
            "user@domain..com",
        ]
        for invalid_email in invalid_emails:
            with self.subTest(email=invalid_email):
                payload = self._build_valid_payload(package, email=invalid_email)
                serializer = ApplicationSubmissionSerializer(
                    data=payload, context={"workspace": workspace}
                )
                self.assertFalse(
                    serializer.is_valid(),
                    f"Email '{invalid_email}' must be rejected by EmailField validation.",
                )
                self.assertIn(
                    "email",
                    serializer.errors,
                    f"Validation error for '{invalid_email}' must appear under 'email' key.",
                )


class ApplicationSubmissionServerControlledStateGuardsTests(BaseApplicationSubmissionTestCase):
    """Verifies non-client-settable guards for status, workspace, and user (Points 6, 7, 8)."""

    def test_status_is_not_client_settable_and_defaults_to_submitted(self):
        """Guards server-controlled lifecycle state: status must always be SUBMITTED (Point 6).

        A submitter must never be permitted to set or advance the application lifecycle status
        directly (e.g. attempting to submit as 'APPROVED' or 'REVIEWING'). Even if a client
        crafts a payload with status='APPROVED', the saved database record must strictly possess
        status='SUBMITTED'.
        """
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)

        for attempted_status in ("APPROVED", "REVIEWING", "REJECTED"):
            with self.subTest(status=attempted_status):
                payload = self._build_valid_payload(package, status=attempted_status)
                serializer = ApplicationSubmissionSerializer(
                    data=payload, context={"workspace": workspace}
                )
                if serializer.is_valid():
                    application = serializer.save()
                    refetched = self.application_model.objects.get(pk=application.pk)
                    self.assertEqual(
                        refetched.status,
                        "SUBMITTED",
                        f"Application status must be 'SUBMITTED' even when client supplied "
                        f"status='{attempted_status}'.",
                    )
                    self.assertNotEqual(
                        refetched.status,
                        attempted_status,
                        f"Application status must not be client-writable to '{attempted_status}'.",
                    )
                else:
                    self.assertFalse(
                        self.application_model.objects.filter(
                            workspace=workspace, full_name=payload["full_name"]
                        ).exists(),
                        "Invalid submission with status must not persist any record.",
                    )

    def test_workspace_is_not_client_settable_and_always_uses_context_workspace(self):
        """Guards multi-tenant security (API §25): workspace is bound from context (Point 7).

        Clients must never be able to redirect or assign an application to an arbitrary workspace
        by injecting 'workspace' or 'workspace_id' into the submission payload. The persisted
        Application must strictly belong to the Workspace supplied in the serializer context.
        """
        workspace_a = self._create_workspace(slug="context-workspace-a")
        workspace_b = self._create_workspace(slug="attacker-workspace-b")
        package_a = self._create_package(workspace=workspace_a)

        for field_name in ("workspace", "workspace_id"):
            with self.subTest(field_name=field_name):
                payload = self._build_valid_payload(
                    package_a,
                    **{field_name: str(workspace_b.id)},
                )
                serializer = ApplicationSubmissionSerializer(
                    data=payload, context={"workspace": workspace_a}
                )
                if serializer.is_valid():
                    application = serializer.save()
                    refetched = self.application_model.objects.get(pk=application.pk)
                    self.assertEqual(
                        refetched.workspace_id,
                        workspace_a.id,
                        f"Saved Application.workspace_id must match context Workspace A when "
                        f"'{field_name}' is in payload.",
                    )
                    self.assertNotEqual(
                        refetched.workspace_id,
                        workspace_b.id,
                        f"Saved Application must not receive client-supplied Workspace B id "
                        f"from '{field_name}'.",
                    )

    def test_user_is_not_client_settable_and_persists_as_none(self):
        """Guards anonymous intake boundary: user is not client-settable (Point 8).

        Public submissions originate from anonymous prospects and must not allow client-supplied
        user association. The user field must remain None upon initial submission; association
        is deferred to the Story 7.3 onboarding workflow.
        """
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)
        user = self._create_user()

        for field_name in ("user", "user_id"):
            with self.subTest(field_name=field_name):
                payload = self._build_valid_payload(
                    package,
                    **{field_name: str(user.id)},
                )
                serializer = ApplicationSubmissionSerializer(
                    data=payload, context={"workspace": workspace}
                )
                if serializer.is_valid():
                    application = serializer.save()
                    refetched = self.application_model.objects.get(pk=application.pk)
                    self.assertIsNone(
                        refetched.user,
                        f"Application.user must be None even when '{field_name}' is in payload.",
                    )
                    self.assertIsNone(
                        refetched.user_id,
                        f"Application.user_id must be None when '{field_name}' is in payload.",
                    )


class ApplicationSubmissionPackageScopingAndAntiEnumerationTests(BaseApplicationSubmissionTestCase):
    """Verifies workspace package scoping, active checks, and anti-enumeration (Points 9-11)."""

    def test_package_from_different_workspace_fails_validation(self):
        """Asserts submitting a package_id from a foreign workspace is invalid (Point 9)."""
        workspace_a = self._create_workspace(slug="ws-target")
        workspace_b = self._create_workspace(slug="ws-foreign")
        foreign_package = self._create_package(workspace=workspace_b, is_active=True)

        payload = self._build_valid_payload(foreign_package)
        serializer = ApplicationSubmissionSerializer(
            data=payload, context={"workspace": workspace_a}
        )

        self.assertFalse(
            serializer.is_valid(),
            "Serializer must be invalid when package_id belongs to a different workspace.",
        )
        self.assertIn(
            "package_id",
            serializer.errors,
            "Validation error must be attached to the 'package_id' field.",
        )

    def test_inactive_package_in_same_workspace_fails_validation(self):
        """Asserts submitting an inactive package in same workspace is invalid (Point 10)."""
        workspace = self._create_workspace()
        inactive_package = self._create_package(workspace=workspace, is_active=False)

        payload = self._build_valid_payload(inactive_package)
        serializer = ApplicationSubmissionSerializer(data=payload, context={"workspace": workspace})

        self.assertFalse(
            serializer.is_valid(),
            "Serializer must be invalid when package_id belongs to an inactive package.",
        )
        self.assertIn(
            "package_id",
            serializer.errors,
            "Validation error must be attached to the 'package_id' field.",
        )

    def test_foreign_and_nonexistent_packages_produce_identical_errors(self):
        """Guards anti-enumeration invariant (DB §26, API §25): errors match strictly (Point 11).

        A submitter must never be able to discover or enumerate package UUIDs in other workspaces
        by observing differential error messages. The validation error returned for a foreign
        package ID must be byte-for-byte / value-for-value identical to a non-existent UUID.
        """
        workspace_a = self._create_workspace(slug="tenant-a")
        workspace_b = self._create_workspace(slug="tenant-b")
        foreign_package = self._create_package(workspace=workspace_b, is_active=True)
        nonexistent_uuid = uuid.uuid4()

        foreign_payload = self._build_valid_payload(foreign_package)
        nonexistent_payload = self._build_valid_payload(
            foreign_package, package_id=str(nonexistent_uuid)
        )

        foreign_serializer = ApplicationSubmissionSerializer(
            data=foreign_payload, context={"workspace": workspace_a}
        )
        nonexistent_serializer = ApplicationSubmissionSerializer(
            data=nonexistent_payload, context={"workspace": workspace_a}
        )

        self.assertFalse(foreign_serializer.is_valid())
        self.assertFalse(nonexistent_serializer.is_valid())

        self.assertIn("package_id", foreign_serializer.errors)
        self.assertIn("package_id", nonexistent_serializer.errors)

        # Each error echoes back the UUID the caller itself submitted, so the two strings
        # necessarily differ in that one substring. Comparing them raw would fail for a reason
        # that carries no information — the submitter already knows the id they sent. The
        # invariant that actually matters is that the error CODE and the message TEMPLATE are
        # identical, so nothing distinguishes "exists in another workspace" from "does not
        # exist anywhere". Normalising the echoed id is what makes this test test that.
        foreign_error = foreign_serializer.errors["package_id"][0]
        nonexistent_error = nonexistent_serializer.errors["package_id"][0]

        self.assertEqual(
            foreign_error.code,
            nonexistent_error.code,
            "package_id error CODE for a foreign-workspace package must equal the code for a "
            "non-existent package UUID (anti-enumeration invariant).",
        )

        foreign_template = str(foreign_error).replace(str(foreign_package.id), "<pk>")
        nonexistent_template = str(nonexistent_error).replace(str(nonexistent_uuid), "<pk>")

        self.assertEqual(
            foreign_template,
            nonexistent_template,
            "package_id error MESSAGE for a foreign-workspace package must be identical to the "
            "message for a non-existent package UUID once the echoed id is normalised.",
        )

        self.assertNotIn(
            str(workspace_b.id),
            str(foreign_error),
            "The error must never reveal the workspace that owns the package.",
        )


class ApplicationSubmissionCountAndAtomicityTests(BaseApplicationSubmissionTestCase):
    """Verifies tenant isolation counts and atomicity on invalid submissions (Points 12, 13)."""

    def test_valid_submission_creates_exactly_one_application_in_context_workspace(self):
        """Asserts valid submission creates exactly 1 row in context workspace (Point 12)."""
        workspace_a = self._create_workspace(slug="ws-submit-a")
        workspace_b = self._create_workspace(slug="ws-submit-b")
        package_a = self._create_package(workspace=workspace_a)
        self._create_package(workspace=workspace_b)

        self.assertEqual(self.application_model.objects.for_workspace(workspace_a).count(), 0)
        self.assertEqual(self.application_model.objects.for_workspace(workspace_b).count(), 0)

        payload = self._build_valid_payload(package_a)
        serializer = ApplicationSubmissionSerializer(
            data=payload, context={"workspace": workspace_a}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()

        self.assertEqual(
            self.application_model.objects.for_workspace(workspace_a).count(),
            1,
            "Context workspace Application count must increment from 0 to 1.",
        )
        self.assertEqual(
            self.application_model.objects.for_workspace(workspace_b).count(),
            0,
            "Other workspace Application count must remain 0.",
        )
        self.assertEqual(
            self.application_model.objects.filter(workspace=workspace_a).count(),
            1,
        )
        self.assertEqual(
            self.application_model.objects.filter(workspace=workspace_b).count(),
            0,
        )

    def test_invalid_submission_creates_no_application_records(self):
        """Asserts invalid submission persists zero rows across all workspaces (Point 13)."""
        workspace_a = self._create_workspace(slug="ws-invalid-a")
        workspace_b = self._create_workspace(slug="ws-invalid-b")
        package_a = self._create_package(workspace=workspace_a)

        self.assertEqual(self.application_model.objects.count(), 0)

        payload = self._build_valid_payload(package_a)
        payload.pop("email")

        serializer = ApplicationSubmissionSerializer(
            data=payload, context={"workspace": workspace_a}
        )
        self.assertFalse(serializer.is_valid())

        self.assertEqual(
            self.application_model.objects.for_workspace(workspace_a).count(),
            0,
            "No Application must be created in context workspace after failed validation.",
        )
        self.assertEqual(
            self.application_model.objects.for_workspace(workspace_b).count(),
            0,
            "No Application must be created in other workspace after failed validation.",
        )
        self.assertEqual(
            self.application_model.objects.count(),
            0,
            "Total Application count across database must remain 0.",
        )


class ApplicationSubmissionArchitectureAndBoundaryGuardTests(BaseApplicationSubmissionTestCase):
    """Verifies boundaries preventing Story 7.3/Epic 08 work leakage (Points 14, 15)."""

    def test_successful_submission_creates_no_user_membership_client_profile_or_order(self):
        """Guards Story boundary: intake only; creates no User, Membership, or Order (Point 14).

        Story 7.2 captures prospective client leads without converting them into authenticated
        users or creating billing records. User creation, ClientProfile linkage, and Membership
        assignment belong strictly to the Story 7.3 onboarding transaction. Order models belong
        to Epic 08. Submitting an application must not create any User, Membership, or
        ClientProfile, and the commerce app must continue to expose zero models.
        """
        workspace = self._create_workspace()
        package = self._create_package(workspace=workspace)

        initial_user_count = self.user_model.objects.count()
        initial_membership_count = self.membership_model.objects.count()
        initial_client_profile_count = self.client_profile_model.objects.count()

        payload = self._build_valid_payload(package)
        serializer = ApplicationSubmissionSerializer(data=payload, context={"workspace": workspace})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()

        self.assertEqual(
            self.user_model.objects.count(),
            initial_user_count,
            "Application submission must not create any User instance.",
        )
        self.assertEqual(
            self.membership_model.objects.count(),
            initial_membership_count,
            "Application submission must not create any Membership instance.",
        )
        self.assertEqual(
            self.client_profile_model.objects.count(),
            initial_client_profile_count,
            "Application submission must not create any ClientProfile instance.",
        )

        # This originally asserted the commerce app defined NO models, which held only while
        # Epic 08 had not started. Story 8.1 has since landed the Order model legitimately, so
        # the check was replaced with the stronger, permanently-true invariant: submitting an
        # application must create no Order ROWS. That is the property Story 7.2 actually owns —
        # the initial Order is created by the Story 7.3 transaction, never by intake alone —
        # and unlike the old assertion it keeps working as Epic 08 grows.
        order_model = apps.get_model("commerce", "Order")
        self.assertEqual(
            order_model.objects.count(),
            0,
            "Application submission must not create any Order; that is the Story 7.3 flow.",
        )

    def test_applications_app_exposes_exactly_application_model(self):
        """Guards architectural boundary: applications app exposes only Application (Point 15)."""
        applications_app = apps.get_app_config("applications")
        concrete_model_names = {model._meta.object_name for model in applications_app.get_models()}
        self.assertSetEqual(
            concrete_model_names,
            {"Application"},
            "applications app must define exactly {'Application'}; no extra models allowed.",
        )
