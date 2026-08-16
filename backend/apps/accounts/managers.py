"""Managers for the accounts app."""

from django.contrib.auth.base_user import BaseUserManager


class UserManager(BaseUserManager):
    """Manager for the email-based User model."""

    def create_user(self, email, password=None, **extra_fields):
        """Create and save a user with an email address and password."""
        if not email:
            raise ValueError("The email address must be set")

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
