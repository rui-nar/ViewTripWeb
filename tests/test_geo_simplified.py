"""Zoom level of detail for map geometry — issue #295.

The measurement behind it: a 219-activity trip carries 1,465,345 coordinates
and the map renders 6,051 of them, holding the rest as roughly 180 MB of Dart
heap on a device whose heap plateaus at ~625 MB and which is killed above
~1.3 GB. Simplifying to what a zoom can actually resolve removes the
difference, rather than decimating it away client-side after paying to
transfer and materialise it.
"""
from __future__ import annotations

import math

import pytest

from api.geo import simplify_geo_features
from src.models.simplify import simplify_lonlat, zoom_tolerance_m


def _line(n: int, *, jitter: float = 0.0) -> list[list[float]]:
    """A roughly straight east-west line of *n* points, optionally wobbling by
    *jitter* degrees so simplification has something to remove."""
    return [
        [7.0 + i * 0.0001, 45.0 + (jitter if i % 2 else 0.0)]
        for i in range(n)
    ]


def _feature(coords: list[list[float]], **props) -> dict:
    return {
        "type": "Feature",
        "properties": {"type": "activity", "activity_id": "1", **props},
        "geometry": {"type": "LineString", "coordinates": coords},
    }


# ── tolerance ────────────────────────────────────────────────────────────────

def test_tolerance_halves_with_each_zoom_level():
    a = zoom_tolerance_m(10, 45.0)
    b = zoom_tolerance_m(11, 45.0)
    assert b == pytest.approx(a / 2, rel=1e-6)


def test_tolerance_shrinks_away_from_the_equator():
    # Web Mercator stretches with latitude: a pixel covers less ground further
    # north, so a latitude-blind tolerance would over-simplify northern tracks.
    assert zoom_tolerance_m(10, 60.0) < zoom_tolerance_m(10, 0.0)
    assert zoom_tolerance_m(10, 60.0) == pytest.approx(
        zoom_tolerance_m(10, 0.0) * math.cos(math.radians(60.0)), rel=1e-6)


# ── simplification ───────────────────────────────────────────────────────────

def test_endpoints_are_always_kept():
    # A simplified line must still start and end exactly where it did, or the
    # track visibly detaches from its neighbours.
    poly = _line(500, jitter=0.0002)
    out = simplify_lonlat(poly, 50.0)
    assert out[0] == poly[0]
    assert out[-1] == poly[-1]


def test_a_coarser_zoom_yields_fewer_points():
    poly = _line(2000, jitter=0.0002)
    far = simplify_geo_features([_feature(poly)], 8)
    near = simplify_geo_features([_feature(poly)], 16)
    n_far = len(far[0]["geometry"]["coordinates"])
    n_near = len(near[0]["geometry"]["coordinates"])
    assert n_far < n_near <= len(poly)


def test_whole_trip_zoom_collapses_a_dense_track():
    # The case that matters: at the zoom that shows a whole trip, a pixel is
    # hundreds of metres and almost nothing survives.
    poly = _line(5000, jitter=0.00005)
    out = simplify_geo_features([_feature(poly)], 6)
    assert len(out[0]["geometry"]["coordinates"]) < len(poly) // 10


def test_short_lines_are_returned_untouched():
    for n in (0, 1, 2):
        poly = _line(n)
        out = simplify_geo_features([_feature(poly)], 10)
        assert out[0]["geometry"]["coordinates"] == poly


def test_the_input_features_are_not_mutated():
    # They may be shared with a cache entry; mutating in place would poison it.
    poly = _line(2000, jitter=0.0002)
    feature = _feature(poly)
    simplify_geo_features([feature], 8)
    assert len(feature["geometry"]["coordinates"]) == 2000


def test_an_encoded_polyline_is_left_alone():
    # Re-encoding would cost a decode plus an encode per activity to save
    # bytes the caller did not ask to save; the encoded variant exists to
    # avoid exactly that work.
    feature = {
        "type": "Feature",
        "properties": {"activity_id": "1", "polyline": "abcdef"},
        "geometry": {"type": "LineString", "coordinates": []},
    }
    out = simplify_geo_features([feature], 6)
    assert out[0]["properties"]["polyline"] == "abcdef"
    assert out[0]["geometry"]["coordinates"] == []


