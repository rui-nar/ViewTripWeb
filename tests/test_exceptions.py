"""Unit tests for custom exceptions."""

import pytest

from src.exceptions.errors import (
    APIError,
    AuthenticationError,
    ConfigurationError,
    ExportError,
    ViewTripException,
    GPXError,
    TokenError,
    ValidationError,
)


class TestExceptions:
    """Test custom exception classes."""

    def test_base_exception(self):
        """Test ViewTripException can be raised and caught."""
        with pytest.raises(ViewTripException):
            raise ViewTripException("Test error")

    def test_configuration_error(self):
        """Test ConfigurationError is a ViewTripException."""
        error = ConfigurationError("Config error")
        assert isinstance(error, ViewTripException)
        with pytest.raises(ConfigurationError):
            raise error

    def test_authentication_error(self):
        """Test AuthenticationError is a ViewTripException."""
        error = AuthenticationError("Auth failed")
        assert isinstance(error, ViewTripException)

    def test_api_error(self):
        """Test APIError is a ViewTripException."""
        error = APIError("API call failed")
        assert isinstance(error, ViewTripException)

    def test_token_error(self):
        """Test TokenError is a ViewTripException."""
        error = TokenError("Token expired")
        assert isinstance(error, ViewTripException)

    def test_validation_error(self):
        """Test ValidationError is a ViewTripException."""
        error = ValidationError("Invalid data")
        assert isinstance(error, ViewTripException)

    def test_export_error(self):
        """Test ExportError is a ViewTripException."""
        error = ExportError("Export failed")
        assert isinstance(error, ViewTripException)

    def test_gpx_error(self):
        """Test GPXError is a ViewTripException."""
        error = GPXError("GPX parse error")
        assert isinstance(error, ViewTripException)

    def test_exception_message(self):
        """Test exception message is preserved."""
        message = "Test error message"
        error = ViewTripException(message)
        assert str(error) == message
