"""Tests for project data models and ProjectIO round-trip — no Qt required."""

import os
import pytest

from src.models.project import (
    ConnectingSegment,
    Project,
    ProjectFilterState,
    ProjectItem,
    SegmentEndpoint,
)
from src.project.project_io import ProjectIO


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_activity_item(aid: int) -> ProjectItem:
    return ProjectItem(item_type="activity", activity_id=aid)


def _make_segment_item(label: str = "Paris → Lyon") -> ProjectItem:
    seg = ConnectingSegment(
        id="test-uuid-1234",
        segment_type="train",
        label=label,
        start=SegmentEndpoint(lat=48.85, lon=2.35, source="auto"),
        end=SegmentEndpoint(lat=45.74, lon=4.83, source="manual"),
    )
    return ProjectItem(item_type="segment", segment=seg)


@pytest.fixture
def simple_project():
    p = Project(name="Test Journey")
    p.items = [
        _make_activity_item(111),
        _make_segment_item(),
        _make_activity_item(222),
    ]
    p.filter_state = ProjectFilterState(
        start_date="2024-01-01",
        end_date="2024-12-31",
        activity_types=["Run", "Ride"],
    )
    return p


# ---------------------------------------------------------------------------
# ProjectItem / ConnectingSegment
# ---------------------------------------------------------------------------

class TestProjectItem:
    def test_activity_item(self):
        item = _make_activity_item(42)
        assert item.item_type == "activity"
        assert item.activity_id == 42
        assert item.segment is None

    def test_segment_item(self):
        item = _make_segment_item()
        assert item.item_type == "segment"
        assert item.segment is not None
        assert item.segment.segment_type == "train"
        assert item.segment.start.lat == pytest.approx(48.85)
        assert item.segment.end.source == "manual"

    def test_segment_default_id_is_uuid(self):
        seg = ConnectingSegment()
        assert len(seg.id) == 36    # UUID4 canonical form
        assert seg.id.count("-") == 4


# ---------------------------------------------------------------------------
# Project helpers
# ---------------------------------------------------------------------------

class TestProjectHelpers:
    def test_move_item_forward(self):
        p = Project(name="x")
        p.items = [_make_activity_item(i) for i in range(4)]
        p.move_item(0, 2)
        assert [i.activity_id for i in p.items] == [1, 2, 0, 3]

    def test_move_item_backward(self):
        p = Project(name="x")
        p.items = [_make_activity_item(i) for i in range(4)]
        p.move_item(3, 1)
        assert [i.activity_id for i in p.items] == [0, 3, 1, 2]

    def test_move_item_no_op(self):
        p = Project(name="x")
        p.items = [_make_activity_item(i) for i in range(3)]
        p.move_item(1, 1)
        assert [i.activity_id for i in p.items] == [0, 1, 2]

    def test_remove_item(self):
        p = Project(name="x")
        p.items = [_make_activity_item(i) for i in range(3)]
        p.remove_item(1)
        assert [i.activity_id for i in p.items] == [0, 2]

    def test_remove_out_of_range_noop(self):
        p = Project(name="x")
        p.items = [_make_activity_item(0)]
        p.remove_item(99)   # should not raise
        assert len(p.items) == 1


# ---------------------------------------------------------------------------
# ProjectIO serialisation helpers (unit-level, no disk)
# ---------------------------------------------------------------------------