def test_malformed_geometry_passes_through_rather_than_raising():
    for geom in ({}, {"coordinates": None}, {"coordinates": [["x", "y"], [1, 2], [3, 4]]}):
        out = simplify_geo_features([{"type": "Feature", "geometry": geom}], 10)
        assert len(out) == 1


def test_latitude_is_taken_per_feature():
    # A trip spanning many latitudes must be simplified correctly along its
    # whole length, not against one global scale factor.
    equator = [[0.0 + i * 0.0001, 0.0 + (0.0002 if i % 2 else 0.0)] for i in range(1000)]
    north = [[0.0 + i * 0.0001, 60.0 + (0.0002 if i % 2 else 0.0)] for i in range(1000)]
    out = simplify_geo_features([_feature(equator), _feature(north)], 12)
    # Same shape at different latitudes: the northern one keeps at least as
    # much detail, because a pixel there covers less ground.
    assert len(out[1]["geometry"]["coordinates"]) >= len(out[0]["geometry"]["coordinates"])


# ── The route (issue #295) ───────────────────────────────────────────────────

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import models.db as db_module
from api.deps import get_current_user
from api.geo import _geo_cache, _geo_gen, _level_cache, router as geo_router
from models.project_db import DBActivity, DBProject, DBProjectItem
from models.user import UserInfo

_POINTS = 3000


@pytest.fixture
def env(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_module, "engine", engine)
    SQLModel.metadata.create_all(engine)
    _geo_cache.clear()
    _geo_gen.clear()
    _level_cache.clear()

    import polyline as polyline_lib

    with Session(engine) as sess:
        owner = UserInfo(display_name="Owner", email="owner@e.com")
        stranger = UserInfo(display_name="Nosy", email="nosy@e.com")
        sess.add(owner)
        sess.add(stranger)
        sess.commit()
        sess.refresh(owner)
        sess.refresh(stranger)
        uid, sid = owner.id, stranger.id

        project = DBProject(user_info_id=uid, name="Trip")
        sess.add(project)
        sess.commit()
        sess.refresh(project)

        # A wobbling track, so simplification has something to remove.
        pts = [(45.0 + (0.0002 if i % 2 else 0.0), 7.0 + i * 0.0001)
               for i in range(_POINTS)]
        sess.add(DBActivity(
            id=111, user_info_id=uid, name="Ride", type="Ride",
            start_date="2026-06-01T00:00:00Z",
            summary_polyline=polyline_lib.encode(pts),
            start_latlng_json=json.dumps(list(pts[0])),
            end_latlng_json=json.dumps(list(pts[-1])),
        ))
        sess.add(DBProjectItem(
            project_id=project.id, position=0, item_type="activity", activity_id=111))
        sess.commit()

    current = {"uid": uid}
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(current["uid"])}
    app.include_router(geo_router)
    yield TestClient(app), uid, sid, lambda who: current.update(uid=who)


def _points(resp) -> int:
    return len(resp.json()["features"][0]["geometry"]["coordinates"])


def test_route_returns_fewer_points_at_a_coarser_zoom(env):
    client, *_ = env
    far = client.get("/api/geo/project/simplified?name=Trip&zoom=8")
    near = client.get("/api/geo/project/simplified?name=Trip&zoom=17")
    assert far.status_code == near.status_code == 200
    assert _points(far) < _points(near) <= _POINTS


def test_route_saves_substantially_against_full_resolution(env):
    client, *_ = env
    full = client.get("/api/geo/project?name=Trip")
    coarse = client.get("/api/geo/project/simplified?name=Trip&zoom=8")
    assert _points(coarse) * 10 < _points(full), (
        "the whole point is holding a fraction of the geometry at trip zoom"
    )


def test_second_request_for_the_same_level_is_a_cache_hit(env):
    client, *_ = env
    assert client.get(
        "/api/geo/project/simplified?name=Trip&zoom=10").headers["x-cache"] == "MISS"
    assert client.get(
        "/api/geo/project/simplified?name=Trip&zoom=10").headers["x-cache"] == "HIT"


