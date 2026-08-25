"""Views for account API endpoints."""

import binascii
from functools import partial

import pyotp
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import exceptions, serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.workspaces.public_views import resolve_public_workspace

from .models import CoachSecurity, LoginOTP, Membership
from .otp import (
    OTP_MAX_ATTEMPTS,
    ClientOTPEmailRateThrottle,
    is_valid_login_code,
    issue_login_otp,
    send_login_code_email,
)
from .serializers import (
    AuthMeSerializer,
    ClientOTPRequestSerializer,
    ClientOTPVerifySerializer,
    CoachLoginSerializer,
    CoachRegistrationSerializer,
    EmailVerificationResendSerializer,
    EmailVerificationSerializer,
    PasswordForgotSerializer,
    PasswordResetSerializer,
    TwoFactorCodeSerializer,
)
from .tokens import email_verification_token_generator, password_reset_token_generator

REGISTRATION_RESPONSE = {
    "message": "Account created. Please verify your email.",
    "requires_email_verification": True,
}
EMAIL_RESEND_RESPONSE = {
    "message": "If an unverified account exists for this email, a verification email has been sent."
}
PASSWORD_FORGOT_RESPONSE = {
    "message": "If an account exists for this email, a password reset email has been sent."
}
INVALID_VERIFICATION_TOKEN_MESSAGE = "Invalid or expired verification token."
INVALID_PASSWORD_RESET_TOKEN_MESSAGE = "Invalid or expired password reset token."
INVALID_TWO_FACTOR_CODE_MESSAGE = "Invalid two-factor authentication code."
PENDING_TWO_FACTOR_USER_ID_SESSION_KEY = "pending_2fa_user_id"
CLIENT_OTP_REQUEST_RESPONSE = {
    "message": "If an eligible client account exists, a login code has been sent."
}


class InvalidOTP(exceptions.APIException):
    """Return the documented error code for an unusable OTP."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "INVALID_OTP"
    default_detail = "Invalid verification code."


class ExpiredOTP(exceptions.APIException):
    """Return the documented error code for an expired OTP."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "OTP_EXPIRED"
    default_detail = "Verification code has expired."


class OTPRateLimited(exceptions.APIException):
    """Return the documented error code for exhausted OTP attempts."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_code = "OTP_RATE_LIMITED"
    default_detail = "Too many OTP requests. Please try again later."


def _send_verification_email(user):
    """Send a stateless email-verification token to a newly registered user."""
    token = email_verification_token_generator.make_token(user)
    send_mail(
        subject="Verify your FitOps email",
        message=f"Use this token to verify your email: {token}",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
    )


def _send_password_reset_email(user):
    """Send a stateless password-reset token to a coach."""
    token = password_reset_token_generator.make_token(user)
    send_mail(
        subject="Reset your FitOps password",
        message=f"Use this token to reset your password: {token}",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
    )


def _normalize_email(email):
    """Normalize email consistently for client OTP lookups."""
    return get_user_model().objects.normalize_email(email).casefold()


def _resolve_client_workspace(slug):
    """Resolve an active public workspace without exposing a lookup failure."""
    try:
        return resolve_public_workspace(slug)
    except exceptions.NotFound:
        return None


def _has_active_client_membership(user, workspace):
    """Return whether a user is an active client in the resolved workspace."""
    return Membership.objects.filter(
        user=user,
        workspace=workspace,
        role=Membership.Role.CLIENT,
        status=Membership.Status.ACTIVE,
    ).exists()


class ClientOTPRequestView(APIView):
    """Issue a client login OTP without exposing account or workspace state."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ClientOTPEmailRateThrottle, ScopedRateThrottle]
    throttle_scope = "client_otp_request_ip"

    def post(self, request):
        """Send a code only for an eligible client and always return one response."""
        serializer = ClientOTPRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = _normalize_email(serializer.validated_data["email"])
        workspace = _resolve_client_workspace(serializer.validated_data["workspace_slug"])
        user = get_user_model().objects.filter(email__iexact=email).first()

        eligible_client = (
            workspace is not None
            and user is not None
            and _has_active_client_membership(user, workspace)
        )
        if eligible_client:
            code = issue_login_otp(user)
            transaction.on_commit(partial(send_login_code_email, user, code))

        # All account and workspace states intentionally receive this identical response.
        return Response(CLIENT_OTP_REQUEST_RESPONSE)


class ClientOTPVerifyView(APIView):
    """Verify a client login OTP and start the standard Django session."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "client_otp_verify"

    def post(self, request):
        """Consume a valid OTP after confirming its client workspace authorization."""
        serializer = ClientOTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = _normalize_email(serializer.validated_data["email"])
        workspace = _resolve_client_workspace(serializer.validated_data["workspace_slug"])
        user = get_user_model().objects.filter(email__iexact=email).first()

        if workspace is None or user is None or not _has_active_client_membership(user, workspace):
            raise InvalidOTP()

        invalid_code = False
        exhausted = False
        with transaction.atomic():
            otp = (
                LoginOTP.objects.select_for_update()
                .filter(user=user)
                .order_by("-created_at")
                .first()
            )
            if otp is None or otp.used_at is not None:
                raise InvalidOTP()
            if otp.expires_at <= timezone.now():
                raise ExpiredOTP()
            if otp.attempts >= OTP_MAX_ATTEMPTS:
                raise OTPRateLimited()
            # check_password performs the required constant-time hash comparison.
            if not is_valid_login_code(otp, serializer.validated_data["code"]):
                otp.attempts += 1
                otp.save(update_fields=["attempts"])
                # Raise after the transaction so the failed attempt is committed.
                invalid_code = True
                exhausted = otp.attempts >= OTP_MAX_ATTEMPTS
            else:
                otp.used_at = timezone.now()
                otp.save(update_fields=["used_at"])

        if invalid_code:
            if exhausted:
                raise OTPRateLimited()
            raise InvalidOTP()

        login(request, user)
        return Response({"authenticated": True})


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


class PasswordForgotView(APIView):
    """Queue a reset email without exposing account state."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_forgot"

    def post(self, request):
        serializer = PasswordForgotSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user_model = get_user_model()
        email = user_model.objects.normalize_email(serializer.validated_data["email"])

        with transaction.atomic():
            user = user_model.objects.filter(email=email).first()
            if user is not None:
                transaction.on_commit(partial(_send_password_reset_email, user))

        return Response(PASSWORD_FORGOT_RESPONSE)


