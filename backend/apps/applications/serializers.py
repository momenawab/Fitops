"""Serializers for public onboarding application submissions."""

from rest_framework import serializers

from apps.coaching.models import Package

from .models import Application


class ApplicationSubmissionSerializer(serializers.ModelSerializer):
    """Validate a public application submission for a resolved workspace."""

    # ``package_id`` is the public wire name while the model relation is named ``package``.
    package_id = serializers.PrimaryKeyRelatedField(
        source="package",
        queryset=Package.objects.none(),
    )

    class Meta:
        model = Application
        fields = (
            "package_id",
            "full_name",
            "email",
            "phone",
            "age",
            "gender",
            "height",
            "weight",
            "goal",
            "training_experience",
            "notes",
        )

    def get_fields(self):
        """Limit selectable packages to active packages in the resolved workspace."""
        fields = super().get_fields()
        fields["package_id"].queryset = Package.objects.for_workspace(
            self.context["workspace"]
        ).filter(is_active=True)
        return fields

    def create(self, validated_data):
        """Create the application within the resolved workspace."""
        return Application.objects.create(
            workspace=self.context["workspace"],
            **validated_data,
        )
