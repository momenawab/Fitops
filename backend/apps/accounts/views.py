"""Views for account API endpoints."""

from functools import partial

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import exceptions, serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .models import CoachSecurity
from .serializers import (
    CoachLoginSerializer,
    CoachRegistrationSerializer,
    EmailVerificationResendSerializer,
    EmailVerificationSerializer,
)
from .tokens import email_verification_token_generator

REGISTRATION_RESPONSE = {
    "message": "Account created. Please verify your email.",
    "requires_email_verification": True,
}
EMAIL_RESEND_RESPONSE = {
    "message": "If an unverified account exists for this email, a verification email has been sent."
}
INVALID_VERIFICATION_TOKEN_MESSAGE = "Invalid or expired verification token."


def _send_verification_email(user):
    """Send a stateless email-verification token to a newly registered user."""
    token = email_verification_token_generator.make_token(user)
    send_mail(
        subject="Verify your FitOps email",
        message=f"Use this token to verify your email: {token}",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
    )


class CoachRegistrationView(APIView):
    """Create a coach account and queue its verification email after commit."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = CoachRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        user_model = get_user_model()
        email = user_model.objects.normalize_email(validated_data["email"])
        user_data = {**validated_data, "email": email}

        with transaction.atomic():
            user = user_model.objects.filter(email=email).first()
            if user is None:
                try:
                    with transaction.atomic():
                        user = user_model.objects.create_user(**user_data)
                except IntegrityError:
                    # A concurrent registration created the same account first.
                    user = None
                else:
                    transaction.on_commit(partial(_send_verification_email, user))

        return Response(REGISTRATION_RESPONSE, status=status.HTTP_201_CREATED)


class EmailVerificationView(APIView):
    """Verify a coach email address from a stateless verification token."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "email_verify"

    def post(self, request):
        serializer = EmailVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = serializer.validated_data["token"]
        user_model = get_user_model()

        user_id = email_verification_token_generator.get_user_id(token)
        if user_id is None:
            self._raise_invalid_token()

        with transaction.atomic():
            user = user_model.objects.filter(pk=user_id).select_for_update().first()
            if user is None or not email_verification_token_generator.check_token(user, token):
                self._raise_invalid_token()
            user.email_verified_at = timezone.now()
            user.save(update_fields=["email_verified_at"])

        return Response({"message": "Email verified successfully."})

    @staticmethod
    def _raise_invalid_token():
        """Raise the shared response for all unusable verification tokens."""
        raise serializers.ValidationError({"token": [INVALID_VERIFICATION_TOKEN_MESSAGE]})


class EmailVerificationResendView(APIView):
    """Queue a new verification email without exposing account state."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "email_resend"

    def post(self, request):
        serializer = EmailVerificationResendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user_model = get_user_model()
        email = user_model.objects.normalize_email(serializer.validated_data["email"])

        with transaction.atomic():
            user = user_model.objects.filter(
                email=email,
                email_verified_at__isnull=True,
            ).first()
            if user is not None:
                transaction.on_commit(partial(_send_verification_email, user))

        return Response(EMAIL_RESEND_RESPONSE)


class EmailNotVerified(exceptions.PermissionDenied):
    """Return the documented error code for an unverified email address."""

    default_code = "EMAIL_NOT_VERIFIED"
    default_detail = "Email address has not been verified."


class InvalidCredentials(exceptions.APIException):
    """Return a 401 response without DRF's authenticator-header downgrade."""

    status_code = status.HTTP_401_UNAUTHORIZED
    default_code = "INVALID_CREDENTIALS"
    default_detail = "Invalid credentials."


class CoachLoginView(APIView):
    """Authenticate a verified coach and start a Django session when 2FA is disabled."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        serializer = CoachLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(
            request,
            email=serializer.validated_data["email"],
            password=serializer.validated_data["password"],
        )
        if user is None:
            raise InvalidCredentials()

        if user.email_verified_at is None:
            raise EmailNotVerified()

        if CoachSecurity.objects.filter(user=user, two_factor_enabled=True).exists():
            return Response({"authenticated": False, "requires_2fa": True})

        login(request, user)
        return Response({"authenticated": True})
