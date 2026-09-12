"""What a GPX file already tells us, and what the first import ignored (#260).

Unit 3 of the import plan. Two things are under test: that a planned route is
importable at all — the case issue #260 was actually written for, and the one
the first version refused with "GPX contains no tracks" — and that the date,
time, name and activity type sitting in the file are read from it rather than
typed again by the user.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.gpx.importer import (
    GPXImportError,
    MAX_IMPORT_BYTES,
    candidates,
    guard_upload_size,
    gpx_track_to_points,
    map_activity_type,
    parse_gpx_bytes,
    suggested_name,
    validate_for_import,
)

_HEADER = ('<?xml version="1.0"?>'
           '<gpx version="1.1" creator="test" '
           'xmlns="http://www.topografix.com/GPX/1/1">')
_START = datetime(2024, 8, 12, 7, 33, 0, tzinfo=timezone.utc)


def _pt(tag, lat, lon, ele=None, when=None):
    inner = f'<ele>{ele}</ele>' if ele is not None else ""
    if when is not None:
        inner += f'<time>{when.strftime("%Y-%m-%dT%H:%M:%SZ")}</time>'
    return f'<{tag} lat="{lat}" lon="{lon}">{inner}</{tag}>'


def _track_gpx(points, name=None, activity_type=None, metadata_name=None):
    meta = f"<metadata><name>{metadata_name}</name></metadata>" if metadata_name else ""
    parts = [_HEADER, meta, "<trk>"]
    if name:
        parts.append(f"<name>{name}</name>")
    if activity_type:
        parts.append(f"<type>{activity_type}</type>")
    parts.append("<trkseg>")
    parts += [_pt("trkpt", *p) for p in points]
    parts += ["</trkseg>", "</trk>", "</gpx>"]
    return "".join(parts).encode("utf-8")


def _route_gpx(points, name=None):
    parts = [_HEADER, "<rte>"]
    if name:
        parts.append(f"<name>{name}</name>")
    parts += [_pt("rtept", *p) for p in points]
    parts += ["</rte>", "</gpx>"]
    return "".join(parts).encode("utf-8")


def _moving_track(*, stop_seconds=None):
    """A 10-point track walked at ~1.4 m/s — one sample per second, 1.4 m apart.

    ``stop_seconds`` stretches the single gap in the middle without moving:
    120 s is a rest at a junction, 7200 s is the device switched off over lunch.
    """
    points, when = [], _START
    for i in range(10):
        points.append((46.0 + i * 1.26e-5, 6.0, 500.0, when))
        pause = stop_seconds if (i == 4 and stop_seconds is not None) else 1
        when += timedelta(seconds=pause)
    return _track_gpx(points)


class TestPlannedRoutes:
    """The case #260 was written for. A planner exports <rte>, not <trk>."""

    def test_a_route_only_file_is_importable(self):
        gpx = parse_gpx_bytes(_route_gpx([(46.0, 6.0), (46.1, 6.1)]))
        assert validate_for_import(gpx) == []

    def test_a_route_yields_its_points(self):
        gpx = parse_gpx_bytes(_route_gpx([(46.0, 6.0), (46.1, 6.1), (46.2, 6.2)]))
        assert len(gpx_track_to_points(gpx)) == 3

    def test_a_route_is_marked_as_one(self):
        """The preview says "planned route" and leaves duration blank, because a
        route has no timing to show."""
        gpx = parse_gpx_bytes(_route_gpx([(46.0, 6.0), (46.1, 6.1)]))
        found = candidates(gpx)
        assert found[0].is_route is True
        assert found[0].elapsed_seconds is None

    def test_a_recorded_track_wins_over_a_route_in_the_same_file(self):
        """Garmin courses often carry both. Import what actually happened."""
        both = (_track_gpx([(46.0, 6.0), (46.1, 6.1)]).decode()
                .replace("</gpx>", "<rte><rtept lat='45' lon='5'/>"
                                   "<rtept lat='45.1' lon='5.1'/></rte></gpx>")
                .encode())
        found = candidates(parse_gpx_bytes(both))
        assert len(found) == 1
        assert found[0].is_route is False

    def test_waypoints_only_says_what_is_missing(self):
        gpx = parse_gpx_bytes(
            _HEADER.encode() + b'<wpt lat="46.0" lon="6.0"/></gpx>')
        errors = validate_for_import(gpx)
        assert any("only waypoints" in e.lower() for e in errors)


