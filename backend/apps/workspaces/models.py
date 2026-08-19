"""Workspace models."""

import uuid

from django.db import models


class Workspace(models.Model):
    """A branded workspace for a fitness business."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    logo = models.FileField(upload_to="workspace_logos/", blank=True)
    profile_image = models.FileField(upload_to="workspace_profile_images/", blank=True)
    description = models.TextField(blank=True)
    brand_color = models.CharField(max_length=7, blank=True)
    currency = models.CharField(max_length=3)
    timezone = models.CharField(max_length=64)
    whatsapp_number = models.CharField(max_length=32, blank=True)
    status = models.CharField(
        max_length=9,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


from common.models.tenant import WorkspaceScopedModel  # noqa: E402


class PaymentMethod(WorkspaceScopedModel):
    """A workspace-owned method through which clients can pay."""

    class Type(models.TextChoices):
        INSTAPAY = "INSTAPAY", "InstaPay"
        VODAFONE_CASH = "VODAFONE_CASH", "Vodafone Cash"
        BANK_TRANSFER = "BANK_TRANSFER", "Bank Transfer"
        CUSTOM = "CUSTOM", "Custom"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    type = models.CharField(max_length=13, choices=Type.choices)
    name = models.CharField(max_length=255)
    instructions = models.TextField()
    account_details = models.TextField()
    image = models.FileField(upload_to="payment_method_images/", blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
