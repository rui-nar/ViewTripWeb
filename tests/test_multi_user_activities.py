"""Multi-user Strava/import correctness for shared projects (issue #106, U3).

A project shared with a companion can hold activities imported by DIFFERENT
users. Every path that talks to Strava about them must use the right account:

* imports record the IMPORTER's user_info_id on new activity rows;
* "refresh from Strava" is restricted to the activity's importer (403);
* background enrichment uses the importer's client and busts the OWNER's
  geo cache;
* sync/check and the Strava/Polarsteps import screens run against the
  CALLER's own token/cache, with in_project/already_imported flags computed
  against the shared project.
"""
from __future__ import annotations

import json
import time

import polyline as polyline_lib
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import api.activities as activities_module
import api.polarsteps as polarsteps_module
import models.db as db_module
from api.deps import get_current_user
from api.activities import router as activities_router
from api.polarsteps import router as polarsteps_router
from api.projects import router as projects_router
from api.strava import router as strava_router
from models.project_db import (
    DBActivity,
    DBMemory,
    DBProject,
    DBProjectItem,
    DBProjectMember,
    DBStravaCache,
)
from models.user import StravaToken, UserInfo

_TRACK = [(48.0, 2.0), (48.0, 2.01), (48.0, 2.02)]


def _raw_act(act_id: int, name: str = "Run", start: str = "2024-06-02T10:00:00Z") -> dict:
    """Minimal raw Strava API activity dict accepted by Activity.from_strava_api."""
    return {
        "id": act_id,
        "name": name,
        "type": "Run",
        "distance": 5000.0,
        "moving_time": 1800,
        "elapsed_time": 2000,
        "total_elevation_gain": 50.0,
        "start_date": start,
        "start_date_local": start,
        "map": {"summary_polyline": polyline_lib.encode(_TRACK)},
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

    with Session(engine) as sess:
        owner = UserInfo(display_name="Owner", email="owner@e.com")
        editor = UserInfo(display_name="Editor", email="editor@e.com")
        sess.add(owner); sess.add(editor); sess.commit()
        sess.refresh(owner); sess.refresh(editor)
        proj = DBProject(user_info_id=owner.id, name="Trip")
        sess.add(proj); sess.commit(); sess.refresh(proj)
        # Membership row directly — the invite flow is covered by
        # test_project_members.py.
        sess.add(DBProjectMember(
            project_id=proj.id, user_info_id=editor.id, role="editor",
            invited_by=owner.id, created_at=time.time(),
        ))
        # One activity already imported by the OWNER.
        sess.add(DBActivity(
            id=111, user_info_id=owner.id, name="Owner ride", type="Ride",
            distance=4000.0, moving_time=1000, elapsed_time=1200,
            summary_polyline=polyline_lib.encode(_TRACK),
            start_date="2024-06-01T10:00:00Z",
            start_date_local="2024-06-01T12:00:00Z",
        ))
        sess.add(DBProjectItem(project_id=proj.id, position=0,
                               item_type="activity", activity_id=111))
        sess.commit()
        ids = {"owner": owner.id, "editor": editor.id, "project": proj.id}

    current = {"uid": ids["owner"]}
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(current["uid"])}
    app.include_router(projects_router)
    app.include_router(activities_router)
    app.include_router(strava_router)
    app.include_router(polarsteps_router)

    client = TestClient(app)

    def act_as(who: str):
        current["uid"] = ids[who]

    return client, engine, ids, act_as


# ── Import attribution ────────────────────────────────────────────────────────

def test_companion_import_attributes_rows_to_companion(env):
    client, engine, ids, act_as = env
    act_as("editor")
    r = client.post(f"/api/projects/Trip/activities?owner={ids['owner']}",
                    json={"activities": [_raw_act(222)]})
    assert r.status_code == 200, r.text
    assert r.json()["added"] == 1

    with Session(engine) as sess:
        assert sess.get(DBActivity, 222).user_info_id == ids["editor"]
        # The owner's pre-existing activity keeps its importer.
        assert sess.get(DBActivity, 111).user_info_id == ids["owner"]

    # The owner sees both activities in the project details.
    act_as("owner")
    detail = client.get("/api/projects/Trip").json()
    assert {a["id"] for a in detail["activities"]} == {111, 222}


def test_owner_import_still_attributes_to_owner(env):
    client, engine, ids, act_as = env
    act_as("owner")
    r = client.post("/api/projects/Trip/activities",
                    json={"activities": [_raw_act(333)]})
    assert r.status_code == 200, r.text
    with Session(engine) as sess:
        assert sess.get(DBActivity, 333).user_info_id == ids["owner"]


# ── Refresh-from-Strava importer guard ────────────────────────────────────────

def test_owner_cannot_refresh_companions_activity(env):
    client, engine, ids, act_as = env
    act_as("editor")
    client.post(f"/api/projects/Trip/activities?owner={ids['owner']}",
                json={"activities": [_raw_act(222)]})
    act_as("owner")
    r = client.post("/api/projects/Trip/activities/222/refresh")
    assert r.status_code == 403
    assert "user who imported" in r.json()["detail"]


def test_companion_cannot_refresh_owners_activity(env):
    client, _, ids, act_as = env
    act_as("editor")
    r = client.post(f"/api/projects/Trip/activities/111/refresh?owner={ids['owner']}")
    assert r.status_code == 403
    assert "user who imported" in r.json()["detail"]


