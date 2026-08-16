"""Standard API error envelope exception handler for FitOps.

Conforms to FitOps API Specification §2 (Standard Error Format):
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Please correct the highlighted fields.",
    "fields": {
      "email": [
        "Enter a valid email address."
      ]
    }
  }
}
"""

from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import exceptions
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.views import exception_handler as drf_exception_handler

# Closed list of error codes specified in API Specification §2.
# No codes outside this set may be emitted.
VALID_ERROR_CODES: frozenset[str] = frozenset(
    {
        "AUTHENTICATION_REQUIRED",
        "INVALID_CREDENTIALS",
        "INVALID_OTP",
        "OTP_EXPIRED",
        "OTP_RATE_LIMITED",
        "EMAIL_NOT_VERIFIED",
        "TWO_FACTOR_REQUIRED",
        "INVALID_TWO_FACTOR_CODE",
        "PERMISSION_DENIED",
        "NOT_FOUND",
        "VALIDATION_ERROR",
        "CONFLICT",
        "RATE_LIMITED",
        "FILE_TOO_LARGE",
        "UNSUPPORTED_FILE_TYPE",
        "INTERNAL_ERROR",
    }
)

DEFAULT_ERROR_MESSAGES: dict[str, str] = {
    "AUTHENTICATION_REQUIRED": "Authentication credentials were not provided.",
    "INVALID_CREDENTIALS": "Invalid credentials.",
    "INVALID_OTP": "Invalid verification code.",
    "OTP_EXPIRED": "Verification code has expired.",
    "OTP_RATE_LIMITED": "Too many OTP requests. Please try again later.",
    "EMAIL_NOT_VERIFIED": "Email address has not been verified.",
    "TWO_FACTOR_REQUIRED": "Two-factor authentication is required.",
    "INVALID_TWO_FACTOR_CODE": "Invalid two-factor authentication code.",
    "PERMISSION_DENIED": "You do not have permission to perform this action.",
    "NOT_FOUND": "The requested resource was not found.",
    "VALIDATION_ERROR": "Please correct the highlighted fields.",
    "CONFLICT": "A conflict occurred with the current state of the resource.",
    "RATE_LIMITED": "Request was throttled. Please try again later.",
    "FILE_TOO_LARGE": "The uploaded file exceeds the size limit.",
    "UNSUPPORTED_FILE_TYPE": "The file type is not supported.",
    "INTERNAL_ERROR": "An internal server error occurred.",
}

EXCEPTION_TYPE_MAP: tuple[tuple[type[Exception] | tuple[type[Exception], ...], str], ...] = (
    (exceptions.ValidationError, "VALIDATION_ERROR"),
    (exceptions.ParseError, "VALIDATION_ERROR"),
    (exceptions.AuthenticationFailed, "INVALID_CREDENTIALS"),
    (exceptions.NotAuthenticated, "AUTHENTICATION_REQUIRED"),
    ((exceptions.PermissionDenied, DjangoPermissionDenied), "PERMISSION_DENIED"),
    ((exceptions.NotFound, Http404), "NOT_FOUND"),
    (exceptions.UnsupportedMediaType, "UNSUPPORTED_FILE_TYPE"),
    (exceptions.Throttled, "RATE_LIMITED"),
)

STATUS_CODE_MAP: dict[int, str] = {
    400: "VALIDATION_ERROR",
    401: "AUTHENTICATION_REQUIRED",
    403: "PERMISSION_DENIED",
    404: "NOT_FOUND",
    409: "CONFLICT",
    413: "FILE_TOO_LARGE",
    415: "UNSUPPORTED_FILE_TYPE",
    429: "RATE_LIMITED",
}


def _get_error_code(exc: Exception, response: Response) -> str:
    """Determine the standard error code for an exception.

    Resolution order:
    1. Direct 'code' attribute on the exception if it matches the closed set.
    2. Direct 'default_code' attribute on the exception if it matches the closed set.
    3. Exception class hierarchy matching.
    4. HTTP status code fallback.
    5. Fallback to INTERNAL_ERROR.
    """
    exc_code = getattr(exc, "code", None)
    if isinstance(exc_code, str) and exc_code in VALID_ERROR_CODES:
        return exc_code

    default_code = getattr(exc, "default_code", None)
    if isinstance(default_code, str) and default_code in VALID_ERROR_CODES:
        return default_code

    for exc_types, code in EXCEPTION_TYPE_MAP:
        if isinstance(exc, exc_types):
            return code

    status_code = getattr(response, "status_code", None)
    if isinstance(status_code, int) and status_code in STATUS_CODE_MAP:
        return STATUS_CODE_MAP[status_code]

    return "INTERNAL_ERROR"


