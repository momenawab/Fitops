"""Serializers for workspace API endpoints."""

from rest_framework import serializers

from common.storage import process_uploaded_image, save_thumbnail_beside

from .models import PaymentMethod, Workspace


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


class WorkspaceSettingsSerializer(serializers.ModelSerializer):
    """Validate the mutable settings accepted by the workspace endpoint."""

    class Meta:
        model = Workspace
        fields = (
            "name",
            "description",
            "brand_color",
            "currency",
            "whatsapp_number",
            "timezone",
        )


class WorkspaceBrandingSerializer(serializers.Serializer):
    """Serialize the branding response without changing the workspace contract."""

    logo = serializers.SerializerMethodField()
    profile_image = serializers.SerializerMethodField()
    brand_color = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)

    @staticmethod
    def _file_url(workspace, field_name):
        field = getattr(workspace, field_name)
        return field.url if field else None

    def get_logo(self, workspace):
        return self._file_url(workspace, "logo")

    def get_profile_image(self, workspace):
        return self._file_url(workspace, "profile_image")


class _ThumbnailPersistingMixin:
    """Persist the WebP thumbnail that ``process_uploaded_image`` produces.

    The pipeline generates a thumbnail per API §21, but a serializer that only stores the
    processed original silently discards it. Each validated image field records its thumbnail
    here, and ``update`` writes them once the originals have their final storage names.
    """

    thumbnail_fields: tuple[str, ...] = ()

    def _process(self, field_name, value):
        processed = process_uploaded_image(value)
        if not hasattr(self, "_pending_thumbnails"):
            self._pending_thumbnails = {}
        self._pending_thumbnails[field_name] = processed.thumbnail
        return processed.image

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)
        for field_name, thumbnail in getattr(self, "_pending_thumbnails", {}).items():
            field_file = getattr(instance, field_name, None)
            if field_file:
                save_thumbnail_beside(field_file, thumbnail)
        return instance

    def create(self, validated_data):
        instance = super().create(validated_data)
        for field_name, thumbnail in getattr(self, "_pending_thumbnails", {}).items():
            field_file = getattr(instance, field_name, None)
            if field_file:
                save_thumbnail_beside(field_file, thumbnail)
        return instance


class WorkspaceBrandingUpdateSerializer(_ThumbnailPersistingMixin, serializers.ModelSerializer):
    """Validate and process optional branding fields from a multipart update."""

    logo = serializers.FileField(required=False, write_only=True)
    profile_image = serializers.FileField(required=False, write_only=True)

    class Meta:
        model = Workspace
        fields = ("logo", "profile_image", "brand_color", "description")

    def validate_logo(self, value):
        return self._process("logo", value)

    def validate_profile_image(self, value):
        return self._process("profile_image", value)


class WorkspaceLogoUploadSerializer(_ThumbnailPersistingMixin, serializers.ModelSerializer):
    """Validate and process the required logo upload."""

    logo = serializers.FileField(write_only=True)

    class Meta:
        model = Workspace
        fields = ("logo",)

    def validate_logo(self, value):
        return self._process("logo", value)


class PaymentMethodSerializer(_ThumbnailPersistingMixin, serializers.ModelSerializer):
    """Validate and serialize payment methods without exposing their workspace id."""

    image = serializers.FileField(required=False)

    class Meta:
        model = PaymentMethod
        fields = (
            "id",
            "type",
            "name",
            "instructions",
            "account_details",
            "image",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def validate_image(self, value):
        return self._process("image", value)