def test_zoom_is_rounded_up_so_a_level_is_never_under_detailed(env):
    # Flooring served 11.9 the zoom-11 tolerance — 1.87x too coarse, about two
    # pixels of visible drift. Ceiling shares a cache entry with 12, not 11.
    client, *_ = env
    client.get("/api/geo/project/simplified?name=Trip&zoom=12")
    hit = client.get("/api/geo/project/simplified?name=Trip&zoom=11.9")
    assert hit.headers["x-cache"] == "HIT"


def test_out_of_range_zoom_is_rejected(env):
    client, *_ = env
    for z in (-1, 23, 100):
        assert client.get(
            f"/api/geo/project/simplified?name=Trip&zoom={z}").status_code == 400


def test_unknown_project_is_404(env):
    client, *_ = env
    assert client.get(
        "/api/geo/project/simplified?name=NoSuchTrip&zoom=10").status_code == 404


def test_a_stranger_cannot_read_someone_elses_geometry(env):
    client, _uid, sid, act_as = env
    act_as(sid)
    assert client.get(
        "/api/geo/project/simplified?name=Trip&zoom=10").status_code in (403, 404)


def test_full_resolution_endpoint_is_unchanged(env):
    # It is an additional endpoint: shipped clients keep the geometry they
    # expect.
    client, *_ = env
    assert _points(client.get("/api/geo/project?name=Trip")) == _POINTS


# ── Cost and coarseness bounds (issue #295 regressions) ──────────────────────
#
# The first cut of this endpoint measured 21.6 s per request on a 219-activity
# trip and returned 515 coordinates for it — 2.4 per activity, a straight line
# per leg. Both are bounded now, and both bounds are asserted because either
# one silently drifting makes the endpoint worse than what it replaced.

from src.models.simplify import simplify_for_zoom


def _wiggly(n: int) -> list[list[float]]:
    lat, lon, out = 45.0, 7.0, []
    for i in range(n):
        lon += 0.00003 + math.sin(i / 50.0) * 0.00002
        lat += math.cos(i / 37.0) * 0.00002
        out.append([lon, lat])
    return out


def test_a_track_never_collapses_below_the_floor():
    # Whole-trip zoom, where a pixel is hundreds of metres.
    out = simplify_for_zoom(_wiggly(5000), 5)
    assert len(out) >= 32


def test_the_floor_is_at_least_what_the_client_would_render_anyway():
    # The client's own budget worked out at ~27 points per activity on the
    # trip that prompted this. A floor below that is a regression.
    assert simplify_for_zoom(_wiggly(5000), 5).__len__() >= 27


def test_the_floor_keeps_the_shape_rather_than_just_the_ends():
    out = simplify_for_zoom(_wiggly(5000), 4)
    # A strided sample of a winding path visits many distinct latitudes; two
    # endpoints would not.
    assert len({round(p[1], 4) for p in out}) > 5


def test_work_is_bounded_regardless_of_input_size():
    small = simplify_for_zoom(_wiggly(4000), 13)
    large = simplify_for_zoom(_wiggly(200000), 13)
    # Both run over at most max_input_points, so the larger input cannot
    # return a wildly larger result — that boundedness is the cost guarantee.
    assert len(large) <= 4000
    assert len(small) <= 4000


def test_zooming_in_still_yields_more_detail_than_the_floor():
    coarse = simplify_for_zoom(_wiggly(20000), 5)
    fine = simplify_for_zoom(_wiggly(20000), 15)
    assert len(fine) > len(coarse)


def test_endpoints_survive_the_floor_path():
    poly = _wiggly(5000)
    out = simplify_for_zoom(poly, 4)
    assert out[0] == poly[0]
    assert out[-1] == poly[-1]


# ── Viewport bounding box (issue #324) ────────────────────────────────
#
# Zoom bounds the *detail*, not the *extent*: at zoom 15 a deep zoom still
# returned the whole trip at that detail, and simplified all of it. Measured on
# a 219-activity trip, simplification alone cost 0.19 s at zoom 9, 2.94 s at
# zoom 12 and 6.98 s at zoom 15 — the cost rises with zoom while the saving
# falls. The box makes the deep-zoom case bounded in both directions.

from src.models.simplify import bboxes_intersect, line_bbox, snap_bbox_to_tiles


def _at(lon: float, lat: float, n: int = 400) -> list[list[float]]:
    """A wobbling line near (lon, lat), small enough to sit inside one viewport."""
    return [[lon + i * 0.00002, lat + (0.0002 if i % 2 else 0.0)] for i in range(n)]