class PasswordResetView(APIView):
    """Reset a coach password from a stateless password-reset token."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset"

    def post(self, request):
        serializer = PasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = serializer.validated_data["token"]
        user_id = password_reset_token_generator.get_user_id(token)
        if user_id is None:
            self._raise_invalid_token()

        with transaction.atomic():
            user = get_user_model().objects.filter(pk=user_id).select_for_update().first()
            if user is None or not password_reset_token_generator.check_token(user, token):
                self._raise_invalid_token()
            try:
                validate_password(serializer.validated_data["password"], user)
            except DjangoValidationError as exc:
                raise serializers.ValidationError({"password": list(exc.messages)}) from exc
            user.set_password(serializer.validated_data["password"])
            user.save()

        return Response()

    @staticmethod
    def _raise_invalid_token():
        """Raise the shared response for all unusable reset tokens."""
        raise serializers.ValidationError({"token": [INVALID_PASSWORD_RESET_TOKEN_MESSAGE]})


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
            request.session[PENDING_TWO_FACTOR_USER_ID_SESSION_KEY] = str(user.pk)
            return Response({"authenticated": False, "requires_2fa": True})

        login(request, user)
        return Response({"authenticated": True})


def _raise_invalid_two_factor_code():
    """Raise a field-level validation error without exposing TOTP state."""
    raise serializers.ValidationError({"code": [INVALID_TWO_FACTOR_CODE_MESSAGE]})


def _is_valid_two_factor_code(secret, code):
    """Verify a TOTP code, treating malformed stored secrets as invalid."""
    try:
        return pyotp.TOTP(secret).verify(code)
    except TypeError, ValueError, binascii.Error:
        return False


class TwoFactorSetupView(APIView):
    """Generate a new TOTP secret for the authenticated user."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        security, _ = CoachSecurity.objects.get_or_create(user=request.user)
        secret = pyotp.random_base32()
        security.two_factor_secret = secret
        security.two_factor_enabled = False
        security.save(update_fields=["two_factor_secret", "two_factor_enabled", "updated_at"])
        uri = pyotp.TOTP(secret).provisioning_uri(
            name=request.user.email,
            issuer_name="FitOps",
        )
        return Response({"secret": secret, "otpauth_uri": uri})


class TwoFactorConfirmView(APIView):
    """Enable TOTP after the authenticated user proves possession of its secret."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = TwoFactorCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        security = CoachSecurity.objects.filter(user=request.user).first()
        if security is None or not security.two_factor_secret:
            _raise_invalid_two_factor_code()
        if not _is_valid_two_factor_code(
            security.two_factor_secret, serializer.validated_data["code"]
        ):
            _raise_invalid_two_factor_code()

        security.two_factor_enabled = True
        security.save(update_fields=["two_factor_enabled", "updated_at"])
        return Response()


class TwoFactorVerifyView(APIView):
    """Complete a pending 2FA login after validating its TOTP code."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = TwoFactorCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pending_user_id = request.session.get(PENDING_TWO_FACTOR_USER_ID_SESSION_KEY)
        if pending_user_id is None:
            raise InvalidCredentials()

        user = get_user_model().objects.filter(pk=pending_user_id).first()
        security = (
            CoachSecurity.objects.filter(user=user, two_factor_enabled=True).first()
            if user is not None
            else None
        )
        if security is None or not security.two_factor_secret:
            raise InvalidCredentials()
        if not _is_valid_two_factor_code(
            security.two_factor_secret, serializer.validated_data["code"]
        ):
            _raise_invalid_two_factor_code()

        login(request, user)
        del request.session[PENDING_TWO_FACTOR_USER_ID_SESSION_KEY]
        return Response()


class TwoFactorDisableView(APIView):
    """Disable TOTP after proving possession of the current TOTP secret."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = TwoFactorCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        security = CoachSecurity.objects.filter(user=request.user).first()
        if security is None or not security.two_factor_secret:
            _raise_invalid_two_factor_code()
        if not _is_valid_two_factor_code(
            security.two_factor_secret, serializer.validated_data["code"]
        ):
            _raise_invalid_two_factor_code()

        security.two_factor_enabled = False
        security.two_factor_secret = ""
        security.save(update_fields=["two_factor_enabled", "two_factor_secret", "updated_at"])
        return Response()


class AuthMeView(APIView):
    """Return the authenticated user's global account state."""

    def get(self, request):
        user = get_user_model().objects.select_related("coach_security").get(pk=request.user.pk)
        return Response(AuthMeSerializer(user).data)


class LogoutView(APIView):
    """Revoke the authenticated user's current session."""

    def post(self, request):
        logout(request)
        return Response()