class TestTimesFromTheFile:
    def test_start_and_end_come_from_the_track(self):
        gpx = parse_gpx_bytes(_moving_track())
        found = candidates(gpx)[0]
        assert found.started_at == _START
        assert found.ended_at == _START + timedelta(seconds=9)
        assert found.elapsed_seconds == 9
        assert found.moving_seconds == 9

    def test_a_track_without_times_offers_none(self):
        """A planned route has no clock, and saying so is what lets the preview
        ask for a date instead of inventing one."""
        gpx = parse_gpx_bytes(_route_gpx([(46.0, 6.0), (46.1, 6.1)]))
        found = candidates(gpx)[0]
        assert found.has_times is False
        assert found.started_at is None
        assert found.moving_seconds is None

    def test_standing_still_is_not_moving_time(self):
        """Moving time used to be set equal to elapsed time, so every import
        claimed it never stopped — even when its own timestamps disagreed."""
        gpx = parse_gpx_bytes(_moving_track(stop_seconds=120))
        found = candidates(gpx)[0]
        assert found.elapsed_seconds == 128   # 8 one-second steps + the 120 s rest
        assert found.moving_seconds == 8     # the rest itself is not moving

    def test_a_recording_gap_is_not_counted(self):
        """A device switched off over lunch, or a fix lost in a tunnel, must not
        hand two hours to the ride's moving time."""
        gpx = parse_gpx_bytes(_moving_track(stop_seconds=7200))
        found = candidates(gpx)[0]
        assert found.elapsed_seconds == 7208
        assert found.moving_seconds == 8     # the two-hour gap is dropped whole


class TestStopsAndJitter:
    """The finding that made the first cut of this unit's release note false.

    A per-sample speed test is a displacement test in disguise: at 1 Hz, 0.3 m/s
    is 0.3 m between neighbours, which ordinary GPS jitter clears without the
    device going anywhere. Measured on a twenty-minute stationary recording it
    counted 91% of the stop as moving under half a metre of jitter, and 99%
    under one and a half.
    """

    @staticmethod
    def _stationary(count, sigma, rho, seed=4):
        """A phone sitting on a table: drift and jitter, going nowhere."""
        import math
        import random

        random.seed(seed)
        dx = dy = 0.0
        points, when = [], _START
        for _ in range(count):
            dx = rho * dx + random.gauss(0, sigma * math.sqrt(1 - rho * rho))
            dy = rho * dy + random.gauss(0, sigma * math.sqrt(1 - rho * rho))
            points.append((46.0 + dy / 111320.0,
                           6.0 + dx / (111320.0 * math.cos(math.radians(46.0))),
                           500.0, when))
            when += timedelta(seconds=1)
        return _track_gpx(points)

    @pytest.mark.parametrize("sigma,rho,label", [
        (0.5, 0.0, "half a metre of jitter"),
        (1.5, 0.0, "a metre and a half of jitter"),
        (2.5, 0.95, "two and a half metres of slow drift"),
    ])
    def test_a_stop_is_not_moving_however_the_fix_wanders(self, sigma, rho, label):
        found = candidates(parse_gpx_bytes(
            self._stationary(1200, sigma, rho)))[0]
        share = found.moving_seconds / found.elapsed_seconds
        assert share < 0.10, (
            f"{label}: {share:.0%} of a twenty-minute stop counted as moving"
        )

    def test_a_real_walk_is_still_entirely_moving(self):
        """The other half: a filter that calls a walk a stop is no better."""
        import random

        random.seed(7)
        points, when = [], _START
        for i in range(600):
            points.append((46.0 + (i * 1.4 + random.gauss(0, 1.5)) / 111320.0,
                           6.0, 500.0, when))
            when += timedelta(seconds=1)
        found = candidates(parse_gpx_bytes(_track_gpx(points)))[0]
        assert found.moving_seconds / found.elapsed_seconds > 0.95


