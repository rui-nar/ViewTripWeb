"""Custom exceptions for ViewTrip application."""


class ViewTripException(Exception):
    """Base exception for ViewTrip."""

    pass


class ConfigurationError(ViewTripException):
    """Raised when configuration is invalid or missing."""

    pass


class AuthenticationError(ViewTripException):
    """Raised when authentication fails."""

    pass


class APIError(ViewTripException):
    """Raised when Strava API returns an error."""

    pass


class RateLimitError(APIError):
    """Raised when the app's own Strava quota window is full.

    A subclass of APIError so the existing app-level handler still maps it to a
    502 "integration temporarily unavailable" — the client-facing outcome is the
    same, but no request is sent to Strava at all.
    """

    pass


class TokenError(ViewTripException):
    """Raised when token management fails."""

    pass


class ValidationError(ViewTripException):
    """Raised when data validation fails."""

    pass


class ExportError(ViewTripException):
    """Raised when export operation fails."""

    pass


class GPXError(ViewTripException):
    """Raised when GPX processing fails."""

    pass
