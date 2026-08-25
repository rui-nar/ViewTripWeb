"""Unit tests for GPX import (parse_gpx_bytes, validate_for_import, gpx_track_to_points)."""

import gpxpy
import gpxpy.gpx
import pytest

from src.models.track_edit import TrackPoint
from src.gpx.importer import (
    GPXImportError,
    parse_gpx_bytes,
    validate_for_import,
    gpx_track_to_points,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gpx_xml(tracks):
    """Build a GPX 1.1 XML string. `tracks` is a list of segments-lists,
    where each segment is a list of (lat, lon, ele) tuples."""
    parts = ['<?xml version="1.0"?>',
             '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">']
    for segments in tracks:
        parts.append("<trk>")
        for segment in segments:
            parts.append("<trkseg>")
            for lat, lon, ele in segment:
                if ele is None:
                    parts.append(f'<trkpt lat="{lat}" lon="{lon}"/>')
                else:
                    parts.append(f'<trkpt lat="{lat}" lon="{lon}"><ele>{ele}</ele></trkpt>')
            parts.append("</trkseg>")
        parts.append("</trk>")
    parts.append("</gpx>")
    return "\n".join(parts)


def _make_gpx(n_tracks=1, n_segments=1, n_points=3):
    segment = [(48.0 + i * 0.001, 2.0 + i * 0.001, 100.0 + i) for i in range(n_points)]
    track = [segment for _ in range(n_segments)]
    xml = _gpx_xml([track for _ in range(n_tracks)])
    return gpxpy.parse(xml)


# ---------------------------------------------------------------------------
# parse_gpx_bytes
# ---------------------------------------------------------------------------

class TestParseGpxBytes:

    def test_valid_gpx_bytes_parses(self):
        xml = _gpx_xml([[[(48.0, 2.0, 10.0), (48.001, 2.001, 11.0)]]])
        gpx = parse_gpx_bytes(xml.encode("utf-8"))
        assert isinstance(gpx, gpxpy.gpx.GPX)
        assert len(gpx.tracks) == 1

    def test_garbage_bytes_raises_import_error(self):
        with pytest.raises(GPXImportError):
            parse_gpx_bytes(b"not xml at all")

    def test_garbage_bytes_error_has_reasons(self):
        try:
            parse_gpx_bytes(b"not xml at all")
            assert False, "expected GPXImportError"
        except GPXImportError as e:
            assert len(e.errors) >= 1
            assert isinstance(e.errors[0], str)


# ---------------------------------------------------------------------------
# validate_for_import
# ---------------------------------------------------------------------------

class TestValidateForImport:

    def test_valid_single_track_single_segment_returns_no_errors(self):
        gpx = _make_gpx(n_tracks=1, n_segments=1, n_points=3)
        assert validate_for_import(gpx) == []

    def test_zero_tracks_rejected(self):
        gpx = gpxpy.gpx.GPX()
        errors = validate_for_import(gpx)
        assert errors != []
        assert any("no tracks" in e.lower() for e in errors)

    def test_two_tracks_rejected(self):
        gpx = _make_gpx(n_tracks=2, n_segments=1, n_points=3)
        errors = validate_for_import(gpx)
        assert errors != []
        assert any("only a single track" in e.lower() for e in errors)

    def test_two_tracks_message_mentions_count(self):
        gpx = _make_gpx(n_tracks=2, n_segments=1, n_points=3)
        errors = validate_for_import(gpx)
        assert any("2" in e for e in errors)

    def test_single_track_multiple_segments_accepted(self):
        gpx = _make_gpx(n_tracks=1, n_segments=2, n_points=3)
        assert validate_for_import(gpx) == []

    def test_single_point_track_rejected(self):
        gpx = _make_gpx(n_tracks=1, n_segments=1, n_points=1)
        errors = validate_for_import(gpx)
        assert errors != []
        assert any("fewer than 2" in e.lower() for e in errors)

    def test_two_points_accepted(self):
        gpx = _make_gpx(n_tracks=1, n_segments=1, n_points=2)
        assert validate_for_import(gpx) == []

    def test_out_of_range_latitude_rejected(self):
        # gpxpy does not validate lat/lon range at parse or construction time
        # (verified: GPXTrackPoint(latitude=200, ...) constructs without error,
        # and gpxpy.parse() happily accepts lat="200" in the XML), so this is
        # exactly the case validate_for_import must catch itself.
        xml = _gpx_xml([[[(200.0, 2.0, 10.0), (48.001, 2.001, 11.0)]]])
        gpx = gpxpy.parse(xml)
        errors = validate_for_import(gpx)
        assert errors != []
        assert any("latitude" in e.lower() for e in errors)

    def test_out_of_range_longitude_rejected(self):
        xml = _gpx_xml([[[(48.0, 200.0, 10.0), (48.001, 2.001, 11.0)]]])
        gpx = gpxpy.parse(xml)
        errors = validate_for_import(gpx)
        assert errors != []
        assert any("longitude" in e.lower() for e in errors)

    def test_too_many_points_rejected(self):
        segment = [(48.0 + i * 0.0001, 2.0, None) for i in range(50001)]
        gpx = gpxpy.gpx.GPX()
        gpx_track = gpxpy.gpx.GPXTrack()
        gpx_segment = gpxpy.gpx.GPXTrackSegment()
        for lat, lon, ele in segment:
            gpx_segment.points.append(gpxpy.gpx.GPXTrackPoint(latitude=lat, longitude=lon))
        gpx_track.segments.append(gpx_segment)
        gpx.tracks.append(gpx_track)
        errors = validate_for_import(gpx)
        assert errors != []
        assert any("too many" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# gpx_track_to_points
# ---------------------------------------------------------------------------

class TestGpxTrackToPoints:

    def test_point_count_and_values(self):
        gpx = _make_gpx(n_tracks=1, n_segments=1, n_points=3)
        points = gpx_track_to_points(gpx)
        assert len(points) == 3
        assert all(isinstance(p, TrackPoint) for p in points)
        assert points[0].lat == pytest.approx(48.0)
        assert points[0].lng == pytest.approx(2.0)
        assert points[0].elev == pytest.approx(100.0)

    def test_missing_elevation_is_none(self):
        xml = _gpx_xml([[[(48.0, 2.0, None), (48.001, 2.001, None)]]])
        gpx = gpxpy.parse(xml)
        points = gpx_track_to_points(gpx)
        assert points[0].elev is None

    def test_multiple_segments_concatenated_in_order(self):
        gpx = _make_gpx(n_tracks=1, n_segments=2, n_points=3)
        points = gpx_track_to_points(gpx)
        assert len(points) == 6
        seg1 = gpx.tracks[0].segments[0].points
        seg2 = gpx.tracks[0].segments[1].points
        assert points[0].lat == pytest.approx(seg1[0].latitude)
        assert points[2].lat == pytest.approx(seg1[2].latitude)
        assert points[3].lat == pytest.approx(seg2[0].latitude)
        assert points[5].lat == pytest.approx(seg2[2].latitude)