def test_a_line_outside_the_box_falls_to_the_whole_trip_floor():
    # Not dropped, and not two points: exactly what a whole-trip zoom would
    # have produced for it. That equivalence is the safety argument — the
    # feature is no coarser than something the client already renders and
    # exports at another zoom.
    poly = _at(7.0, 45.0, 5000)
    off = simplify_for_zoom(poly, 15, bbox=(20.0, 20.0, 21.0, 21.0))
    assert len(off) == 32
    assert off[0] == poly[0] and off[-1] == poly[-1]
    assert off == simplify_for_zoom(poly, 3)


def test_a_line_inside_the_box_is_untouched_by_it():
    poly = _at(7.0, 45.0, 5000)
    assert (simplify_for_zoom(poly, 15, bbox=(6.0, 44.0, 8.0, 46.0))
            == simplify_for_zoom(poly, 15))


def test_a_line_merely_clipping_the_box_still_counts_as_visible():
    # Its bbox overlaps even though most of it is off screen; drawing only the
    # part inside would leave a visible gap at the edge of the viewport.
    poly = _at(7.0, 45.0, 5000)
    assert len(simplify_for_zoom(poly, 15, bbox=(7.05, 44.9, 9.0, 46.0))) > 32


def test_malformed_geometry_still_passes_through_with_a_box():
    # The intersection test compares coordinates, so bad data reaches it
    # first now. One bad point must still not 500 a whole project's map.
    for geom in ({}, {"coordinates": None},
                 {"coordinates": [["x", "y"], [1, 2], [3, 4]]},
                 {"coordinates": [[1], [2], [3]]}):
        out = simplify_geo_features(
            [{"type": "Feature", "geometry": geom}], 12, (6.0, 44.0, 8.0, 46.0))
        assert len(out) == 1


def test_a_line_entering_the_box_late_is_still_visible():
    # The intersection test short-circuits on the first point, because at
    # whole-trip zoom every line is on screen and the full walk would be pure
    # added cost (measured 0.24 s -> 0.34 s on a 1.47 M-point trip). A line
    # that starts outside and enters must not be lost to that shortcut.
    poly = [[7.0 + i * 0.001, 45.0 + (0.0002 if i % 2 else 0.0)]
            for i in range(2000)]
    kept = simplify_for_zoom(poly, 15, bbox=(8.0, 44.9, 8.5, 45.1))
    assert len(kept) > 32
    assert kept == simplify_for_zoom(poly, 15), "kept exactly as if unscoped"


def test_the_box_never_drops_a_feature():
    # geo is read as a description of the WHOLE trip by the segment-overlay
    # reconciliation (a tombstone is cleared when the server geo no longer
    # mentions its id), by fit-to-bounds, and by the export path. A missing
    # feature would silently break all three.
    features = [_feature(_at(7.0, 45.0)), _feature(_at(30.0, 60.0))]
    out = simplify_geo_features(features, 15, (6.0, 44.0, 8.0, 46.0))
    assert len(out) == 2
    assert all(len(f["geometry"]["coordinates"]) >= 2 for f in out)


def test_the_box_is_where_the_server_cpu_goes(monkeypatch):
    # The saving is structural, not incidental: an off-box line must not reach
    # the Ramer-Douglas-Peucker pass at all.
    import src.models.simplify as simplify_mod

    calls = []
    real = simplify_mod.simplify_lonlat
    monkeypatch.setattr(simplify_mod, "simplify_lonlat",
                        lambda poly, tol: calls.append(len(poly)) or real(poly, tol))
    features = [_feature(_at(7.0, 45.0)) for _ in range(3)]
    features += [_feature(_at(30.0 + i, 60.0)) for i in range(20)]
    simplify_geo_features(features, 15, (6.0, 44.0, 8.0, 46.0))
    assert len(calls) == 3, "only the three visible lines are worth simplifying"


# ── Snapping, which is what bounds the cache ────────────────────────────────

def test_snapping_is_outward_so_the_answer_is_a_superset():
    box = (7.3, 45.3, 7.4, 45.4)
    snapped, _ = snap_bbox_to_tiles(box, 12)
    assert snapped[0] <= box[0] and snapped[1] <= box[1]
    assert snapped[2] >= box[2] and snapped[3] >= box[3]


