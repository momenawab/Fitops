"""Stateless token generation for account email verification."""

import binascii
from uuid import UUID

from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.crypto import constant_time_compare
from django.utils.encoding import force_bytes, force_str
from django.utils.http import base36_to_int, urlsafe_base64_decode, urlsafe_base64_encode


class UidPrefixedTokenGenerator(PasswordResetTokenGenerator):
    """Add an O(1) user-id lookup prefix to Django's signed tokens."""

    def make_token(self, user):
        """Return a uid-prefixed, signed token for a specific user."""
        uidb64 = urlsafe_base64_encode(force_bytes(str(user.pk)))
        return f"{uidb64}:{super().make_token(user)}"

    @staticmethod
    def get_user_id(token):
        """Extract the UUID encoded in a combined token."""
        try:
            uidb64, _ = token.split(":", maxsplit=1)
            return UUID(force_str(urlsafe_base64_decode(uidb64)))
        except AttributeError, TypeError, UnicodeDecodeError, ValueError, binascii.Error:
            return None

    def check_token(self, user, token):
        """Validate a token using this generator's scoped expiry window."""
        if not (user and token):
            return False

        try:
            user_id = self.get_user_id(token)
            _, token = token.split(":", maxsplit=1)
            ts_b36, _ = token.split("-")
            timestamp = base36_to_int(ts_b36)
        except ValueError:
            return False

        if user_id != user.pk:
            return False

        for secret in [self.secret, *self.secret_fallbacks]:
            if constant_time_compare(
                self._make_token_with_timestamp(user, timestamp, secret),
                token,
            ):
                break
        else:
            return False

        return (self._num_seconds(self._now()) - timestamp) <= self.timeout


class EmailVerificationTokenGenerator(UidPrefixedTokenGenerator):
    """Issue single-use email-verification tokens that expire after 10 minutes."""

    timeout = 600

    def _make_hash_value(self, user, timestamp):
        """Include verification state so a successful verification consumes the token."""
        verified_timestamp = (
            ""
            if user.email_verified_at is None
            else user.email_verified_at.replace(microsecond=0, tzinfo=None)
        )
        return f"{super()._make_hash_value(user, timestamp)}{verified_timestamp}"


class PasswordResetLinkTokenGenerator(UidPrefixedTokenGenerator):
    """Issue password-reset tokens that expire after 10 minutes."""

    timeout = 600


email_verification_token_generator = EmailVerificationTokenGenerator()
password_reset_token_generator = PasswordResetLinkTokenGenerator()