class TestAwkwardClocks:
    def test_moving_time_never_exceeds_elapsed(self):
        """A device resyncing its clock emits the occasional backwards step;
        a preview showing more moving time than elapsed is visibly wrong."""
        offsets = [0, 20, 10, 30]
        points = [(46.0 + i * 1.26e-4, 6.0, 500.0, _START + timedelta(seconds=o))
                  for i, o in enumerate(offsets)]
        found = candidates(parse_gpx_bytes(_track_gpx(points)))[0]
        assert found.moving_seconds <= found.elapsed_seconds

    def test_elapsed_spans_the_whole_recording_despite_a_backwards_step(self):
        offsets = [0, 20, 10]
        points = [(46.0 + i * 1.26e-4, 6.0, 500.0, _START + timedelta(seconds=o))
                  for i, o in enumerate(offsets)]
        found = candidates(parse_gpx_bytes(_track_gpx(points)))[0]
        assert found.elapsed_seconds == 20      # not 10, the first-to-last span

    def test_a_file_mixing_zoned_and_unzoned_times_does_not_raise(self):
        """GPX times are UTC by spec, but a <time> written without a suffix
        parses naive — and mixing the two once raised out of the middle of a
        duration calculation, which downstream is a 500 rather than a refusal."""
        xml = (_HEADER + "<trk><trkseg>"
               '<trkpt lat="46.0" lon="6.0"><time>2024-08-12T07:33:00Z</time></trkpt>'
               '<trkpt lat="46.001" lon="6.0"><time>2024-08-12T07:33:30</time></trkpt>'
               '<trkpt lat="46.002" lon="6.0"><time>2024-08-12T07:34:00Z</time></trkpt>'
               "</trkseg></trk></gpx>").encode()
        found = candidates(parse_gpx_bytes(xml))[0]
        assert found.elapsed_seconds == 60
        assert found.moving_seconds is not None


class TestEmptyElements:
    def test_an_empty_track_does_not_suppress_a_real_route(self):
        """Some tools write a placeholder <trk> beside the real <rte>. Treating
        it as a track hid the route, and the file was then refused for having a
        track with no points — true, and useless."""
        xml = (_HEADER + "<trk><name>placeholder</name></trk>"
               "<rte><name>Planned</name>"
               '<rtept lat="46.0" lon="6.0"/><rtept lat="46.1" lon="6.1"/>'
               "</rte></gpx>").encode()
        gpx = parse_gpx_bytes(xml)
        found = candidates(gpx)
        assert len(found) == 1
        assert found[0].is_route is True
        assert validate_for_import(gpx) == []

    def test_an_empty_track_is_not_offered_as_a_choice(self):
        """One real track plus a placeholder is not a file to ask about."""
        xml = (_HEADER + "<trk><trkseg>"
               '<trkpt lat="46.0" lon="6.0"/><trkpt lat="46.1" lon="6.1"/>'
               "</trkseg></trk><trk><trkseg/></trk></gpx>").encode()
        gpx = parse_gpx_bytes(xml)
        assert len(candidates(gpx)) == 1
        assert validate_for_import(gpx) == []

    def test_indices_address_the_offered_list(self):
        """Dropping empties renumbers, so a picker's choice means what it says."""
        xml = (_HEADER + "<trk><trkseg/></trk>"
               "<trk><name>Real</name><trkseg>"
               '<trkpt lat="46.0" lon="6.0"/><trkpt lat="46.1" lon="6.1"/>'
               "</trkseg></trk></gpx>").encode()
        gpx = parse_gpx_bytes(xml)
        found = candidates(gpx)
        assert [c.index for c in found] == [0]
        assert found[0].name == "Real"
        assert validate_for_import(gpx, track_index=0) == []


