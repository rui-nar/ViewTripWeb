"""A load-mutate-save that blind-overwrites loses a concurrent writer's work.

`save_project` with the default `check_version=False` rewrites *every* field of
the project row from the in-memory snapshot the caller loaded — day-meta,
sleeping options, counters, track style, trip dates. So any write that commits
between that load and the save is silently reverted to its pre-request value,
with no error on either side.

Two importers still did this: the GPX import and the Strava sync. The Strava
one is the worst window in the app, since a network round trip to Strava sits
inside it. `save_project_with_retry` reloads and re-applies the mutation under
the optimistic lock instead — the policy every other structural mutation
already used (issues #172/#173).

These tests drive the real endpoints and land a real concurrent write inside
the window, by hooking the repo call the endpoint makes mid-request.
"""
from __future__ import annotations

import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import models.db as db_module
from api.deps import get_current_user
from models.project_db import DBProject
from models.user import UserInfo


def _gpx_bytes():
    pts = [(48.0, 2.0, 100.0), (48.001, 2.001, 110.0), (48.002, 2.002, 105.0)]
    body = "".join(
        f'<trkpt lat="{la}" lon="{lo}"><ele>{el}</ele></trkpt>' for la, lo, el in pts
    )
    return (
        '<?xml version="1.0"?>'
        '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><trkseg>{body}</trkseg></trk></gpx>"
    ).encode("utf-8")


@pytest.fixture
def env(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "get_session", lambda: Session(engine))
    SQLModel.metadata.create_all(engine)

    with Session(engine) as sess:
        owner = UserInfo(display_name="Owner", email="owner@e.com")
        sess.add(owner); sess.commit(); sess.refresh(owner)
        proj = DBProject(user_info_id=owner.id, name="Trip",
                         day_meta_json=json.dumps({"2024-06-01": {"note": "before"}}))
        sess.add(proj); sess.commit(); sess.refresh(proj)
        ids = {"owner": owner.id, "project": proj.id}

    from api.activities import router as activities_router
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(ids["owner"])}
    app.include_router(activities_router)
    return TestClient(app), engine, ids


def _concurrent_day_meta_write(engine, payload: dict):
    """Stand in for another request's PUT /day-meta committing right now."""
    with Session(engine) as sess:
        row = sess.exec(select(DBProject).where(DBProject.name == "Trip")).one()
        row.day_meta_json = json.dumps(payload)
        row.lock_version = (row.lock_version or 0) + 1
        sess.add(row); sess.commit()


def _stored_day_meta(engine):
    with Session(engine) as sess:
        row = sess.exec(select(DBProject).where(DBProject.name == "Trip")).one()
        return json.loads(row.day_meta_json) if row.day_meta_json else {}


def test_gpx_import_does_not_revert_a_day_meta_write_made_while_it_ran(env, monkeypatch):
    client, engine, ids = env
    import api.activities as activities_mod
    monkeypatch.setattr(activities_mod, "_schedule_gpx_enrichment", lambda *a, **k: None,
                        raising=False)

    # The concurrent write lands after the endpoint has loaded the project,
    # which is exactly the window a blind overwrite cannot see.
    real_add = None
    fired = {"done": False}

    from src.models.project import Project
    real_add = Project.add_activities

    def _add_then_race(self, activities):
        if not fired["done"]:
            fired["done"] = True
            _concurrent_day_meta_write(engine, {"2024-06-02": {"note": "written during"}})
        return real_add(self, activities)

    monkeypatch.setattr(Project, "add_activities", _add_then_race)

    r = client.post(
        "/api/projects/Trip/activities/import-gpx",
        files={"file": ("t.gpx", _gpx_bytes(), "application/gpx+xml")},
        data={"date": "2024-06-01", "start_time": "09:00", "end_time": "10:00",
              "activity_type": "Hike"},
    )
    assert r.status_code == 200, r.text
    assert fired["done"], "the concurrent write never ran — test is not exercising the window"

    # The concurrent write must survive. A blind save rewrites day_meta_json
    # from the snapshot loaded before it, restoring {"2024-06-01": ...}.
    assert "2024-06-02" in _stored_day_meta(engine)


class _FakeStravaClient:
    """Stands in for StravaAPI; token_data matches the seeded token so
    _save_refreshed_token is a no-op."""
    token_data = {"access_token": "tok", "refresh_token": "ref", "expires_at": 9e9}


def _raw_strava_activity(act_id, start):
    return {
        "id": act_id, "name": "Ride", "type": "Ride",
        "distance": 1000.0, "moving_time": 100, "elapsed_time": 120,
        "total_elevation_gain": 0.0,
        "start_date": start, "start_date_local": start,
    }


def test_strava_sync_does_not_revert_a_day_meta_write_made_during_the_fetch(
        env, monkeypatch):
    """The Strava fetch is a network round trip sitting inside the load-save
    window — the widest one in the app. A write committing there was reverted
    to its pre-request value."""
    client, engine, ids = env
    from models.user import StravaToken
    import api.strava as strava_mod

    with Session(engine) as sess:
        sess.add(StravaToken(user_info_id=ids["owner"], access_token="tok",
                             refresh_token="ref", expires_at=9e9))
        sess.commit()

    client.app.include_router(strava_mod.router)

    fired = {"done": False}

    def _fetch(_client, after=None, before=None):
        # Land the concurrent write exactly where the real fetch blocks.
        fired["done"] = True
        _concurrent_day_meta_write(engine, {"2024-06-02": {"note": "written during"}})
        return [_raw_strava_activity(1, "2024-06-03T10:00:00Z")]

    monkeypatch.setattr(strava_mod, "_strava_client_for_token",
                        lambda token_row: _FakeStravaClient())
    monkeypatch.setattr(strava_mod, "_fetch_all_strava", _fetch)

    r = client.post("/api/projects/Trip/strava/sync")
    assert r.status_code == 200, r.text
    assert fired["done"], "the fetch never ran — test is not exercising the window"

    assert "2024-06-02" in _stored_day_meta(engine)
