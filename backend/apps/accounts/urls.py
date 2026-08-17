"""URL routes for account API endpoints."""

from django.urls import path

from .views import (
    AuthMeView,
    CoachLoginView,
    CoachRegistrationView,
    EmailVerificationResendView,
    EmailVerificationView,
    LogoutView,
    TwoFactorConfirmView,
    TwoFactorDisableView,
    TwoFactorSetupView,
    TwoFactorVerifyView,
)

urlpatterns = [
    path("auth/me", AuthMeView.as_view(), name="auth-me"),
    path("auth/logout", LogoutView.as_view(), name="logout"),
    path("auth/login", CoachLoginView.as_view(), name="coach-login"),
    path("auth/register", CoachRegistrationView.as_view(), name="coach-register"),
    path("auth/email/verify", EmailVerificationView.as_view(), name="email-verify"),
    path("auth/email/resend", EmailVerificationResendView.as_view(), name="email-resend"),
    path("auth/2fa/setup", TwoFactorSetupView.as_view(), name="two-factor-setup"),
    path("auth/2fa/confirm", TwoFactorConfirmView.as_view(), name="two-factor-confirm"),
    path("auth/2fa/verify", TwoFactorVerifyView.as_view(), name="two-factor-verify"),
    path("auth/2fa/disable", TwoFactorDisableView.as_view(), name="two-factor-disable"),
]
