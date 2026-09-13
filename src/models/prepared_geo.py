"""On-disk format for a line prepared for zoom-level-of-detail serving (#369).

What a prepared line holds and why:

* the **working set** — the line already strided to ``MAX_INPUT_POINTS``, which
  is all :func:`simplify_for_zoom` ever reads, so serving from it is identical
  to serving from the original at every level;
* its **vertex levels** — one byte per point, the lowest zoom level that keeps
  it (see :func:`~src.models.simplify.vertex_levels`), which turns a
  Ramer-Douglas-Peucker pass into a list comprehension;
* its **bounding box**, so "can this viewport show it" is O(1) rather than a
  walk over every coordinate.

Coordinates are stored as ``int32`` scaled by 1e5. That is **exact, not
lossy**: every track reaching the geo endpoints was decoded by
``polyline.decode``, which computes ``k / 100000.0``, so five decimals is the
true precision of the data and the integer round-trip is bit-for-bit. It also
halves the 16 bytes a pair of ``float64`` costs — and the unpacked form is kept
as the same ``array("i")``, so a cached trip costs 9 bytes per coordinate
(8 plus the level byte) against the 16 it cost before (issue #369).

Format v1, little-endian::

    u8   version
    u32  n
    4xf64  bbox (min_lon, min_lat, max_lon, max_lat)
    n x (i32 lon_e5, i32 lat_e5)
    n x u8 level

That is 9 bytes per coordinate plus a 37-byte header — at most 36 KB per
activity given the 4,000-point working set. Measured against the production
database: 959 activities with geometry come to ~8.4 MB in total, which is why
this stores the integers plainly rather than delta-encoding and compressing
them. If that ever stops being true, a v2 can; the version byte is here so it
can be told apart rather than guessed at.

Third ordinates (GeoJSON positions legally carry elevation) are **not** stored.
Nothing downstream of the simplified endpoint reads them — the elevation
profile is its own payload — and keeping them would cost a third of the file
for data no consumer wants.
"""
from __future__ import annotations

import struct
import sys
from array import array

import polyline as polyline_lib

from src.models.simplify import (
    PREPARED_GEO_VERSION,
    line_bbox,
    vertex_levels,
    working_set,
)
from src.utils.encryption_check import is_encrypted_envelope

# Little-endian throughout, so a blob written on one architecture reads on
# another. Native order would be a silent corruption on a big-endian host.
_HEADER = struct.Struct("<BI4d")
_BIG_ENDIAN = sys.byteorder == "big"
# "i" is the C int, 4 bytes on every platform this runs on; the format says
# int32, so refuse to start anywhere that is not true rather than write blobs
# no other host could read.
assert array("i").itemsize == 4

# What a stored integer is divided by to get the coordinate back. Public
# because the serving side holds the packed integers and does this division
# itself, per kept point, rather than expanding every point up front.
COORD_SCALE = 100_000.0


class PreparedGeoFormatError(ValueError):
    """A blob that cannot be read as a prepared line.

    Raised rather than returning None so a caller cannot mistake a corrupt row
    for an absent one: an absent row means "prepare it", a corrupt one means
    "something wrote nonsense", and the two deserve different logs.
    """


def pack_prepared_line(points: list, levels: bytes, bbox: tuple) -> bytes:
    """Serialise a prepared line. *points* must be the working set.

    *levels* must be :func:`~src.models.simplify.vertex_levels` of exactly
    those points — the two are index-aligned, and a mismatch is a programming
    error rather than a recoverable condition.
    """
    if len(levels) != len(points):
        raise ValueError(
            f"levels/points length mismatch: {len(levels)} vs {len(points)}")
    flat = array("i")
    for point in points:
        # round(), not int(): int() truncates towards zero, which would move a
        # negative coordinate by up to 1e-5 and break the round-trip identity
        # this format claims.
        flat.append(round(point[0] * COORD_SCALE))
        flat.append(round(point[1] * COORD_SCALE))
    if _BIG_ENDIAN:
        flat.byteswap()
    return _HEADER.pack(PREPARED_GEO_VERSION, len(points), *bbox) + flat.tobytes() + levels


