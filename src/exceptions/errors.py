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


class QuotaExceeded(ViewTripException):
    """Raised when an action would push a user past their plan's limits.

    Carries the numbers so the API handler can turn it into a 402 the client can
    render ("2 of 1 trips used") without a second round trip.
    """

    def __init__(self, message: str, *, plan: str, limit: int | None,
                 used: int, resource: str):
        super().__init__(message)
        self.plan = plan
        self.limit = limit
        self.used = used
        self.resource = resource  # "projects" | "storage"


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
