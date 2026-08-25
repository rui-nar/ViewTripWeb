"""GPX import: parse and validate uploaded GPX files for a single-track import."""

from typing import List

import gpxpy
import gpxpy.gpx

from src.models.track_edit import TrackPoint

MAX_IMPORT_POINTS = 50000


class GPXImportError(Exception):
    """Raised when a GPX file cannot be imported; carries human-readable reasons."""

    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def parse_gpx_bytes(data: bytes) -> gpxpy.gpx.GPX:
    """Parse raw GPX file bytes into a gpxpy.gpx.GPX object.

    Raises:
        GPXImportError: if the data is not a valid GPX/XML document.
    """
    try:
        return gpxpy.parse(data)
    except gpxpy.gpx.GPXException:
        raise GPXImportError(["File is not a valid GPX document."])


def validate_for_import(gpx: gpxpy.gpx.GPX) -> List[str]:
    """Return a list of rejection-reason strings; empty list means the GPX is importable.

    Checks: exactly one track, at least 2 points total (across segments), all
    points have valid lat/lng, and the point count is within MAX_IMPORT_POINTS.
    Multiple segments within the single track are allowed.
    """
    errors: List[str] = []

    if not gpx.tracks:
        errors.append("GPX contains no tracks.")
        return errors

    if len(gpx.tracks) > 1:
        errors.append(
            f"GPX contains {len(gpx.tracks)} tracks; only a single track is supported."
        )
        return errors

    track = gpx.tracks[0]
    points = [p for seg in track.segments for p in seg.points]

    if len(points) < 2:
        errors.append(f"Track has fewer than 2 points ({len(points)}).")

    for p in points:
        if p.latitude is None or p.longitude is None:
            errors.append("Track contains a point with missing coordinates.")
            break

    for p in points:
        if p.latitude is not None and not (-90 <= p.latitude <= 90):
            errors.append(f"Track contains an out-of-range latitude ({p.latitude}).")
            break

    for p in points:
        if p.longitude is not None and not (-180 <= p.longitude <= 180):
            errors.append(f"Track contains an out-of-range longitude ({p.longitude}).")
            break

    if len(points) > MAX_IMPORT_POINTS:
        errors.append(
            f"Track has too many points ({len(points)}); the limit is {MAX_IMPORT_POINTS}."
        )

    return errors


def gpx_track_to_points(gpx: gpxpy.gpx.GPX) -> List[TrackPoint]:
    """Flatten the single track's segments (already validated) into TrackPoints, in order."""
    track = gpx.tracks[0]
    return [
        TrackPoint(lat=p.latitude, lng=p.longitude, elev=p.elevation)
        for seg in track.segments
        for p in seg.points
    ]