def test_importer_passes_refresh_guard(env):
    client, _, ids, act_as = env
    # The importer gets past the guard: next failure is the (expected)
    # missing Strava connection, not a 403.
    act_as("owner")
    r = client.post("/api/projects/Trip/activities/111/refresh")
    assert r.status_code == 400
    assert "Strava not connected" in r.json()["detail"]


# ── Background enrichment uses the importer's client + owner's cache ─────────

def test_enrichment_uses_importer_client_and_owner_cache(env, monkeypatch):
    client, _, ids, act_as = env

    class _FakeClient:
        def get_activity_streams(self, _id):
            return {"latlng": {"data": [[48.0, 2.0], [48.1, 2.1]]}}

    factory_calls = []

    def _factory(user_info_id):
        factory_calls.append(user_info_id)
        return _FakeClient()

    busts, warms = [], []
    monkeypatch.setattr(activities_module, "_strava_client_for_user", _factory)
    monkeypatch.setattr(activities_module, "bust_geo_cache",
                        lambda uid, name: busts.append((uid, name)))
    monkeypatch.setattr(activities_module, "warm_geo_cache",
                        lambda uid, name: warms.append((uid, name)))

    # Companion imports → enrichment must be constructed for the COMPANION.
    act_as("editor")
    r = client.post(f"/api/projects/Trip/activities?owner={ids['owner']}",
                    json={"activities": [_raw_act(444)]})
    assert r.status_code == 200, r.text
    assert factory_calls == [ids["editor"]]

    # ...and the geo cache busted/warmed for the OWNER's project key.
    assert (ids["owner"], "Trip") in busts
    assert (ids["owner"], "Trip") in warms
    assert all(uid == ids["owner"] for uid, _ in busts + warms)

    # Owner imports next → enrichment for the OWNER. Never the wrong user.
    act_as("owner")
    r = client.post("/api/projects/Trip/activities",
                    json={"activities": [_raw_act(555)]})
    assert r.status_code == 200, r.text
    assert factory_calls == [ids["editor"], ids["owner"]]


# ── sync/check runs against the caller's own Strava account ──────────────────

def test_sync_check_companion_uses_own_cache(env):
    client, engine, ids, act_as = env
    with Session(engine) as sess:
        sess.add(StravaToken(
            user_info_id=ids["editor"], access_token="tok",
            refresh_token="ref", expires_at=time.time() + 3600,
        ))
        sess.add(DBStravaCache(
            user_info_id=ids["editor"], fetched_at=time.time(),
            activities_json=json.dumps([
                _raw_act(666, start="2024-06-03T10:00:00Z"),
                _raw_act(111, start="2024-06-01T10:00:00Z"),  # already in project
            ]),
        ))
        sess.commit()

    act_as("editor")
    r = client.get(f"/api/projects/Trip/sync/check?owner={ids['owner']}")
    assert r.status_code == 200, r.text
    body = r.json()
    # The companion's own new activity is offered; the in-project one is not.
    assert [a["id"] for a in body["strava"]] == [666]


def test_sync_check_owner_without_token_is_empty_not_500(env):
    client, _, ids, act_as = env
    act_as("owner")  # owner has no Strava token/cache
    r = client.get("/api/projects/Trip/sync/check")
    assert r.status_code == 200
    assert r.json() == {"strava": [], "polarsteps": []}


# ── Import-screen flags against a shared project ──────────────────────────────

def test_companion_strava_list_flags_shared_project(env):
    client, engine, ids, act_as = env
    with Session(engine) as sess:
        sess.add(StravaToken(
            user_info_id=ids["editor"], access_token="tok",
            refresh_token="ref", expires_at=time.time() + 3600,
        ))
        sess.add(DBStravaCache(
            user_info_id=ids["editor"], fetched_at=time.time(),
            activities_json=json.dumps([_raw_act(111), _raw_act(777)]),
        ))
        sess.commit()

    act_as("editor")
    r = client.get(f"/api/strava/activities?project=Trip&owner={ids['owner']}")
    assert r.status_code == 200, r.text
    flags = {a["id"]: a["in_project"] for a in r.json()["activities"]}
    assert flags == {111: True, 777: False}


def test_companion_polarsteps_steps_flag_shared_project(env, monkeypatch):
    client, engine, ids, act_as = env
    with Session(engine) as sess:
        sess.add(DBMemory(project_id=ids["project"], name="Step A",
                          date="2024-06-02", polarsteps_step_id=9))
        sess.commit()

    class _FakePSClient:
        def get_trip_steps(self, _trip_id):
            return [
                {"id": 9, "display_name": "Step A",
                 "start_time": "2024-06-02T10:00:00", "location": {}},
                {"id": 10, "display_name": "Step B",
                 "start_time": "2024-06-03T10:00:00", "location": {}},
            ]

    monkeypatch.setattr(polarsteps_module, "_require_client",
                        lambda uid: _FakePSClient())

    act_as("editor")
    r = client.get(
        f"/api/polarsteps/trips/1/steps?project_name=Trip&owner={ids['owner']}")
    assert r.status_code == 200, r.text
    flags = {s["id"]: s["already_imported"] for s in r.json()}
    assert flags == {9: True, 10: False}
