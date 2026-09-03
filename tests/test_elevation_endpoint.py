"""``GET /api/projects/{name}/elevation`` — issue #295, Phase 4.2.

The point of this route is that it is *additional*. ``GET /{name}`` keeps
serving ``elevation_profile`` inside the full details payload, because Android
and iOS builds in the wild read it from there; a newer client can fetch the
same series at a fraction of the size instead.

Harness mirrors ``test_project_details_cache.py``.
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import models.db as db_module
from api.deps import get_current_user
from api.geo import _geo_cache, _geo_gen
from api.projects import router as projects_router
from models.project_db import DBActivity, DBProject, DBProjectItem
from models.user import UserInfo
from src.project.elevation_codec import decode_profile

_POINTS = 400
_EP = {
    "distances_km": [i * 0.01 for i in range(_POINTS)],
    "elevations_m": [500.0 + i * 0.5 for i in range(_POINTS)],
}


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

        sess.add(DBActivity(
            id=111, user_info_id=uid, name="Ride", type="Ride",
            start_date="2026-06-01T00:00:00Z",
            elevation_profile_json=json.dumps(_EP),
        ))
        sess.add(DBProjectItem(
            project_id=project.id, position=0, item_type="activity", activity_id=111))
        sess.commit()

    current = {"uid": uid}
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(current["uid"])}
    app.include_router(projects_router)
    yield TestClient(app), uid, sid, lambda who: current.update(uid=who)


def _body(resp) -> dict:
    # The route hands back pre-gzipped bytes with an explicit Content-Encoding,
    # which the test client transparently decompresses for us.
    return resp.json()


def test_returns_the_profile_encoded(env):
    client, *_ = env
    resp = client.get("/api/projects/Trip/elevation")
    assert resp.status_code == 200
    decoded = decode_profile(_body(resp)["profiles"]["111"])
    assert len(decoded) == _POINTS
    assert decoded[-1][1] == pytest.approx(_EP["elevations_m"][-1], abs=0.051)


def test_it_is_far_smaller_than_the_details_equivalent(env):
    client, *_ = env
    encoded = _body(client.get("/api/projects/Trip/elevation"))["profiles"]["111"]
    details_profile = _body(client.get("/api/projects/Trip"))["activities"][0]["elevation_profile"]
    assert len(encoded) * 5 < len(json.dumps(details_profile))


def test_details_still_carries_the_raw_profile(env):
    # The compatibility guarantee: shipped mobile builds read elevation_profile
    # out of the full details payload and must keep working.
    client, *_ = env
    assert len(_body(client.get("/api/projects/Trip"))["activities"][0]["elevation_profile"]) == _POINTS


def test_second_request_is_a_cache_hit(env):
    client, *_ = env
    assert client.get("/api/projects/Trip/elevation").headers["x-cache"] == "MISS"
    assert client.get("/api/projects/Trip/elevation").headers["x-cache"] == "HIT"


def test_unknown_project_is_404(env):
    client, *_ = env
    assert client.get("/api/projects/NoSuchTrip/elevation").status_code == 404


def test_a_stranger_cannot_read_someone_elses_elevation(env):
    client, _uid, sid, act_as = env
    act_as(sid)
    assert client.get("/api/projects/Trip/elevation").status_code in (403, 404)
