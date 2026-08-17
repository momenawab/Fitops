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
