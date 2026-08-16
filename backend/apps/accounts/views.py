"""Views for account API endpoints."""

from functools import partial

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import CoachRegistrationSerializer

REGISTRATION_RESPONSE = {
    "message": "Account created. Please verify your email.",
    "requires_email_verification": True,
}


def _send_verification_email(user):
    """Send a stateless email-verification token to a newly registered user."""
    token = default_token_generator.make_token(user)
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
