"""Services and throttles for client email one-time passwords."""

import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from rest_framework.throttling import SimpleRateThrottle

from .models import LoginOTP

OTP_EXPIRY_MINUTES = 10
OTP_MAX_ATTEMPTS = 5


class ClientOTPEmailRateThrottle(SimpleRateThrottle):
    """Limit client OTP requests by normalized submitted email address."""

    scope = "client_otp_request_email"

    def get_cache_key(self, request, view):
        """Build a rate-limit key from email without retaining raw OTP data."""
        email = request.data.get("email") if hasattr(request.data, "get") else None
        if not isinstance(email, str) or not email:
            return None
        normalized_email = get_user_model().objects.normalize_email(email.strip()).casefold()
        return self.cache_format % {"scope": self.scope, "ident": normalized_email}


def generate_login_code():
    """Generate a cryptographically secure six-digit numeric OTP."""
    return f"{secrets.randbelow(1_000_000):06d}"


def issue_login_otp(user):
    """Create a new OTP and invalidate earlier usable codes for the same user."""
    code = generate_login_code()
    now = timezone.now()
    with transaction.atomic():
        # Invalidate and create atomically so two usable codes never coexist.
        locked_user = get_user_model().objects.select_for_update().get(pk=user.pk)
        LoginOTP.objects.filter(
            user=locked_user,
            expires_at__gt=now,
            used_at__isnull=True,
        ).update(used_at=now)
        LoginOTP.objects.create(
            user=locked_user,
            email=locked_user.email,
            code_hash=make_password(code),
            expires_at=now + timedelta(minutes=OTP_EXPIRY_MINUTES),
        )
    return code


def send_login_code_email(user, code):
    """Deliver an OTP through Django's configured email backend."""
    send_mail(
        subject="Your FitOps login code",
        message=f"Your FitOps login code is: {code}",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
    )


def is_valid_login_code(otp, code):
    """Compare an OTP using Django's constant-time password hash verifier."""
    return check_password(code, otp.code_hash)