class TestProjectIOHelpers:
    def test_serialise_activity_item(self):
        item = _make_activity_item(99)
        d = ProjectIO._serialise_item(item)
        assert d == {"item_type": "activity", "activity_id": 99}

    def test_serialise_segment_item(self):
        item = _make_segment_item("Test label")
        d = ProjectIO._serialise_item(item)
        assert d["item_type"] == "segment"
        seg_d = d["segment"]
        assert seg_d["segment_type"] == "train"
        assert seg_d["label"] == "Test label"
        assert seg_d["start"]["lat"] == pytest.approx(48.85)
        assert seg_d["end"]["source"] == "manual"

    def test_deserialise_activity_item(self):
        d = {"item_type": "activity", "activity_id": 77}
        item = ProjectIO._deserialise_item(d)
        assert item.item_type == "activity"
        assert item.activity_id == 77

    def test_deserialise_segment_item(self):
        d = {
            "item_type": "segment",
            "segment": {
                "id": "abc",
                "segment_type": "flight",
                "label": "NYC → LAX",
                "start": {"lat": 40.71, "lon": -74.01, "source": "auto"},
                "end":   {"lat": 34.05, "lon": -118.24, "source": "manual"},
            },
        }
        item = ProjectIO._deserialise_item(d)
        assert item.item_type == "segment"
        assert item.segment.segment_type == "flight"
        assert item.segment.label == "NYC → LAX"
        assert item.segment.start.lon == pytest.approx(-74.01)

    def test_round_trip_item_activity(self):
        orig = _make_activity_item(55)
        restored = ProjectIO._deserialise_item(ProjectIO._serialise_item(orig))
        assert restored.item_type == orig.item_type
        assert restored.activity_id == orig.activity_id

    def test_round_trip_item_segment(self):
        orig = _make_segment_item("round trip")
        restored = ProjectIO._deserialise_item(ProjectIO._serialise_item(orig))
        assert restored.segment.label == "round trip"
        assert restored.segment.segment_type == "train"
        assert restored.segment.start.lat == pytest.approx(48.85)


# ---------------------------------------------------------------------------
# Full file round-trip
# ---------------------------------------------------------------------------

class TestProjectIORoundTrip:
    def test_save_and_load(self, simple_project, tmp_path):
        path = str(tmp_path / "test.viewtrip")
        ProjectIO.save(simple_project, path)
        assert os.path.exists(path)

        loaded = ProjectIO.load(path)
        assert loaded.name == "Test Journey"
        assert loaded.version == 1
        assert len(loaded.items) == 3

    def test_items_preserved(self, simple_project, tmp_path):
        path = str(tmp_path / "test.viewtrip")
        ProjectIO.save(simple_project, path)
        loaded = ProjectIO.load(path)

        assert loaded.items[0].item_type == "activity"
        assert loaded.items[0].activity_id == 111
        assert loaded.items[1].item_type == "segment"
        assert loaded.items[1].segment.label == "Paris → Lyon"
        assert loaded.items[2].item_type == "activity"
        assert loaded.items[2].activity_id == 222

    def test_filter_state_preserved(self, simple_project, tmp_path):
        path = str(tmp_path / "test.viewtrip")
        ProjectIO.save(simple_project, path)
        loaded = ProjectIO.load(path)

        assert loaded.filter_state.start_date == "2024-01-01"
        assert loaded.filter_state.end_date == "2024-12-31"
        assert loaded.filter_state.activity_types == ["Run", "Ride"]

    def test_segment_coordinates_preserved(self, simple_project, tmp_path):
        path = str(tmp_path / "test.viewtrip")
        ProjectIO.save(simple_project, path)
        loaded = ProjectIO.load(path)

        seg = loaded.items[1].segment
        assert seg.start.lat == pytest.approx(48.85)
        assert seg.start.lon == pytest.approx(2.35)
        assert seg.end.lat == pytest.approx(45.74)
        assert seg.end.source == "manual"

    def test_empty_project_round_trip(self, tmp_path):
        p = Project(name="Empty")
        path = str(tmp_path / "empty.viewtrip")
        ProjectIO.save(p, path)
        loaded = ProjectIO.load(path)
        assert loaded.name == "Empty"
        assert loaded.items == []
        assert loaded.activities == []

    def test_file_is_valid_json(self, simple_project, tmp_path):
        import json
        path = str(tmp_path / "test.viewtrip")
        ProjectIO.save(simple_project, path)
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        assert "version" in data
        assert "name" in data
        assert "items" in data
        assert "activities" in data

    def test_unicode_in_label(self, tmp_path):
        p = Project(name="München → Paris 🚂")
        seg = ConnectingSegment(
            id="u1", segment_type="train", label="Basel → Zürich ✓",
            start=SegmentEndpoint(47.56, 7.59),
            end=SegmentEndpoint(47.38, 8.54),
        )
        p.items.append(ProjectItem(item_type="segment", segment=seg))
        path = str(tmp_path / "unicode.viewtrip")
        ProjectIO.save(p, path)
        loaded = ProjectIO.load(path)
        assert loaded.name == "München → Paris 🚂"
        assert loaded.items[0].segment.label == "Basel → Zürich ✓"