class TestNameAndType:
    def test_the_track_name_wins(self):
        gpx = parse_gpx_bytes(_track_gpx(
            [(46.0, 6.0), (46.1, 6.1)], name="Morning ride to Annecy",
            metadata_name="export"))
        assert suggested_name(gpx, candidates(gpx)[0], "2024-08-12_073312.gpx") \
            == "Morning ride to Annecy"

    def test_metadata_name_is_next(self):
        gpx = parse_gpx_bytes(_track_gpx(
            [(46.0, 6.0), (46.1, 6.1)], metadata_name="Col de la Colombière"))
        assert suggested_name(gpx, candidates(gpx)[0], "export.gpx") \
            == "Col de la Colombière"

    def test_the_filename_is_the_last_resort(self):
        gpx = parse_gpx_bytes(_track_gpx([(46.0, 6.0), (46.1, 6.1)]))
        assert suggested_name(gpx, candidates(gpx)[0], "Sunday loop.gpx") \
            == "Sunday loop"

    def test_no_name_anywhere_is_no_name(self):
        gpx = parse_gpx_bytes(_track_gpx([(46.0, 6.0), (46.1, 6.1)]))
        assert suggested_name(gpx, candidates(gpx)[0], None) is None

    @pytest.mark.parametrize("raw,expected", [
        # Strava writes these.
        ("cycling", "ride"), ("running", "run"), ("hiking", "hike"),
        ("walking", "walk"),
        # Garmin Connect joins its words with underscores, which is what the
        # first version of this table missed entirely.
        ("road_biking", "ride"), ("mountain_biking", "ride"),
        ("gravel_cycling", "ride"), ("e_bike_fitness", "ride"),
        ("trail_running", "run"),
        # And the spellings in between.
        ("MTB", "ride"), ("Road cycling", "ride"), ("Trail Running", "run"),
        ("e-bike", "ride"), ("  Cycling  ", "ride"),
    ])
    def test_known_types_are_mapped(self, raw, expected):
        assert map_activity_type(raw) == expected

    @pytest.mark.parametrize("raw", ["9", "", None, "kitesurfing", "Type 3"])
    def test_unknown_types_stay_unset(self, raw):
        """Better to ask than to label a kite surf a hike."""
        assert map_activity_type(raw) is None

    def test_the_type_is_read_off_the_track(self):
        gpx = parse_gpx_bytes(_track_gpx(
            [(46.0, 6.0), (46.1, 6.1)], activity_type="cycling"))
        assert candidates(gpx)[0].activity_type == "ride"


class TestMultipleCandidates:
    def test_each_track_is_offered_with_what_it_would_import(self):
        two = (_track_gpx([(46.0, 6.0), (46.1, 6.1)], name="Lap 1").decode()
               .replace("</gpx>", "<trk><name>Lap 2</name><trkseg>"
                                  "<trkpt lat='45' lon='5'/>"
                                  "<trkpt lat='45.1' lon='5.1'/>"
                                  "<trkpt lat='45.2' lon='5.2'/></trkseg></trk></gpx>")
               .encode())
        found = candidates(parse_gpx_bytes(two))
        assert [c.name for c in found] == ["Lap 1", "Lap 2"]
        assert [c.point_count for c in found] == [2, 3]
        assert all(c.distance_m > 0 for c in found)

    def test_a_chosen_track_validates_on_its_own(self):
        two = (_track_gpx([(46.0, 6.0), (46.1, 6.1)]).decode()
               .replace("</gpx>", "<trk><trkseg><trkpt lat='45' lon='5'/>"
                                  "</trkseg></trk></gpx>")
               .encode())
        gpx = parse_gpx_bytes(two)
        assert validate_for_import(gpx, track_index=0) == []
        assert any("fewer than 2 points" in e
                   for e in validate_for_import(gpx, track_index=1))

    def test_an_out_of_range_choice_is_refused(self):
        gpx = parse_gpx_bytes(_track_gpx([(46.0, 6.0), (46.1, 6.1)]))
        assert validate_for_import(gpx, track_index=7) != []

    def test_a_negative_index_is_refused_rather_than_wrapping(self):
        """Python would happily hand back the last candidate; a picker sending
        -1 means something has gone wrong, not "the last one"."""
        gpx = parse_gpx_bytes(_track_gpx([(46.0, 6.0), (46.1, 6.1)]))
        with pytest.raises(GPXImportError):
            gpx_track_to_points(gpx, -1)


class TestUploadSize:
    def test_a_normal_file_passes(self):
        guard_upload_size(b"x" * 1024)

    def test_an_oversized_upload_is_refused_before_parsing(self):
        """gpxpy builds an object tree many times the size of the XML — 4.6 MB
        of file measured at 73 MB of heap — so a point cap applied after parsing
        is a cap that has already let the damage happen."""
        with pytest.raises(GPXImportError) as excinfo:
            guard_upload_size(b"x" * (MAX_IMPORT_BYTES + 1))
        assert "limit is 12 MB" in excinfo.value.errors[0]
