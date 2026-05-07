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
