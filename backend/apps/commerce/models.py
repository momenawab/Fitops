"""Models for commercial orders."""

import uuid

from django.db import models

from common.models.tenant import WorkspaceScopedModel


class Order(WorkspaceScopedModel):
    """A client's commercial purchase of a package within one workspace."""

    class Status(models.TextChoices):
        PENDING_PAYMENT = "PENDING_PAYMENT", "Pending Payment"
        PAYMENT_SUBMITTED = "PAYMENT_SUBMITTED", "Payment Submitted"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        CANCELLED = "CANCELLED", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(
        "accounts.Membership",
        on_delete=models.PROTECT,
        related_name="orders",
    )
    package = models.ForeignKey(
        "coaching.Package",
        on_delete=models.PROTECT,
        related_name="orders",
    )
    order_number = models.CharField(max_length=20)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3)
    status = models.CharField(
        max_length=17,
        choices=Status.choices,
        default=Status.PENDING_PAYMENT,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "order_number"],
                name="unique_order_number_per_workspace",
            )
        ]
