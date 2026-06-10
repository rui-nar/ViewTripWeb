"""Tests for the full-res geo endpoint's encoded-polyline payload, the
elevation-deferred load path, and background cache warming.

The /api/geo/project endpoint sends activity tracks as Google-encoded polylines
(properties.polyline, empty coordinates) instead of expanded [[lon,lat],…]
arrays, cutting a large trip's payload from ~17.7 MB to a couple of MB and
skipping the server-side decode. Segments keep expanded coordinates.
"""
from __future__ import annotations

import gzip
import json

import polyline as polyline_lib
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import models.db as db_module
import api.geo as geo_mod
from api.deps import get_current_user
from api.geo import router as geo_router, warm_geo_cache, _geo_cache
from models.project_db import DBActivity, DBProject, DBProjectItem
from models.user import UserInfo


_LINE = [(60.17, 24.94), (61.50, 23.77), (65.01, 25.48)]


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

    with Session(engine) as sess:
        user = UserInfo(display_name="Alice", email="a@b.c")
        sess.add(user)
        sess.commit()
        sess.refresh(user)
        uid = user.id
        project = DBProject(user_info_id=uid, name="Trip")
        sess.add(project)
        sess.commit()
        sess.refresh(project)
        pid = project.id

        # One activity with a real GPS polyline + a (large) elevation profile.
        enc = polyline_lib.encode(_LINE)
        ep = json.dumps({"distances_km": [0.0, 1.0], "elevations_m": [10.0, 20.0]})
        sess.add(DBActivity(
            id=111, user_info_id=uid, name="Ride", type="Ride",
            start_date="2026-06-01T00:00:00Z",
            summary_polyline=enc, elevation_profile_json=ep,
            start_latlng_json=json.dumps([_LINE[0][0], _LINE[0][1]]),
            end_latlng_json=json.dumps([_LINE[-1][0], _LINE[-1][1]]),
        ))
        sess.add(DBProjectItem(project_id=pid, position=0, item_type="activity", activity_id=111))
        sess.commit()

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(uid), "email": "a@b.c"}
    app.include_router(geo_router)
    client = TestClient(app)
    yield client, uid, "Trip", enc


def _decode_geo(resp) -> dict:
    # TestClient transparently decompresses gzip; resp.json() works directly.
    return resp.json()


def test_activity_sent_as_encoded_polyline_when_opted_in(env):
    client, uid, name, enc = env
    resp = client.get(f"/api/geo/project?name={name}&encoded=1")
    assert resp.status_code == 200
    geo = _decode_geo(resp)
    feats = [f for f in geo["features"] if f["properties"]["type"] == "activity"]
    assert len(feats) == 1
    props = feats[0]["properties"]
    # Encoded polyline carried verbatim; coordinates left empty for the client.
    assert props["polyline"] == enc
    assert feats[0]["geometry"]["coordinates"] == []
    # Decoding the payload reproduces the original line (lon/lat order in GeoJSON).
    decoded = polyline_lib.decode(props["polyline"])
    assert decoded[0] == pytest.approx(_LINE[0])
    assert decoded[-1] == pytest.approx(_LINE[-1])


def test_default_expands_coordinates_for_backward_compat(env):
    """Without ?encoded=1 the server expands activity polylines to full
    coordinates so a client that doesn't decode encoded polylines still renders
    them (no vanishing tracks on version skew)."""
    client, uid, name, _ = env
    resp = client.get(f"/api/geo/project?name={name}")
    assert resp.status_code == 200
    geo = _decode_geo(resp)
    feats = [f for f in geo["features"] if f["properties"]["type"] == "activity"]
    assert len(feats) == 1
    # No polyline property; coordinates expanded server-side.
    assert "polyline" not in feats[0]["properties"]
    coords = feats[0]["geometry"]["coordinates"]
    assert len(coords) == len(_LINE)
    assert coords[0] == pytest.approx([_LINE[0][1], _LINE[0][0]])  # [lon, lat]


def test_response_is_gzipped(env):
    client, *_ = env
    resp = client.get("/api/geo/project?name=Trip&encoded=1")
    assert resp.headers.get("content-encoding") == "gzip"


def test_cache_keys_per_format(env):
    client, *_ = env
    # Same project, two formats → independent cache entries.
    r1 = client.get("/api/geo/project?name=Trip&encoded=1")
    r2 = client.get("/api/geo/project?name=Trip&encoded=1")
    r3 = client.get("/api/geo/project?name=Trip")  # expanded — distinct key
    assert r1.headers["x-cache"] == "MISS"
    assert r2.headers["x-cache"] == "HIT"
    assert r3.headers["x-cache"] == "MISS"


def test_warm_geo_cache_populates_both_variants(env):
    client, uid, name, _ = env
    assert (uid, name, True) not in _geo_cache
    warm_geo_cache(uid, name)
    # Both the encoded and expanded payloads are warmed.
    assert (uid, name, True) in _geo_cache
    assert (uid, name, False) in _geo_cache
    # Subsequent endpoint calls on either format serve the warmed bytes.
    assert client.get(f"/api/geo/project?name={name}&encoded=1").headers["x-cache"] == "HIT"
    assert client.get(f"/api/geo/project?name={name}").headers["x-cache"] == "HIT"


def test_warm_geo_cache_defers_elevation(env, monkeypatch):
    """warm_geo_cache must load with include_elevation=False (geo never needs
    the elevation series — deferring it is what keeps the cold load fast)."""
    client, uid, name, _ = env
    seen = {}
    orig = geo_mod._repo.get_project

    def _spy(sess, user_info_id, project_name, **kwargs):
        seen.update(kwargs)
        return orig(sess, user_info_id, project_name, **kwargs)

    monkeypatch.setattr(geo_mod._repo, "get_project", _spy)
    warm_geo_cache(uid, name)
    assert seen.get("include_elevation") is False
