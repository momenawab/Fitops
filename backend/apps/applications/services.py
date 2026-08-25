"""Transactional service for public application submissions (Story 7.3).

Implements API §7 step 3–7 ordering inside a single database transaction:
application → user/client profile → membership → user association → initial order.
A failure at any step rolls back every record created by this request, so an
Application is never observable without its Order (and vice versa).
"""

from django.db import IntegrityError, transaction

from apps.accounts.models import ClientProfile, Membership, User
from apps.commerce.models import Order

from .models import Application

# Bounded retries for the per-workspace order-number race (Blueprint §2D decision 52).
ORDER_NUMBER_MAX_ATTEMPTS = 5
ORDER_NUMBER_PADDING = 6


def submit_application(workspace, validated_data):
    """Persist an application and its initial order atomically.

    Args:
        workspace: the active Workspace resolved from the public URL slug.
        validated_data: serializer-validated fields, including the scoped ``package``.

    Returns:
        A tuple ``(application, order)`` of the created records.
    """
    with transaction.atomic():
        application = Application.objects.create(workspace=workspace, **validated_data)

        user = _resolve_client_user(validated_data["email"])
        membership = _resolve_client_membership(user, workspace)

        application.user = user
        application.save(update_fields=["user"])

        order = _create_initial_order(workspace, membership, application.package)

    return application, order


def _resolve_client_user(email):
    """Find or create the global User + ClientProfile for an applicant email.

    A global Client User may already exist because of another Workspace (ERD §6);
    in that case it is reused untouched. ClientProfile is global identity (DB §10)
    and is deliberately not scoped to any workspace.
    """
    normalized = User.objects.normalize_email(email)
    user = User.objects.filter(email__iexact=normalized).first()
    if user is None:
        try:
            # Savepoint: a rare concurrent signup of the same email raises
            # IntegrityError here, and without a savepoint that error would
            # poison the outer transaction (TransactionManagementError).
            with transaction.atomic():
                user = User.objects.create_user(email=normalized, password=None)
        except IntegrityError:
            user = User.objects.filter(email__iexact=normalized).first()
            if user is None:
                raise
    ClientProfile.objects.get_or_create(user=user)
    return user


def _resolve_client_membership(user, workspace):
    """Return this user's membership in the workspace, creating a CLIENT one if absent.

    An existing membership is reused WITHOUT changing its role or status — the
    applicant may already be a COACH or OWNER here, and get_or_create guarantees
    the role default is only applied on creation.
    """
    membership, _created = Membership.objects.get_or_create(
        user=user,
        workspace=workspace,
        defaults={"role": Membership.Role.CLIENT},
    )
    return membership


def _next_order_number(workspace):
    """Compute the next zero-padded sequential order number for one workspace.

    Scoped to the workspace only — never a platform-wide counter, which would
    leak cross-tenant order volume. Non-numeric historical values (if any) are
    skipped rather than crashing the allocation.
    """
    current_max = 0
    existing = Order.objects.for_workspace(workspace).values_list("order_number", flat=True)
    for value in existing:
        try:
            current_max = max(current_max, int(value))
        except TypeError, ValueError:
            continue
    return str(current_max + 1).zfill(ORDER_NUMBER_PADDING)


def _create_initial_order(workspace, membership, package):
    """Create the initial Order with a concurrency-safe per-workspace number.

    Amount and currency are taken from the Package — never from the request —
    because the frontend cannot choose the authoritative price (API §7 step 7).

    Two simultaneous submissions may compute the same number; the losing insert
    violates UNIQUE(workspace, order_number). Each attempt runs inside its own
    savepoint so the IntegrityError only rolls back that attempt — an unsavepointed
    failure inside the outer atomic block would mark the whole transaction broken
    and raise TransactionManagementError on any later statement.
    """
    order = None
    for _attempt in range(ORDER_NUMBER_MAX_ATTEMPTS):
        order_number = _next_order_number(workspace)
        try:
            with transaction.atomic():
                order = Order.objects.create(
                    workspace=workspace,
                    client=membership,
                    package=package,
                    order_number=order_number,
                    amount=package.price,
                    currency=package.currency,
                )
                break
        except IntegrityError:
            # Another concurrent submission committed this number first; the
            # savepoint above left the transaction usable, so recompute and retry.
            continue
    if order is None:
        raise IntegrityError(
            "Could not allocate a unique order number for workspace "
            f"{workspace.slug} after {ORDER_NUMBER_MAX_ATTEMPTS} attempts."
        )
    return order
