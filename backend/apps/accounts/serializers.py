"""Serializers for account API endpoints."""

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers


class CoachRegistrationSerializer(serializers.Serializer):
    """Validate the fields required to register a coach account."""

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    first_name = serializers.CharField()
    last_name = serializers.CharField()

    def validate(self, attrs):
        user = get_user_model()(
            email=attrs["email"],
            first_name=attrs["first_name"],
            last_name=attrs["last_name"],
        )
        try:
            validate_password(attrs["password"], user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)}) from exc
        return attrs


class EmailVerificationSerializer(serializers.Serializer):
    """Validate an email-verification token submission."""

    token = serializers.CharField()


class EmailVerificationResendSerializer(serializers.Serializer):
    """Validate an email address for verification-email resend requests."""

    email = serializers.EmailField()


class CoachLoginSerializer(serializers.Serializer):
    """Validate coach login credentials."""

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class TwoFactorCodeSerializer(serializers.Serializer):
    """Validate a time-based one-time password submission."""

    code = serializers.CharField(min_length=6, max_length=6)
