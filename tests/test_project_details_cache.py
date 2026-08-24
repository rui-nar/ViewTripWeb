"""Regression tests for the ``GET /{name}`` (full-details) payload cache.

``get_project`` had zero caching: measured against a real 219-activity
project it re-queried and re-serialised the whole trip on *every* request —
12.3-13.4 s, cold or warm. It now rides the same per-project payload cache
as ``GET /{name}/meta`` (issue #178), keyed per caller for the identical
reason: journal entries are filtered to their author and ``caller_role`` is
baked into the body, so two members of the same trip must never share a
cache entry.
"""
from __future__ import annotations

import json

import polyline as polyline_lib
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import api.project_shared as shared_mod
import models.db as db_module
from api.deps import get_current_user
from api.geo import _geo_cache, _geo_gen, bust_project_cache
from api.projects import router as projects_router
from models.project_db import DBActivity, DBProject, DBProjectItem, DBProjectMember
from models.user import UserInfo

_LINE_BEFORE = [(60.0, 24.0), (61.0, 25.0)]
_LINE_AFTER = [(10.0, 4.0), (11.0, 5.0)]
_EP_BEFORE = {"distances_km": [0.0, 1.0], "elevations_m": [10.0, 20.0]}


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
        editor = UserInfo(display_name="Editor", email="editor@e.com")
        sess.add(owner); sess.add(editor); sess.commit()
        sess.refresh(owner); sess.refresh(editor)
        uid, eid = owner.id, editor.id

        project = DBProject(user_info_id=uid, name="Trip")
        sess.add(project); sess.commit(); sess.refresh(project)
        pid = project.id

        sess.add(DBProjectMember(project_id=pid, user_info_id=eid, role="co-owner", invited_by=uid))

        sess.add(DBActivity(
            id=111, user_info_id=uid, name="Ride", type="Ride",
            start_date="2026-06-01T00:00:00Z",
            summary_polyline=polyline_lib.encode(_LINE_BEFORE),
            elevation_profile_json=json.dumps(_EP_BEFORE),
            start_latlng_json=json.dumps(list(_LINE_BEFORE[0])),
            end_latlng_json=json.dumps(list(_LINE_BEFORE[-1])),
        ))
        sess.add(DBProjectItem(project_id=pid, position=0, item_type="activity", activity_id=111))
        sess.commit()

    current = {"uid": uid}
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(current["uid"])}
    app.include_router(projects_router)
    client = TestClient(app)

    def act_as(who_id: int):
        current["uid"] = who_id

    yield client, engine, uid, eid, act_as


def _activity(resp) -> dict:
    return resp.json()["activities"][0]


def test_second_request_is_a_cache_hit_and_skips_the_db_load(env, monkeypatch):
    client, _engine, uid, _eid, _act_as = env
    seen: list[dict] = []
    orig = shared_mod._repo.get_project

    def _spy(*args, **kwargs):
        seen.append(kwargs)
        return orig(*args, **kwargs)

    monkeypatch.setattr(shared_mod._repo, "get_project", _spy)

    first = client.get("/api/projects/Trip")
    assert first.status_code == 200
    assert first.headers["x-cache"] == "MISS"
    assert len(seen) == 1

    second = client.get("/api/projects/Trip")
    assert second.status_code == 200
    assert second.headers["x-cache"] == "HIT"
    # No further DB load — the second response was served straight from cache.
    assert len(seen) == 1


def test_mutation_busts_the_details_cache(env):
    client, _engine, uid, _eid, _act_as = env
    first = client.get("/api/projects/Trip")
    assert first.status_code == 200
    assert first.json()["trip_start"] is None

    r = client.put("/api/projects/Trip", json={"trip_start": "2026-07-01"})
    assert r.status_code == 200

    second = client.get("/api/projects/Trip")
    assert second.headers["x-cache"] == "MISS"
    assert second.json()["trip_start"] == "2026-07-01"


def test_mutating_the_activity_and_busting_manually_is_reflected(env):
    """Same as the geo-cache staleness suite's ``_mutate`` — a raw DB edit plus
    the standard bust call must be picked up by the details cache too, proving
    ``bust_project_cache`` covers the new "details" variant alongside "meta"
    and the geo variants without any dedicated invalidation code.
    """
    client, engine, uid, _eid, _act_as = env
    assert client.get("/api/projects/Trip").status_code == 200  # warm the cache

    with Session(engine) as sess:
        act = sess.exec(select(DBActivity).where(DBActivity.id == 111)).first()
        act.summary_polyline = polyline_lib.encode(_LINE_AFTER)
        sess.add(act)
        sess.commit()
    bust_project_cache(uid, "Trip")

    resp = client.get("/api/projects/Trip")
    assert resp.headers["x-cache"] == "MISS"
    decoded = polyline_lib.decode(_activity(resp)["map"]["summary_polyline"])
    assert decoded == pytest.approx(_LINE_AFTER)


def test_two_callers_get_their_own_scoped_response(env):
    client, _engine, uid, eid, act_as = env

    act_as(uid)
    owner_resp = client.get("/api/projects/Trip")
    assert owner_resp.headers["x-cache"] == "MISS"
    assert owner_resp.json()["caller_role"] == "owner"

    act_as(eid)
    editor_resp = client.get(f"/api/projects/Trip?owner={uid}")
    # Not served from the owner's cache entry — separately keyed and separately computed.
    assert editor_resp.headers["x-cache"] == "MISS"
    assert editor_resp.json()["caller_role"] == "co-owner"

    # Each caller's own repeat request is now a HIT of their own entry.
    act_as(uid)
    assert client.get("/api/projects/Trip").headers["x-cache"] == "HIT"
    act_as(eid)
    assert client.get(f"/api/projects/Trip?owner={uid}").headers["x-cache"] == "HIT"


def test_response_still_carries_the_heavy_fields_meta_omits(env):
    """A regression here would silently degrade /{name} back into /meta's shape."""
    client, _engine, _uid, _eid, _act_as = env
    resp = client.get("/api/projects/Trip")
    assert resp.status_code == 200
    act = _activity(resp)
    assert act["map"]["summary_polyline"] == polyline_lib.encode(_LINE_BEFORE)
    assert act["elevation_profile"] == [[0.0, 10.0], [1.0, 20.0]]

    meta_resp = client.get("/api/projects/Trip/meta")
    meta_act = meta_resp.json()["activities"][0]
    assert meta_act["map"]["summary_polyline"] is None