def test_neighbouring_viewports_share_one_key():
    # Raw viewport floats would mean a distinct cache entry per pan pixel.
    # This project has already OOM-killed its API container once with a payload
    # cache bounded by the wrong thing.
    a = snap_bbox_to_tiles((7.30, 45.30, 7.32, 45.32), 12)[1]
    b = snap_bbox_to_tiles((7.3001, 45.3001, 7.3201, 45.3201), 12)[1]
    assert a == b


def test_a_far_pan_does_get_its_own_key():
    a = snap_bbox_to_tiles((7.3, 45.3, 7.4, 45.4), 12)[1]
    b = snap_bbox_to_tiles((9.3, 45.3, 9.4, 45.4), 12)[1]
    assert a != b


def test_a_degenerate_box_still_covers_a_whole_tile():
    snapped, tiles = snap_bbox_to_tiles((7.0, 45.0, 7.0000001, 45.0000001), 12)
    assert tiles[2] > tiles[0] and tiles[3] > tiles[1]
    assert snapped[0] < snapped[2] and snapped[1] < snapped[3]


def test_snapping_clamps_to_the_world():
    snapped, tiles = snap_bbox_to_tiles((-180.0, -89.0, 180.0, 89.0), 3)
    assert tiles == (0, 0, 8, 8)
    assert snapped[0] == -180.0 and snapped[2] == 180.0


def test_line_bbox_tolerates_an_elevation_third_element():
    # GeoJSON positions legally carry one; `for x, y in poly` would raise.
    assert line_bbox([[1.0, 2.0, 300.0], [3.0, 4.0, 310.0]]) == (1.0, 2.0, 3.0, 4.0)


def test_touching_boxes_intersect():
    assert bboxes_intersect((0, 0, 1, 1), (1, 1, 2, 2))
    assert not bboxes_intersect((0, 0, 1, 1), (1.001, 1, 2, 2))


# ── The route ────────────────────────────────────────────────────────────────

def test_the_box_shrinks_the_payload_for_an_off_screen_trip(env):
    client, *_ = env
    whole = client.get("/api/geo/project/simplified?name=Trip&zoom=15")
    # A viewport on the other side of Europe: the trip is off screen entirely.
    scoped = client.get(
        "/api/geo/project/simplified?name=Trip&zoom=15&bbox=20,50,21,51")
    assert scoped.status_code == 200
    assert _points(scoped) < _points(whole)
    assert len(scoped.json()["features"]) == len(whole.json()["features"])


def test_the_box_keeps_full_detail_for_what_is_on_screen(env):
    client, *_ = env
    whole = client.get("/api/geo/project/simplified?name=Trip&zoom=15")
    on_screen = client.get(
        "/api/geo/project/simplified?name=Trip&zoom=15&bbox=6,44,9,46")
    assert _points(on_screen) == _points(whole)


def test_whole_trip_zoom_degenerates_to_the_trip_bounds(env):
    # At a zoom that shows the entire trip the box contains it, so nothing is
    # scoped away. This must fall out, not need a special mode.
    client, *_ = env
    scoped = client.get(
        "/api/geo/project/simplified?name=Trip&zoom=6&bbox=-20,30,40,60")
    plain = client.get("/api/geo/project/simplified?name=Trip&zoom=6")
    assert _points(scoped) == _points(plain)


def test_a_second_box_at_the_same_level_does_not_rebuild(env):
    """The regression this replaces (issue #324).

    With the box in the cache key, every pan to a new tile range rebuilt the
    level — and a rebuild decodes every activity polyline before it simplifies
    anything (1.83 s measured for a 219-activity trip), on a single-process
    server where that CPU-bound work also starves unrelated requests. The
    level is what costs; the box is a pass over the result.
    """
    client, *_ = env
    # zoom 17, where the on-box answer is far above the floor — at coarse
    # zooms both boxes land on it and the assertion below could not tell a
    # reused level from a rebuilt one.
    first = client.get("/api/geo/project/simplified?name=Trip&zoom=17&bbox=6,44,9,46")
    assert first.headers["x-cache"] == "MISS"
    elsewhere = client.get(
        "/api/geo/project/simplified?name=Trip&zoom=17&bbox=20,50,21,51")
    assert elsewhere.headers["x-cache"] == "HIT"
    # Reused the level, but still answered for *this* box: the track is
    # nowhere near it, so it comes back at the floor.
    assert _points(elsewhere) <= 32 < _points(first)