def unpack_prepared_line(blob: bytes) -> tuple[array, bytes, tuple, int]:
    """``(flat, levels, bbox, version)`` from *blob*.

    ``flat`` is the ``array("i")`` of scaled ``lon, lat, lon, lat, ...`` as
    stored — one ``frombytes`` rather than a list of lists, because that list
    is what a cached trip would then hold: 128 bytes per coordinate against 8.

    The version is returned rather than checked here: deciding what to do with
    a stale row belongs to the caller, which can rebuild it, and this function
    has no way to.
    """
    if len(blob) < _HEADER.size:
        raise PreparedGeoFormatError(
            f"blob too short for a header: {len(blob)} bytes")
    version, count, *bbox = _HEADER.unpack_from(blob, 0)
    coords_end = _HEADER.size + count * 8
    if len(blob) != coords_end + count:
        raise PreparedGeoFormatError(
            f"blob is {len(blob)} bytes, header declares {count} points "
            f"({coords_end + count} expected)")
    flat = array("i")
    flat.frombytes(blob[_HEADER.size:coords_end])
    if _BIG_ENDIAN:
        flat.byteswap()
    return flat, blob[coords_end:], tuple(bbox), version


def prepare_polyline(summary_polyline: str | None) -> bytes | None:
    """The v1 blob for a Google-encoded *summary_polyline*, or None.

    None for anything the server cannot or need not prepare: no polyline, a
    client-side E2EE envelope (the server holds no key), or a track of fewer
    than two points, which the geo endpoints do not draw at all. A track of
    exactly two is prepared: it is served verbatim at every level, and a row
    for it means the trip is fully prepared rather than one activity short.

    A polyline that does not decode raises, as it does everywhere else; the
    write path catches that so one bad row cannot fail a whole sync.
    """
    if not summary_polyline or is_encrypted_envelope(summary_polyline):
        return None
    coords = [[lon, lat] for lat, lon in polyline_lib.decode(summary_polyline)]
    if len(coords) < 2:
        return None
    work = working_set(coords)
    return pack_prepared_line(work, vertex_levels(work), line_bbox(work))


# Stored in one statement so the check and the write cannot be separated, and
# with IS rather than = so a NULL polyline compares correctly instead of
# silently failing the guard.
_STORE_IF_UNCHANGED = (
    "INSERT INTO activity_geo_prepared (activity_id, version, blob) "
    "SELECT :id, :version, :blob "
    "WHERE (SELECT summary_polyline FROM activity WHERE id = :id) IS :poly "
    "ON CONFLICT(activity_id) DO UPDATE SET "
    "  version = excluded.version, blob = excluded.blob"
)


def store_prepared_if_unchanged(sess, activity_id: int, polyline: str | None,
                                blob: bytes) -> None:
    """Store *blob* for *activity_id*, but only if its polyline is still *polyline*.

    Both callers that prepare geometry **outside** a write transaction need this
    — the read path in ``api.geo`` and the backfill sweep — because preparing
    takes seconds, and a writer can land in between. Without the guard the
    prepared row would be replaced by geometry read *before* that write, at the
    current version, so it looks fresh and is served until the next polyline
    write. For an activity encrypted in that window it is worse: the encrypt
    path deletes the row, and an unguarded insert puts the **plaintext**
    geometry back for a track the server is no longer meant to read, which the
    share route would then serve publicly.

    One implementation rather than two: the guard is the whole correctness
    argument, and a second copy is how one of them ends up without it.

    Callers commit; this does not, so a batch is one transaction.
    """
    from sqlalchemy import text

    sess.exec(text(_STORE_IF_UNCHANGED).bindparams(
        id=activity_id, version=PREPARED_GEO_VERSION, blob=blob, poly=polyline))
