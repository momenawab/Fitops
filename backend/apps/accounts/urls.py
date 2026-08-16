"""URL routes for account API endpoints."""

from django.urls import path

from .views import CoachRegistrationView

urlpatterns = [
    path("auth/register", CoachRegistrationView.as_view(), name="coach-register"),
]
