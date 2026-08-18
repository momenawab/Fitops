"""Serializers for workspace API endpoints."""

from rest_framework import serializers


class WorkspaceCreateSerializer(serializers.Serializer):
    """Validate the fields accepted by workspace onboarding."""

    name = serializers.CharField(max_length=255)
    slug = serializers.SlugField(max_length=50)
    currency = serializers.CharField(max_length=3)
    timezone = serializers.CharField(max_length=64)


class WorkspaceSerializer(serializers.Serializer):
    """Serialize the public workspace representation returned at creation."""

    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    slug = serializers.SlugField(read_only=True)
    description = serializers.CharField(read_only=True)
    brand_color = serializers.CharField(read_only=True)
    currency = serializers.CharField(read_only=True)
    timezone = serializers.CharField(read_only=True)
    whatsapp_number = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)
