"""API + repo integration tests for activity track editing (issue #31).

Covers:
  - PUT /track trims a track: distance drops, is_edited set, original snapshot taken.
  - POST /reset restores the original geometry and clears is_edited.
  - Enrichment / refresh skip is_edited activities (sync-skip regression).
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
from src.project.project_repo import ProjectRepo

# A simple 5-point track (~roughly a straight eastward line) with elevations.
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
            elevation_profile_json=json.dumps({"distances_km": dist_km, "elevations_m": _ELEV}),
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


def _find_act(body, aid=111):
    return next(a for a in body["activities"] if a["id"] == aid)


def test_get_activity_track_returns_editor_payload(env):
    client, _ = env
    resp = client.get("/api/projects/My Trip/activities/111/track")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == 111
    assert body["is_edited"] is False
    # Geometry the editor needs is present.
    assert body["map"]["summary_polyline"] == polyline_lib.encode(_TRACK)
    # elevation_profile is the [[dist_km, elev_m], ...] pair form, not the
    # {distances_km, elevations_m} storage form.
    ep = body["elevation_profile"]
    assert isinstance(ep, list) and ep[0] == [0.0, 100.0]


def test_get_activity_track_unknown_activity_is_404(env):
    client, _ = env
    resp = client.get("/api/projects/My Trip/activities/999/track")
    assert resp.status_code == 404


def test_get_activity_track_unknown_project_is_404(env):
    client, _ = env
    resp = client.get("/api/projects/No Such Trip/activities/111/track")
    assert resp.status_code == 404


def test_trim_reduces_distance_and_sets_edited(env):
    client, engine = env
    # Trim to the first three points.
    points = [{"lat": lat, "lng": lng, "elev": e}
              for (lat, lng), e in zip(_TRACK[:3], _ELEV[:3])]
    resp = client.put("/api/projects/My Trip/activities/111/track", json={"points": points})
    assert resp.status_code == 200, resp.text
    act = _find_act(resp.json())
    assert act["is_edited"] is True
    assert act["distance"] < 4000.0
    # Times apportioned down to retained distance.
    assert act["moving_time"] < 1000

    with Session(engine) as sess:
        row = sess.get(DBActivity, 111)
        assert row.is_edited is True
        assert row.original_polyline == polyline_lib.encode(_TRACK)   # snapshot taken
        assert row.summary_polyline != row.original_polyline          # geometry changed


def test_track_edit_requires_two_points(env):
    client, _ = env
    resp = client.put("/api/projects/My Trip/activities/111/track",
                      json={"points": [{"lat": 48.0, "lng": 2.0}]})
    assert resp.status_code == 422


def test_reset_restores_original(env):
    client, engine = env
    points = [{"lat": lat, "lng": lng, "elev": e}
              for (lat, lng), e in zip(_TRACK[:2], _ELEV[:2])]
    client.put("/api/projects/My Trip/activities/111/track", json={"points": points})

    resp = client.post("/api/projects/My Trip/activities/111/reset")
    assert resp.status_code == 200, resp.text
    act = _find_act(resp.json())
    assert act["is_edited"] is False

    from src.models.track_edit import align_points, recompute_track_metrics
    full_geom_dist = recompute_track_metrics(
        align_points(polyline_lib.encode(_TRACK), None)).distance
    with Session(engine) as sess:
        row = sess.get(DBActivity, 111)
        assert row.is_edited is False
        assert row.original_polyline is None
        assert row.summary_polyline == polyline_lib.encode(_TRACK)
        # Distance restored to the pre-edit geometry length (haversine of the
        # full track); the original Strava scalar distance is not snapshotted.
        assert row.distance == pytest.approx(full_geom_dist, rel=1e-6)


def test_reset_without_edit_is_conflict(env):
    client, _ = env
    resp = client.post("/api/projects/My Trip/activities/111/reset")
    assert resp.status_code == 409


def test_reset_recovers_original_times(env):
    client, engine = env
    points = [{"lat": lat, "lng": lng, "elev": e}
              for (lat, lng), e in zip(_TRACK[:3], _ELEV[:3])]
    client.put("/api/projects/My Trip/activities/111/track", json={"points": points})
    client.post("/api/projects/My Trip/activities/111/reset")
    with Session(engine) as sess:
        row = sess.get(DBActivity, 111)
        # Times scale down on edit then back up on reset — recovered within rounding.
        assert row.moving_time == pytest.approx(1000, abs=2)
        assert row.elapsed_time == pytest.approx(1200, abs=2)


class TestSyncSkip:
    def test_activity_is_edited_flag(self, env):
        client, engine = env
        repo = ProjectRepo()
        assert repo.activity_is_edited(111) is False
        points = [{"lat": lat, "lng": lng, "elev": e}
                  for (lat, lng), e in zip(_TRACK[:3], _ELEV[:3])]
        client.put("/api/projects/My Trip/activities/111/track", json={"points": points})
        assert repo.activity_is_edited(111) is True

    def test_enrich_activities_skips_edited(self, env):
        from api.activities import _enrich_activities
        from src.models.activity import Activity
        from datetime import datetime

        class _FakeClient:
            remaining_requests = 1000
            def get_activity_streams(self, _id):
                raise AssertionError("must not fetch streams for an edited activity")

        act = Activity(
            id=111, name="x", type="Ride", distance=0.0, moving_time=0,
            elapsed_time=0, total_elevation_gain=0.0,
            start_date=datetime(2024, 1, 1), start_date_local=datetime(2024, 1, 1),
            timezone="UTC", achievement_count=0, kudos_count=0, comment_count=0,
            athlete_count=0, photo_count=0, trainer=False, commute=False,
            manual=False, private=False, flagged=False, average_speed=0.0,
            max_speed=0.0, has_heartrate=False, pr_count=0, total_photo_count=0,
            has_kudoed=False, is_edited=True,
        )
        pending = _enrich_activities([act], _FakeClient())
        assert pending == []  # skipped, not queued

    def test_refresh_edited_activity_is_conflict(self, env):
        client, _ = env
        points = [{"lat": lat, "lng": lng, "elev": e}
                  for (lat, lng), e in zip(_TRACK[:3], _ELEV[:3])]
        client.put("/api/projects/My Trip/activities/111/track", json={"points": points})
        resp = client.post("/api/projects/My Trip/activities/111/refresh")
        assert resp.status_code == 409
