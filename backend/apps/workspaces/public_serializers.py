"""Serializers for the public coach page endpoint."""

from rest_framework import serializers


class PublicWorkspaceSerializer(serializers.Serializer):
    """Serialize the public workspace representation."""

    name = serializers.CharField(read_only=True)
    slug = serializers.SlugField(read_only=True)
    description = serializers.CharField(read_only=True)
    brand_color = serializers.CharField(read_only=True)
    logo = serializers.SerializerMethodField()
    profile_image = serializers.SerializerMethodField()
    whatsapp_number = serializers.CharField(read_only=True)

    @staticmethod
    def _file_url(workspace, field_name):
        """Return a public file URL when the workspace field has a value."""
        field = getattr(workspace, field_name)
        return field.url if field else None

    def get_logo(self, workspace):
        """Return the public URL for the workspace logo."""
        return self._file_url(workspace, "logo")

    def get_profile_image(self, workspace):
        """Return the public URL for the workspace profile image."""
        return self._file_url(workspace, "profile_image")


class PublicCoachSerializer(serializers.Serializer):
    """Serialize the public owner coach profile representation."""

    bio = serializers.CharField(read_only=True)
    profile_image = serializers.SerializerMethodField()
    website_url = serializers.URLField(read_only=True)
    instagram_url = serializers.URLField(read_only=True)

    def get_profile_image(self, coach_profile):
        """Return the public URL for the coach profile image."""
        return coach_profile.profile_image.url if coach_profile.profile_image else None
