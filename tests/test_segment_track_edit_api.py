"""API tests for manually editing a transport segment's route track (issue #150).

Covers:
  - PUT .../segments/{id}/track stores the edited polyline, flips route_mode/
    route_status, and marks route_edited.
  - Validation: min 2 points, at most MAX_TRACK_POINTS points, transport-only
    (not flight), 404 on a missing segment.
  - resolve-route refuses to silently discard a manually edited route (409)
    unless force=True is passed; a forced resolve clears route_edited.
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import models.db as db_module
import api.segments as segments_mod
from api.deps import get_current_user
from api.segments import MAX_TRACK_POINTS, router as segments_router, _resolve_route_job
from models.project_db import DBProject
from models.user import UserInfo


def _seed(engine) -> int:
    with Session(engine) as sess:
        u = UserInfo(display_name="A", email="a@e.com")
        sess.add(u); sess.commit(); sess.refresh(u)
        proj = DBProject(user_info_id=u.id, name="My Trip")
        sess.add(proj); sess.commit(); sess.refresh(proj)
        return u.id


@pytest.fixture
def env(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(segments_mod, "bust_geo_cache", lambda *a, **k: None)
    monkeypatch.setattr(segments_mod, "warm_geo_cache", lambda *a, **k: None)
    SQLModel.metadata.create_all(engine)
    uid = _seed(engine)

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(uid), "email": "a@e.com"}
    app.include_router(segments_router)
    return TestClient(app), engine, uid


def _segment_body(**overrides) -> dict:
    body = {
        "segment_type": "boat",
        "label": "Helsinki -> Tallinn",
        "start_lat": 60.1719,
        "start_lon": 24.9414,
        "end_lat": 59.4370,
        "end_lon": 24.7536,
    }
    body.update(overrides)
    return body


def _load_segment(engine, uid, seg_id: str, name="My Trip"):
    project = segments_mod._repo.get_project(Session(engine), uid, name)
    return next(i.segment for i in project.items
                if i.item_type == "segment" and i.segment and i.segment.id == seg_id)


# ── PUT .../track ────────────────────────────────────────────────────────────

def test_edit_track_stores_polyline_and_marks_edited(env):
    client, engine, uid = env
    seg_id = client.post("/api/projects/My Trip/segments", json=_segment_body()).json()["id"]

    resp = client.put(
        f"/api/projects/My Trip/segments/{seg_id}/track",
        json={"points": [
            {"lat": 60.17, "lng": 24.94},
            {"lat": 59.9, "lng": 24.8},
            {"lat": 59.44, "lng": 24.75},
        ]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["route_mode"] == "ferry"
    assert body["route_status"] == "resolved"
    assert body["route_edited"] is True
    assert json.loads(body["route_polyline"]) == [
        [24.94, 60.17], [24.8, 59.9], [24.75, 59.44],
    ]

    seg = _load_segment(engine, uid, seg_id)
    assert seg.route_edited is True
    assert seg.route_mode == "ferry"
    assert seg.route_status == "resolved"
    assert json.loads(seg.route_polyline) == [
        [24.94, 60.17], [24.8, 59.9], [24.75, 59.44],
    ]


def test_edit_track_requires_at_least_two_points(env):
    client, *_ = env
    seg_id = client.post("/api/projects/My Trip/segments", json=_segment_body()).json()["id"]

    resp = client.put(
        f"/api/projects/My Trip/segments/{seg_id}/track",
        json={"points": [{"lat": 60.17, "lng": 24.94}]},
    )
    assert resp.status_code == 422


def test_edit_track_rejects_more_points_than_the_limit(env):
    """An oversized track is refused outright, never silently truncated.

    Truncating would throw away part of a user's manual edit without telling
    them; the 422 names the limit and the actual count so the client can say
    what to do about it.
    """
    client, engine, uid = env
    seg_id = client.post("/api/projects/My Trip/segments", json=_segment_body()).json()["id"]

    over = MAX_TRACK_POINTS + 1
    resp = client.put(
        f"/api/projects/My Trip/segments/{seg_id}/track",
        json={"points": [{"lat": 60.0 + i * 1e-6, "lng": 24.9} for i in range(over)]},
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert str(MAX_TRACK_POINTS) in detail and str(over) in detail

    # Nothing was written: the segment keeps its unresolved, unedited state.
    seg = _load_segment(engine, uid, seg_id)
    assert seg.route_polyline is None
    assert seg.route_edited is False


def test_edit_track_accepts_a_full_resolution_rail_route(env):
    """The limit must never reject geometry the server itself produced.

    9,700 points is the measured worst case for a real resolved route
    (Hamburg-Offenburg at full OSM-node resolution) — comfortably accepted.
    """
    client, engine, uid = env
    seg_id = client.post(
        "/api/projects/My Trip/segments", json=_segment_body(segment_type="train")
    ).json()["id"]

    points = [{"lat": 53.55 - i * 0.0005, "lng": 9.99 - i * 0.00012} for i in range(9700)]
    resp = client.put(
        f"/api/projects/My Trip/segments/{seg_id}/track", json={"points": points},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["route_mode"] == "rail"

    seg = _load_segment(engine, uid, seg_id)
    assert len(json.loads(seg.route_polyline)) == 9700


def test_edit_track_rejects_flight_segment(env):
    client, *_ = env
    seg_id = client.post(
        "/api/projects/My Trip/segments", json=_segment_body(segment_type="flight")
    ).json()["id"]

    resp = client.put(
        f"/api/projects/My Trip/segments/{seg_id}/track",
        json={"points": [{"lat": 60.17, "lng": 24.94}, {"lat": 59.44, "lng": 24.75}]},
    )
    assert resp.status_code == 400


def test_edit_track_not_found(env):
    client, *_ = env
    resp = client.put(
        "/api/projects/My Trip/segments/nope/track",
        json={"points": [{"lat": 1.0, "lng": 2.0}, {"lat": 3.0, "lng": 4.0}]},
    )
    assert resp.status_code == 404


# ── resolve-route vs. a manual edit ────────────────────────────────────────────

def test_resolve_route_blocked_when_edited_without_force(env, monkeypatch):
    client, engine, uid = env
    seg_id = client.post("/api/projects/My Trip/segments", json=_segment_body()).json()["id"]
    client.put(
        f"/api/projects/My Trip/segments/{seg_id}/track",
        json={"points": [{"lat": 60.17, "lng": 24.94}, {"lat": 59.44, "lng": 24.75}]},
    )
    monkeypatch.setattr(segments_mod, "enqueue", lambda *a, **k: True)

    resp = client.post(f"/api/projects/My Trip/segments/{seg_id}/resolve-route", json={})
    assert resp.status_code == 409

    # The guard must not have touched the stored edit.
    seg = _load_segment(engine, uid, seg_id)
    assert seg.route_edited is True
    assert seg.route_status == "resolved"


def test_resolve_route_allowed_with_force(env, monkeypatch):
    client, engine, uid = env
    seg_id = client.post("/api/projects/My Trip/segments", json=_segment_body()).json()["id"]
    client.put(
        f"/api/projects/My Trip/segments/{seg_id}/track",
        json={"points": [{"lat": 60.17, "lng": 24.94}, {"lat": 59.44, "lng": 24.75}]},
    )
    monkeypatch.setattr(segments_mod, "enqueue", lambda *a, **k: True)

    resp = client.post(
        f"/api/projects/My Trip/segments/{seg_id}/resolve-route",
        json={"force": True},
    )
    assert resp.status_code == 202
    assert resp.json() == {"status": "pending", "route_status": "pending"}

    seg = _load_segment(engine, uid, seg_id)
    assert seg.route_status == "pending"

    # The background job's success path is what actually clears route_edited —
    # confirm it does so on a segment that was previously marked edited.
    fake_line = [[24.9, 60.1], [24.7, 59.4]]
    monkeypatch.setattr(segments_mod, "_compute_segment_geometry",
                        lambda seg, params: (fake_line, 2, False, "ferry"))
    _resolve_route_job(uid, "My Trip", seg_id, {})

    seg = _load_segment(engine, uid, seg_id)
    assert seg.route_status == "resolved"
    assert seg.route_edited is False
    assert json.loads(seg.route_polyline) == fake_line
