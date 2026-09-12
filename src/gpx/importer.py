"""GPX import: parse, validate, and read what the file already tells us.

A GPX file carries far more than geometry, and the first version of this import
threw all of it away — it asked the user to type a date, a start time, an end
time and an activity type for a ride they did three weeks ago, while the file
in front of it held every one of those facts. This module reads them.

It also accepts a shape the first version refused. Issue #260 was written for
"a route drawn in Komoot or RideWithGPS", and those planners frequently export
a ``<rte>`` — a planned route — rather than a ``<trk>``. Looking only at
``gpx.tracks`` meant the motivating case came back as "GPX contains no tracks",
which is both a refusal and a lie about why.

Three vocabularies meet here and are deliberately kept apart:

* what the FILE says — ``<trk>``/``<rte>``, ``<name>``, ``<type>``, ``<time>``
* what the IMPORT decides — one chosen candidate, derived times, a mapped type
* what the USER confirms — all of the above, editable, in the preview

This module does the first two and is pure: no HTTP, no database, no clock.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Sequence, Tuple

import gpxpy
import gpxpy.gpx

from src.models.great_circle import haversine_km
from src.models.track_edit import TrackPoint

MAX_IMPORT_POINTS = 50000

#: Largest upload accepted, checked BEFORE parsing. gpxpy builds an object tree
#: many times the size of the XML — a 4.6 MB file measured at 73 MB of heap — so
#: a point-count limit applied after parsing is a limit that has already let the
#: damage happen. 20 MB is roughly 200k points, comfortably above the point cap
#: below and far below what would trouble the box.
MAX_IMPORT_BYTES = 20 * 1024 * 1024

#: Below this speed a sample is not moving: a stop at a café, a wait at a
#: junction, a fix drifting while the phone sits on a table. 0.3 m/s is about a
#: quarter of walking pace.
MOVING_MIN_SPEED_MS = 0.3

#: A gap longer than this is a pause in the RECORDING rather than a slow stretch
#: of it — the device was switched off, or lost its fix in a tunnel. Counting it
#: would hand a two-hour lunch to the ride's moving time.
MAX_SAMPLE_GAP_S = 300

#: GPX ``<type>`` is free text and every tool writes it differently. Mapped into
#: the types the app draws and colours; anything unrecognised stays None so the
#: user picks, rather than being handed a confident wrong answer.
_TYPE_ALIASES = {
    "run": "run", "running": "run", "jog": "run", "trail running": "run",
    "ride": "ride", "cycling": "ride", "bike": "ride", "biking": "ride",
    "cycle": "ride", "mtb": "ride", "mountain biking": "ride",
    "road cycling": "ride", "e-bike": "ride", "ebike": "ride",
    "hike": "hike", "hiking": "hike", "trekking": "hike",
    "mountaineering": "hike",
    "walk": "walk", "walking": "walk", "stroll": "walk",
}


class GPXImportError(Exception):
    """Raised when a GPX file cannot be imported; carries human-readable reasons."""

    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass(frozen=True)
class GpxCandidate:
    """One importable thing in the file — a recorded track, or a planned route.

    ``index`` addresses it for the picker a multi-candidate file needs: the
    first version refused those outright, leaving the user to go and edit the
    file in another tool.
    """
    index: int
    name: Optional[str]
    activity_type: Optional[str]
    points: List[TrackPoint]
    times: List[Optional[datetime]]
    is_route: bool

    @property
    def point_count(self) -> int:
        return len(self.points)

    @property
    def has_times(self) -> bool:
        return any(t is not None for t in self.times)

    @property
    def distance_m(self) -> float:
        return sum(
            haversine_km(a.lat, a.lng, b.lat, b.lng) * 1000.0
            for a, b in zip(self.points, self.points[1:])
        )

    @property
    def started_at(self) -> Optional[datetime]:
        return next((t for t in self.times if t is not None), None)

    @property
    def ended_at(self) -> Optional[datetime]:
        return next((t for t in reversed(self.times) if t is not None), None)

    @property
    def elapsed_seconds(self) -> Optional[int]:
        start, end = self.started_at, self.ended_at
        if start is None or end is None or end <= start:
            return None
        return int((end - start).total_seconds())

    @property
    def moving_seconds(self) -> Optional[int]:
        """Elapsed time minus the standing still, when the file has a clock.

        Until now moving time was simply set equal to elapsed time, so every
        imported activity claimed it had never stopped — even when its own
        timestamps said otherwise.
        """
        if not self.has_times:
            return None
        moving = 0.0
        for (p1, t1), (p2, t2) in zip(zip(self.points, self.times),
                                      zip(self.points[1:], self.times[1:])):
            if t1 is None or t2 is None:
                continue
            seconds = (t2 - t1).total_seconds()
            if seconds <= 0 or seconds > MAX_SAMPLE_GAP_S:
                continue
            metres = haversine_km(p1.lat, p1.lng, p2.lat, p2.lng) * 1000.0
            if metres / seconds >= MOVING_MIN_SPEED_MS:
                moving += seconds
        return int(moving)


def guard_upload_size(data: bytes) -> None:
    """Reject an oversized upload before it is parsed.

    Raises:
        GPXImportError: if the payload exceeds :data:`MAX_IMPORT_BYTES`.
    """
    if len(data) > MAX_IMPORT_BYTES:
        raise GPXImportError([
            f"File is {len(data) / 1_048_576:.1f} MB; the limit is "
            f"{MAX_IMPORT_BYTES // 1_048_576} MB."
        ])


def parse_gpx_bytes(data: bytes) -> gpxpy.gpx.GPX:
    """Parse raw GPX file bytes into a gpxpy.gpx.GPX object.

    Raises:
        GPXImportError: if the data is not a valid GPX/XML document.
    """
    try:
        return gpxpy.parse(data)
    except gpxpy.gpx.GPXException:
        raise GPXImportError(["File is not a valid GPX document."])


def candidates(gpx: gpxpy.gpx.GPX) -> List[GpxCandidate]:
    """Everything in the file that could become an activity, in file order.

    Tracks are preferred: a file holding both a recorded track and the route it
    was planned from should import what actually happened. Routes are read only
    when there is no track — the Komoot/RideWithGPS case issue #260 was written
    for, and the one the first version refused.

    Segments within one track are concatenated, as before: a recording paused
    and resumed is one activity, and the gap between segments is exactly what
    :attr:`GpxCandidate.moving_seconds` declines to count.
    """
    found: List[GpxCandidate] = []
    for index, track in enumerate(gpx.tracks):
        points, times = _flatten([p for seg in track.segments for p in seg.points])
        found.append(GpxCandidate(
            index=index, name=_clean(track.name),
            activity_type=map_activity_type(track.type),
            points=points, times=times, is_route=False,
        ))
    if found:
        return found

    for index, route in enumerate(gpx.routes):
        points, times = _flatten(route.points)
        found.append(GpxCandidate(
            index=index, name=_clean(route.name),
            activity_type=map_activity_type(getattr(route, "type", None)),
            points=points, times=times, is_route=True,
        ))
    return found


def _flatten(raw_points: Sequence) -> Tuple[List[TrackPoint], List[Optional[datetime]]]:
    points = [TrackPoint(lat=p.latitude, lng=p.longitude, elev=p.elevation)
              for p in raw_points]
    times = [getattr(p, "time", None) for p in raw_points]
    return points, times


def _clean(value: Optional[str]) -> Optional[str]:
    text = (value or "").strip()
    return text or None


def map_activity_type(raw: Optional[str]) -> Optional[str]:
    """Map a GPX ``<type>`` onto one of the app's activity types, or None.

    None for anything unrecognised — including the bare numbers some Garmin
    exports write — so the user is asked rather than told something confidently
    wrong.
    """
    key = (raw or "").strip().lower()
    return _TYPE_ALIASES.get(key)


def suggested_name(gpx: gpxpy.gpx.GPX, candidate: GpxCandidate,
                   filename: Optional[str] = None) -> Optional[str]:
    """The best name the file offers, in descending order of specificity.

    The track's own name, then the file's metadata name, then the filename's
    stem. A filename is the weakest of the three and often the worst thing to
    show a user — ``2024-08-12_073312`` is a name only a device would choose —
    but it beats nothing, and it is all the first version ever used.
    """
    metadata_name = _clean(getattr(gpx, "name", None))
    stem = None
    if filename:
        base = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        stem = _clean(base.rsplit(".", 1)[0])
    return candidate.name or metadata_name or stem


def validate_candidate(candidate: GpxCandidate) -> List[str]:
    """Return rejection reasons for one candidate; empty means importable."""
    errors: List[str] = []
    points = candidate.points

    if len(points) < 2:
        errors.append(f"Track has fewer than 2 points ({len(points)}).")

    if any(p.lat is None or p.lng is None for p in points):
        errors.append("Track contains a point with missing coordinates.")
    else:
        out_of_range_lat = next(
            (p.lat for p in points if not -90 <= p.lat <= 90), None)
        if out_of_range_lat is not None:
            errors.append(
                f"Track contains an out-of-range latitude ({out_of_range_lat}).")
        out_of_range_lng = next(
            (p.lng for p in points if not -180 <= p.lng <= 180), None)
        if out_of_range_lng is not None:
            errors.append(
                f"Track contains an out-of-range longitude ({out_of_range_lng}).")

    if len(points) > MAX_IMPORT_POINTS:
        errors.append(
            f"Track has too many points ({len(points)}); the limit is "
            f"{MAX_IMPORT_POINTS}."
        )
    return errors


def validate_for_import(gpx: gpxpy.gpx.GPX,
                        track_index: Optional[int] = None) -> List[str]:
    """Return rejection reasons for the file; empty means importable.

    With no ``track_index`` a file holding more than one candidate is still
    refused — choosing for the user would be guessing which ride they meant —
    but the message now says a choice exists rather than that the file is
    unsupported, and :func:`candidates` is what the caller offers them.
    """
    found = candidates(gpx)
    if not found:
        if gpx.waypoints:
            return ["GPX contains only waypoints, and no route or track to import."]
        return ["GPX contains no route or track to import."]

    if track_index is None:
        if len(found) > 1:
            noun = "routes" if found[0].is_route else "tracks"
            return [f"GPX contains {len(found)} {noun}; choose which one to import."]
        track_index = 0

    if not 0 <= track_index < len(found):
        return [f"GPX has no track at position {track_index}."]

    return validate_candidate(found[track_index])


def gpx_track_to_points(gpx: gpxpy.gpx.GPX,
                        track_index: int = 0) -> List[TrackPoint]:
    """Flatten a validated candidate into TrackPoints, in order."""
    return candidates(gpx)[track_index].points
