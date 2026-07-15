"""Issue #86: an encounter's Polarsteps track showed an incomplete track.

`format_trip` already falls back to the `all_steps` key when `steps` is
absent/empty — some trip detail responses use the older key. `get_trip_steps`
only read `steps`, so any such trip silently returned a truncated (or empty)
step list instead of the full track.
"""
from __future__ import annotations

from src.api.polarsteps_client import PolarstepsClient


def _client_returning(payload: dict) -> PolarstepsClient:
    c = PolarstepsClient("123|abc")
    c._get = lambda path, **params: payload  # type: ignore[method-assign]
    return c


class TestAllStepsFallback:
    def test_falls_back_to_all_steps_when_steps_missing(self):
        payload = {
            "all_steps": [
                {"id": 1, "type": 1, "start_time": "2026-06-01T08:00:00"},
                {"id": 2, "type": 1, "start_time": "2026-06-02T08:00:00"},
            ]
        }
        ids = [s["id"] for s in _client_returning(payload).get_trip_steps(9)]
        assert ids == [1, 2]

    def test_falls_back_to_all_steps_when_steps_empty(self):
        payload = {
            "steps": [],
            "all_steps": [{"id": 3, "type": 1, "start_time": "2026-06-01T08:00:00"}],
        }
        ids = [s["id"] for s in _client_returning(payload).get_trip_steps(9)]
        assert ids == [3]

    def test_prefers_steps_when_present(self):
        payload = {
            "steps": [{"id": 1, "type": 1, "start_time": "2026-06-01T08:00:00"}],
            "all_steps": [
                {"id": 1, "type": 1, "start_time": "2026-06-01T08:00:00"},
                {"id": 2, "type": 1, "start_time": "2026-06-02T08:00:00"},
            ],
        }
        ids = [s["id"] for s in _client_returning(payload).get_trip_steps(9)]
        assert ids == [1]

    def test_no_key_present_returns_empty(self):
        assert _client_returning({}).get_trip_steps(9) == []
