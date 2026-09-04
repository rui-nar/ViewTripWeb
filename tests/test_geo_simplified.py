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
from api.geo import _geo_cache, _geo_gen, router as geo_router
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