def _flatten_error_messages(item: Any) -> list[str]:
    """Recursively extract string error messages from a nested error structure."""
    if isinstance(item, (list, tuple)):
        messages: list[str] = []
        for element in item:
            messages.extend(_flatten_error_messages(element))
        return messages
    if isinstance(item, dict):
        messages = []
        for key, value in item.items():
            sub_messages = _flatten_error_messages(value)
            for msg in sub_messages:
                messages.append(f"{key}: {msg}")
        return messages
    if item is not None:
        return [str(item)]
    return []


def _extract_message_and_fields(
    data: Any,
    code: str,
    exc: Exception,
) -> tuple[str, dict[str, list[str]] | None]:
    """Extract a human-readable message string and optional fields error dictionary.

    - For field-level validation errors (VALIDATION_ERROR), fields is populated
      as {field: [messages]}.
    - For non-validation errors or validation errors with no field-specific details,
      fields is omitted (None).
    - DRF's non_field_errors are surfaced in the top-level 'message'.
    """
    non_field_keys: set[str] = {"non_field_errors", "__all__"}
    try:
        drf_non_field_key = api_settings.NON_FIELD_ERRORS_KEY
        if drf_non_field_key:
            non_field_keys.add(drf_non_field_key)
    except Exception:
        pass

    if isinstance(data, dict):
        # DRF wraps single detail messages in {'detail': ...} for standard exceptions.
        if len(data) == 1 and "detail" in data and not isinstance(exc, exceptions.ValidationError):
            detail_val = data["detail"]
            if isinstance(detail_val, (str, exceptions.ErrorDetail)):
                return str(detail_val), None
            if isinstance(detail_val, (list, tuple)):
                messages = _flatten_error_messages(detail_val)
                msg_str = (
                    " ".join(messages)
                    if messages
                    else DEFAULT_ERROR_MESSAGES.get(code, "An error occurred.")
                )
                return msg_str, None
            if isinstance(detail_val, dict):
                return _extract_message_and_fields(detail_val, code, exc)

        non_field_messages: list[str] = []
        fields_dict: dict[str, list[str]] = {}

        for key, value in data.items():
            key_str = str(key)
            if key_str in non_field_keys:
                non_field_messages.extend(_flatten_error_messages(value))
            else:
                msgs = _flatten_error_messages(value)
                if msgs:
                    fields_dict[key_str] = msgs

        if non_field_messages:
            message = " ".join(non_field_messages)
        elif fields_dict and code == "VALIDATION_ERROR":
            message = "Please correct the highlighted fields."
        elif fields_dict:
            message = DEFAULT_ERROR_MESSAGES.get(code, "Validation failed.")
        else:
            message = DEFAULT_ERROR_MESSAGES.get(code, "An error occurred.")

        fields = fields_dict if (code == "VALIDATION_ERROR" and fields_dict) else None
        return message, fields

    if isinstance(data, (list, tuple)):
        messages = _flatten_error_messages(data)
        message = (
            " ".join(messages)
            if messages
            else DEFAULT_ERROR_MESSAGES.get(code, "An error occurred.")
        )
        return message, None

    if isinstance(data, (str, exceptions.ErrorDetail)):
        return str(data), None

    return DEFAULT_ERROR_MESSAGES.get(code, "An error occurred."), None


def fitops_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """Transform DRF and Django exceptions into the standard FitOps error envelope.

    Conforms to FitOps API Specification §2:
        {
            "error": {
                "code": "<CODE>",
                "message": "<Human-readable message>",
                "fields": { ... }  # optional, only present on VALIDATION_ERROR with field errors
            }
        }

    Args:
        exc: The unhandled exception to process.
        context: Context dictionary passed by DRF (e.g. view, args, kwargs, request).

    Returns:
        A Response object containing the reshaped error envelope, or None if the
        exception is not handled by DRF (delegating to Django's standard 500 handler).
    """
    response = drf_exception_handler(exc, context)

    if response is None:
        return None

    code = _get_error_code(exc, response)
    if code not in VALID_ERROR_CODES:
        code = "INTERNAL_ERROR"

    message, fields = _extract_message_and_fields(response.data, code, exc)

    error_data: dict[str, Any] = {
        "code": code,
        "message": message,
    }

    if fields is not None:
        error_data["fields"] = fields

    response.data = {"error": error_data}
    return response


# Alias for standard DRF naming compatibility
exception_handler = fitops_exception_handler

__all__ = [
    "DEFAULT_ERROR_MESSAGES",
    "VALID_ERROR_CODES",
    "exception_handler",
    "fitops_exception_handler",
]
