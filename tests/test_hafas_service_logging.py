"""Logging tests for src/services/hafas_service.py (issue #205, Unit C).

Before this, hafas_service.py had no logger at all — every HAFAS/train-routing
failure was a complete blackout. These tests confirm the module now logs a
WARNING for expected upstream flakiness (no stops nearby, train not found) and
an ERROR (via ``.exception()``) for anything unexpected (a raw network
failure), while still raising ``HafasError`` unchanged so callers' fallback
behaviour is untouched.
"""
import logging
from unittest.mock import patch

import pytest

from src.services.hafas_service import HafasError, get_stop_sequence


# Arbitrary coordinates — content doesn't matter, only that the lookup fails.
_LAT1, _LON1 = 52.5200, 13.4050  # Berlin
_LAT2, _LON2 = 48.8566, 2.3522   # Paris


class TestUnsupportedProvider:
    def test_logs_warning_and_raises(self, caplog):
        with caplog.at_level(logging.WARNING, logger="src.services.hafas_service"):
            with pytest.raises(HafasError, match="Unsupported HAFAS provider"):
                get_stop_sequence(
                    provider="not-a-real-provider",
                    train_number="ICE 123",
                    date="2026-06-01",
                    start_lat=_LAT1, start_lon=_LON1,
                    end_lat=_LAT2, end_lon=_LON2,
                )
        assert any(r.levelno == logging.WARNING for r in caplog.records)
        assert "not-a-real-provider" in caplog.text


class TestNoNearbyStops:
    def test_logs_warning_and_raises(self, caplog):
        """_nearest_stop returning nothing (transport.rest 'db' path) is
        expected upstream flakiness — WARNING, not an exception traceback."""
        with patch("src.services.hafas_service._nearest_stop", return_value=None):
            with caplog.at_level(logging.WARNING, logger="src.services.hafas_service"):
                with pytest.raises(HafasError, match="Could not locate nearby stops"):
                    get_stop_sequence(
                        provider="db",
                        train_number="ICE 123",
                        date="2026-06-01",
                        start_lat=_LAT1, start_lon=_LON1,
                        end_lat=_LAT2, end_lon=_LON2,
                    )
        assert any(r.levelno == logging.WARNING for r in caplog.records)


class TestUnexpectedNetworkFailure:
    def test_logs_exception_and_raises(self, caplog):
        """A raw network error (mocked transport) is unexpected — must use
        .exception() (ERROR level + traceback), not a plain WARNING."""
        with patch("src.services.hafas_service.requests.get",
                   side_effect=ConnectionError("boom")):
            with caplog.at_level(logging.WARNING, logger="src.services.hafas_service"):
                with pytest.raises(HafasError, match="HAFAS request failed"):
                    get_stop_sequence(
                        provider="db",
                        train_number="ICE 123",
                        date="2026-06-01",
                        start_lat=_LAT1, start_lon=_LON1,
                        end_lat=_LAT2, end_lon=_LON2,
                    )
        error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert error_records, "expected an ERROR-level .exception() log"
        assert error_records[0].exc_info is not None

    def test_wraps_outbound_call_in_track_external(self, metric):
        """The failing call is still counted via track_external("hafas", ...)."""
        before = metric("viewtrip_external_requests_total",
                        service="hafas", endpoint="stops/nearby", outcome="exception")
        with patch("src.services.hafas_service.requests.get",
                   side_effect=ConnectionError("boom")):
            with pytest.raises(HafasError):
                get_stop_sequence(
                    provider="db",
                    train_number="ICE 123",
                    date="2026-06-01",
                    start_lat=_LAT1, start_lon=_LON1,
                    end_lat=_LAT2, end_lon=_LON2,
                )
        after = metric("viewtrip_external_requests_total",
                       service="hafas", endpoint="stops/nearby", outcome="exception")
        assert after - before == 1


class TestVrTrainNotFound:
    def test_logs_warning_and_raises(self, caplog):
        import src.services.hafas_service as svc
        svc._vr_stations_cache = [{
            "stationShortCode": "HKI", "stationName": "Helsinki asema",
            "latitude": _LAT1, "longitude": _LON1,
        }]
        try:
            with patch("src.services.hafas_service.requests.get") as mock_get:
                mock_get.return_value.json.return_value = []
                mock_get.return_value.raise_for_status = lambda: None

                with caplog.at_level(logging.WARNING, logger="src.services.hafas_service"):
                    with pytest.raises(HafasError, match="not found"):
                        get_stop_sequence(
                            provider="vr",
                            train_number="999",
                            date="2026-06-01",
                            start_lat=_LAT1, start_lon=_LON1,
                            end_lat=_LAT2, end_lon=_LON2,
                        )
            assert any(r.levelno == logging.WARNING for r in caplog.records)
        finally:
            svc._vr_stations_cache = None


class TestRejseplanenNoNearbyStops:
    def test_logs_warning_and_raises(self, caplog):
        with patch("src.services.hafas_service._rp_nearest_stop", return_value=None):
            with caplog.at_level(logging.WARNING, logger="src.services.hafas_service"):
                with pytest.raises(HafasError, match="Rejseplanen"):
                    get_stop_sequence(
                        provider="dsb",
                        train_number="IC 123",
                        date="2026-06-01",
                        start_lat=_LAT1, start_lon=_LON1,
                        end_lat=_LAT2, end_lon=_LON2,
                    )
        assert any(r.levelno == logging.WARNING for r in caplog.records)
