"""Serializers for coaching package API endpoints."""

from rest_framework import serializers

from .models import Package


class PackageSerializer(serializers.ModelSerializer):
    """Validate and serialize packages without exposing their workspace id."""

    # required=False mirrors the model's ``default=list``; an explicit ListField override
    # otherwise drops the default ModelSerializer would have inferred and makes it mandatory.
    features = serializers.ListField(child=serializers.CharField(), required=False)

    class Meta:
        model = Package
        fields = (
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
        )
        read_only_fields = ("id", "created_at", "updated_at")