def test_a_bust_still_rebuilds_the_level(env):
    # The level cache holds Python objects rather than bytes, so it needs the
    # same generation guard the byte cache has, or an edit would leave a stale
    # map served for the whole 15-minute TTL.
    from api.geo import bust_geo_cache
    client, uid, *_ = env
    client.get("/api/geo/project/simplified?name=Trip&zoom=12")
    assert client.get(
        "/api/geo/project/simplified?name=Trip&zoom=12").headers["x-cache"] == "HIT"
    bust_geo_cache(uid, "Trip")
    assert client.get(
        "/api/geo/project/simplified?name=Trip&zoom=12").headers["x-cache"] == "MISS"


def test_a_tiny_pan_reuses_the_cached_entry(env):
    client, *_ = env
    client.get("/api/geo/project/simplified?name=Trip&zoom=12&bbox=7.30,45.30,7.32,45.32")
    hit = client.get(
        "/api/geo/project/simplified?name=Trip&zoom=12&bbox=7.3001,45.3001,7.3201,45.3201")
    assert hit.headers["x-cache"] == "HIT", (
        "the server snaps the box itself, so an unsnapped client cannot mint "
        "an entry per pan pixel"
    )


def test_a_boxed_response_does_not_poison_the_unboxed_one(env):
    client, *_ = env
    # zoom 17, where the unboxed answer is far above the floor, so "the boxed
    # entry was served instead" would be unmissable.
    client.get("/api/geo/project/simplified?name=Trip&zoom=17&bbox=20,50,21,51")
    plain = client.get("/api/geo/project/simplified?name=Trip&zoom=17")
    # A cache hit here is correct now — the cached level is box-independent and
    # the box is applied per request. What must hold is the *content*: the
    # unboxed caller gets the unboxed answer, not the floored one the previous
    # caller was served.
    assert _points(plain) > 32


def test_an_older_client_sending_no_box_is_unaffected(env):
    client, *_ = env
    before = _points(client.get("/api/geo/project/simplified?name=Trip&zoom=12"))
    client.get("/api/geo/project/simplified?name=Trip&zoom=12&bbox=20,50,21,51")
    assert _points(client.get("/api/geo/project/simplified?name=Trip&zoom=12")) == before


@pytest.mark.parametrize("bad", [
    "1,2,3",
    "1,2,3,4,5",
    "a,b,c,d",
    "9,44,6,46",       # inverted longitude
    "6,46,9,44",       # inverted latitude
    "-200,44,9,46",    # out of range
    "6,-95,9,46",
    "",
])
def test_a_malformed_box_is_rejected_rather_than_ignored(env, bad):
    # Falling through as "no box" would serve the whole trip while the client
    # believed it held viewport-scoped geometry.
    client, *_ = env
    assert client.get(
        f"/api/geo/project/simplified?name=Trip&zoom=12&bbox={bad}").status_code == 400


def test_the_box_does_not_change_the_auth_boundary(env):
    client, _uid, sid, act_as = env
    act_as(sid)
    assert client.get(
        "/api/geo/project/simplified?name=Trip&zoom=12&bbox=6,44,9,46"
    ).status_code in (403, 404)


# ── The level cache, after the adversarial review of #328 ────────────────────
#
# The review found three things the route tests could not see, because
# X-Cache reads the same either way: a level too large to cache rebuilt
# forever and silently; a bust left the entry resident, so a dropped Redis
# generation bump would serve a pre-edit map for the full 15-minute TTL; and
# eviction was oldest-inserted rather than least-recently-used, so a level
# being panned around lost to a cold one on age alone.

from api.geo import (
    _LEVEL_CACHE_MAX_ENTRY_COORDS,
    _level_cache_get,
    _level_cache_store,
    restrict_geo_features_to_bbox,
)
from src.models.simplify import restrict_to_bbox, simplify_for_zoom


