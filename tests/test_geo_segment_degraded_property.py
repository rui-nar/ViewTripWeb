"""The full-res geo builder must surface route_degraded on segment features
(issue #207) — the map needs it to render a degraded straight-chord resolve
differently from a real resolved route.
"""
from __future__ import annotations

import json

from api.geo import _build_full_geo_features
from src.models.project import ConnectingSegment, Project, ProjectItem, SegmentEndpoint


def _project_with_segment(seg: ConnectingSegment) -> Project:
    return Project(name="My Trip", items=[ProjectItem(item_type="segment", segment=seg)])


def test_degraded_segment_feature_flags_route_degraded():
    seg = ConnectingSegment(
        id="seg-1", segment_type="train",
        start=SegmentEndpoint(60.17, 24.94), end=SegmentEndpoint(66.50, 25.73),
        route_mode="rail",
        route_polyline=json.dumps([[24.94, 60.17], [25.73, 66.50]]),
        route_degraded=True,
    )
    features = _build_full_geo_features(_project_with_segment(seg))
    seg_feature = next(f for f in features if f["properties"]["type"] == "segment")
    assert seg_feature["properties"]["route_degraded"] is True


def test_real_resolve_feature_flags_route_degraded_false():
    seg = ConnectingSegment(
        id="seg-1", segment_type="train",
        start=SegmentEndpoint(60.17, 24.94), end=SegmentEndpoint(66.50, 25.73),
        route_mode="rail",
        route_polyline=json.dumps([[24.94, 60.17], [25.2, 61.0], [25.73, 66.50]]),
        route_degraded=False,
    )
    features = _build_full_geo_features(_project_with_segment(seg))
    seg_feature = next(f for f in features if f["properties"]["type"] == "segment")
    assert seg_feature["properties"]["route_degraded"] is False
