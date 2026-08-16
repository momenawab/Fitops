"""URL routes for account API endpoints."""

from django.urls import path

from .views import (
    CoachLoginView,
    CoachRegistrationView,
    EmailVerificationResendView,
    EmailVerificationView,
)

urlpatterns = [
    path("auth/login", CoachLoginView.as_view(), name="coach-login"),
    path("auth/register", CoachRegistrationView.as_view(), name="coach-register"),
    path("auth/email/verify", EmailVerificationView.as_view(), name="email-verify"),
    path("auth/email/resend", EmailVerificationResendView.as_view(), name="email-resend"),
]
