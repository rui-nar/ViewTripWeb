"""Regression tests for the activity-mutation lock_version audit fix (Fix 1):

edit_activity_track / split_activity / delete_local_activity /
reset_activity_track, and the background Strava-stream enrichment completion
path, must all advance ``DBProject.lock_version`` — the only signal the
native app's on-disk cache uses to know its cached heavy payloads are stale
(issue #173).
"""
from __future__ import annotations

import json

import polyline as polyline_lib
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import models.db as db_module
from api.deps import get_current_user
from api.activities import router as activities_router
from models.project_db import DBActivity, DBProject, DBProjectItem
from models.user import UserInfo

_TRACK = [(48.0, 2.0), (48.0, 2.01), (48.0, 2.02), (48.0, 2.03), (48.0, 2.04)]
_ELEV = [100.0, 120.0, 110.0, 140.0, 130.0]


def _seed(engine):
    with Session(engine) as sess:
        u = UserInfo(display_name="A", email="a@e.com")
        sess.add(u); sess.commit(); sess.refresh(u)
        proj = DBProject(user_info_id=u.id, name="My Trip")
        sess.add(proj); sess.commit(); sess.refresh(proj)

        poly = polyline_lib.encode(_TRACK)
        dist_km = [i * 1.0 for i in range(len(_TRACK))]
        act = DBActivity(
            id=111, user_info_id=u.id, name="Ride", type="Ride",
            distance=4000.0, moving_time=1000, elapsed_time=1200,
            total_elevation_gain=60.0, summary_polyline=poly,
            elevation_profile_json=json.dumps(
                {"distances_km": dist_km, "elevations_m": _ELEV}),
            start_latlng_json=json.dumps([48.0, 2.0]),
            end_latlng_json=json.dumps([48.0, 2.04]),
        )
        sess.add(act)
        sess.add(DBProjectItem(project_id=proj.id, position=0,
                               item_type="activity", activity_id=111))
        sess.commit()
        return u.id


@pytest.fixture
def env(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_module, "engine", engine)
    SQLModel.metadata.create_all(engine)
    uid = _seed(engine)

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(uid), "email": "a@e.com"}
    app.include_router(activities_router)
    return TestClient(app), engine


def _lock_version(engine, project_id=1):
    with Session(engine) as sess:
        return sess.get(DBProject, project_id).lock_version


def _points(n=3):
    return [{"lat": lat, "lng": lng, "elev": e}
            for (lat, lng), e in zip(_TRACK[:n], _ELEV[:n])]


class TestLockVersionBump:
    """Fix 1: every activity mutation must advance DBProject.lock_version."""

    def test_edit_track_bumps_lock_version(self, env):
        client, engine = env
        before = _lock_version(engine)
        resp = client.put("/api/projects/My Trip/activities/111/track",
                          json={"points": _points()})
        assert resp.status_code == 200, resp.text
        assert _lock_version(engine) == before + 1

    def test_split_bumps_lock_version(self, env):
        client, engine = env
        before = _lock_version(engine)
        resp = client.post("/api/projects/My Trip/activities/111/split",
                           json={"split_index": 2})
        assert resp.status_code == 200, resp.text
        assert _lock_version(engine) == before + 1

    def test_reset_bumps_lock_version(self, env):
        client, engine = env
        client.put("/api/projects/My Trip/activities/111/track", json={"points": _points()})
        before = _lock_version(engine)
        resp = client.post("/api/projects/My Trip/activities/111/reset")
        assert resp.status_code == 200, resp.text
        assert _lock_version(engine) == before + 1

    def test_delete_local_activity_bumps_lock_version(self, env):
        client, engine = env
        resp = client.post("/api/projects/My Trip/activities/111/split",
                           json={"split_index": 2})
        tail_id = next(a["id"] for a in resp.json()["activities"] if a["id"] < 0)
        before = _lock_version(engine)
        resp = client.delete(f"/api/projects/My Trip/activities/{tail_id}/local")
        assert resp.status_code == 204, resp.text
        assert _lock_version(engine) == before + 1

    def test_background_enrichment_bumps_lock_version(self, env, monkeypatch):
        """The Strava-stream enrichment completion path (issue #173) — once it
        successfully writes a polyline, the native cache must be told too."""
        import time as time_mod
        import api.activities as activities_mod
        from models.user import StravaToken

        client, engine = env
        with Session(engine) as sess:
            sess.add(StravaToken(
                user_info_id=1, access_token="tok", refresh_token="ref",
                expires_at=time_mod.time() + 3600,
            ))
            sess.commit()

        class _FakeClient:
            remaining_requests = 100
            def get_activity_streams(self, _aid):
                return {
                    "latlng": {"data": [[48.0, 2.0], [48.1, 2.1]]},
                    "altitude": {"data": [100.0, 110.0]},
                    "distance": {"data": [0.0, 1000.0]},
                }

        monkeypatch.setattr(
            activities_mod, "_strava_client_for_user", lambda _uid: _FakeClient())

        before = _lock_version(engine)
        activities_mod._enrich_activities_background([111], 1, 1, "My Trip")
        assert _lock_version(engine) == before + 1

    def test_background_enrichment_without_writes_does_not_bump(self, env, monkeypatch):
        """No polyline/elevation was written — nothing for the cache to notice,
        so the version must not move."""
        import api.activities as activities_mod

        client, engine = env
        monkeypatch.setattr(
            activities_mod, "_strava_client_for_user", lambda _uid: None)

        before = _lock_version(engine)
        activities_mod._enrich_activities_background([111], 1, 1, "My Trip")
        assert _lock_version(engine) == before
