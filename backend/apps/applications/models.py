"""Models for public onboarding applications."""

import uuid

from django.conf import settings
from django.db import models

from common.models.tenant import WorkspaceScopedModel


class Application(WorkspaceScopedModel):
    """A public onboarding application submitted from a coach's public portal."""

    class Status(models.TextChoices):
        SUBMITTED = "SUBMITTED", "Submitted"
        REVIEWING = "REVIEWING", "Reviewing"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    package = models.ForeignKey(
        "coaching.Package",
        on_delete=models.PROTECT,
        related_name="applications",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="applications",
    )
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.SUBMITTED)
    full_name = models.CharField(max_length=255)
    email = models.EmailField()
    phone = models.CharField(max_length=32, blank=True)
    age = models.PositiveIntegerField(null=True, blank=True)
    gender = models.CharField(max_length=32, blank=True)
    height = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    weight = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    goal = models.CharField(max_length=255, blank=True)
    training_experience = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.full_name