def _feat(n: int, lon: float = 7.0) -> dict:
    return _feature([[lon + i * 0.0001, 45.0] for i in range(n)])


def test_a_level_too_large_to_cache_is_not_stored():
    _level_cache.clear()
    big = [_feat(_LEVEL_CACHE_MAX_ENTRY_COORDS + 10)]
    _level_cache_store((1, "Big", 17), big, 0)
    assert _level_cache_get((1, "Big", 17)) is None, (
        "storing it would let one entry evict everything else and still not fit"
    )


def test_a_level_within_the_entry_cap_is_stored():
    _level_cache.clear()
    _level_cache_store((1, "Ok", 12), [_feat(100)], 0)
    assert _level_cache_get((1, "Ok", 12)) is not None


def test_a_bust_drops_the_entry_rather_than_only_marking_it_stale():
    # Not the same as the route-level bust test: that one passes on the
    # generation guard alone. This pins the *direct* drop, which is what still
    # holds if the shared generation bump is lost.
    from api.geo import bust_geo_cache
    _level_cache.clear()
    _level_cache_store((7, "Trip", 12), [_feat(100)], 0)
    assert (7, "Trip", 12) in _level_cache
    bust_geo_cache(7, "Trip")
    assert (7, "Trip", 12) not in _level_cache


def test_reading_a_level_refreshes_its_deadline():
    # Eviction picks the entry closest to expiry, and every level shares one
    # TTL — so without this, "closest to expiry" means "stored first" and a hot
    # level is evicted before a cold one.
    _level_cache.clear()
    _level_cache_store((1, "Old", 12), [_feat(100)], 0)
    _level_cache_store((1, "New", 12), [_feat(100)], 0)
    before = _level_cache[(1, "Old", 12)][1]
    _level_cache_get((1, "Old", 12))
    assert _level_cache[(1, "Old", 12)][1] > before
    assert _level_cache[(1, "Old", 12)][1] > _level_cache[(1, "New", 12)][1]


# ── restrict_to_bbox, which production now calls and the older bbox tests
#    (which go through simplify_geo_features) no longer reach ────────────────

def test_a_visible_line_is_returned_unchanged_and_unaliased():
    poly = [[7.0 + i * 0.001, 45.0] for i in range(200)]
    assert restrict_to_bbox(poly, (6.0, 44.0, 9.0, 46.0)) is poly


def test_an_off_box_line_is_floored_keeping_both_ends():
    poly = [[7.0 + i * 0.001, 45.0] for i in range(200)]
    out = restrict_to_bbox(poly, (20.0, 50.0, 21.0, 51.0))
    assert len(out) == 32
    assert out[0] == poly[0] and out[-1] == poly[-1]


def test_a_line_already_at_the_floor_is_left_alone():
    poly = [[7.0 + i * 0.001, 45.0] for i in range(20)]
    assert restrict_to_bbox(poly, (20.0, 50.0, 21.0, 51.0)) is poly


def test_flooring_a_simplified_line_matches_flooring_the_original():
    # The equivalence the split rests on: applying the box *after* the level
    # was simplified must give what simplifying with the box gave. Same count,
    # same endpoints — the interior differs only for geometry that is off
    # screen by definition.
    poly = [[7.0 + i * 0.0001, 45.0 + (0.0002 if i % 2 else 0.0)]
            for i in range(3000)]
    far = (20.0, 50.0, 21.0, 51.0)
    in_one_pass = simplify_for_zoom(poly, 14, bbox=far)
    after_the_fact = restrict_to_bbox(simplify_for_zoom(poly, 14), far)
    assert len(in_one_pass) == len(after_the_fact)
    assert in_one_pass[0] == after_the_fact[0]
    assert in_one_pass[-1] == after_the_fact[-1]


def test_restricting_features_never_mutates_the_cached_level():
    # The cache holds these objects and hands them to every later request, so
    # a single in-place write would corrupt the map for everyone.
    level = [_feat(200)]
    original = [list(c) for c in level[0]["geometry"]["coordinates"]]
    out = restrict_geo_features_to_bbox(level, (20.0, 50.0, 21.0, 51.0))
    assert level[0]["geometry"]["coordinates"] == original
    assert out[0] is not level[0]
    assert out[0]["geometry"]["coordinates"] is not level[0]["geometry"]["coordinates"]
