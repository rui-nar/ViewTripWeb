"""Issue #23: Polarsteps import must surface published steps, not drafts.

A step's `type` field marks publication state — `1` = published, `0` = draft
(an unpublished/offline step still being written). `get_trip_steps` drops
`type == 0` by default; `include_drafts=True` keeps them for diagnostics.
"""
from __future__ import annotations

from src.api.polarsteps_client import PolarstepsClient


def _client_returning(steps: list[dict]) -> PolarstepsClient:
    c = PolarstepsClient("123|abc")
    c._get = lambda path, **params: {"steps": list(steps)}  # type: ignore[method-assign]
    return c


class TestDraftFiltering:
    def _steps(self) -> list[dict]:
        return [
            {"id": 1, "name": "Published A", "type": 1, "start_time": "2026-06-01T08:00:00"},
            {"id": 2, "name": "Draft",       "type": 0, "start_time": "2026-06-02T08:00:00"},
            {"id": 3, "name": "Published B", "type": 1, "start_time": "2026-06-03T08:00:00"},
        ]

    def test_drafts_excluded_by_default(self):
        ids = [s["id"] for s in _client_returning(self._steps()).get_trip_steps(9)]
        assert ids == [1, 3]

    def test_include_drafts_keeps_them(self):
        ids = [s["id"] for s in _client_returning(self._steps()).get_trip_steps(9, include_drafts=True)]
        assert ids == [1, 2, 3]

    def test_missing_type_is_treated_as_published(self):
        # Defensive: only an explicit type==0 is a draft. An unknown/absent type
        # must never be silently hidden.
        steps = [{"id": 5, "name": "No type", "start_time": "2026-06-01T08:00:00"}]
        ids = [s["id"] for s in _client_returning(steps).get_trip_steps(9)]
        assert ids == [5]

    def test_filtering_preserves_chronological_sort(self):
        steps = [
            {"id": 3, "type": 1, "start_time": "2026-06-03T08:00:00"},
            {"id": 1, "type": 1, "start_time": "2026-06-01T08:00:00"},
            {"id": 2, "type": 0, "start_time": "2026-06-02T08:00:00"},  # draft, dropped
        ]
        ids = [s["id"] for s in _client_returning(steps).get_trip_steps(9)]
        assert ids == [1, 3]
