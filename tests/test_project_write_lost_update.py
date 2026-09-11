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
from uuid import uuid4

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


@pytest.fixture(scope="module")
def _engine(tmp_path_factory):
    """ONE engine for the whole module, deliberately.

    A file-backed database, not the usual in-memory StaticPool one: this module
    is about two writers racing, and StaticPool hands every Session the same
    connection, so the "concurrent" write would share the caller's transaction
    and the isolation under test would be fake.

    Module-scoped because something under api/ binds a session factory on first
    use; with a fresh engine per test, the second test's writes landed in the
    first test's database and the race quietly stopped happening. One engine
    for the module keeps every binding correct; the tables are recreated per
    test below, so the tests are still independent.
    """
    path = tmp_path_factory.mktemp("db") / "test.db"
    return create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})


@pytest.fixture
def env(monkeypatch, _engine):
    engine = _engine
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "get_session", lambda: Session(engine))
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)

    with Session(engine) as sess:
        owner = UserInfo(display_name="Owner", email="owner@e.com")
        sess.add(owner); sess.commit(); sess.refresh(owner)
        proj = DBProject(user_info_id=owner.id, name="Trip",
                         day_meta_json=json.dumps({"2024-06-01": {"note": "before"}}))
        sess.add(proj); sess.commit(); sess.refresh(proj)
        ids = {"owner": owner.id, "project": proj.id, "name": proj.name}

    from api.activities import router as activities_router
    from api.projects import router as projects_router
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(ids["owner"])}
    app.include_router(activities_router)
    app.include_router(projects_router)
    return TestClient(app), engine, ids


def _concurrent_day_meta_write(client, name: str, payload: dict):
    """Another request's PUT /day-meta committing right now — the REAL
    endpoint, not a stand-in.

    An earlier version of this helper wrote the row by hand and bumped
    lock_version itself. That faked the one thing the endpoint did not do, so
    the tests certified a compare-and-swap that could never fire in
    production. Drive the real route or prove nothing.
    """
    r = client.put(f"/api/projects/{name}/day-meta", json={"day_meta": payload})
    assert r.status_code == 204, r.text


def _stored_day_meta(engine, name):
    with Session(engine) as sess:
        row = sess.exec(select(DBProject).where(DBProject.name == name)).one()
        return json.loads(row.day_meta_json) if row.day_meta_json else {}


def test_gpx_import_does_not_revert_a_day_meta_write_made_while_it_ran(env, monkeypatch):
    client, engine, ids = env
    import api.activities as activities_mod
    monkeypatch.setattr(activities_mod, "_schedule_gpx_enrichment", lambda *a, **k: None,
                        raising=False)

    # Fire the concurrent write from the quota check: it runs exactly once per
    # save attempt, inside the mutate callback, i.e. squarely between the load
    # and the save. (Project.add_activities is NOT a safe hook — the loader
    # calls it too, which would land the write before the window opens.)
    fired = {"done": False}
    real_quota = activities_mod.ensure_trip_days_quota

    def _quota_then_race(*a, **k):
        result = real_quota(*a, **k)
        if not fired["done"]:
            fired["done"] = True
            _concurrent_day_meta_write(client, ids["name"], {"2024-06-02": {"note": "written during"}})
        return result

    monkeypatch.setattr(activities_mod, "ensure_trip_days_quota", _quota_then_race)

    r = client.post(
        f"/api/projects/{ids['name']}/activities/import-gpx",
        files={"file": ("t.gpx", _gpx_bytes(), "application/gpx+xml")},
        data={"date": "2024-06-01", "start_time": "09:00", "end_time": "10:00",
              "activity_type": "Hike"},
    )
    assert r.status_code == 200, r.text
    assert fired["done"], "the concurrent write never ran — test is not exercising the window"

    # The concurrent write must survive. A blind save rewrites day_meta_json
    # from the snapshot loaded before it, restoring {"2024-06-01": ...}.
    assert "2024-06-02" in _stored_day_meta(engine, ids["name"])


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
        _concurrent_day_meta_write(client, ids["name"], {"2024-06-02": {"note": "written during"}})
        return [_raw_strava_activity(1, "2024-06-03T10:00:00Z")]

    monkeypatch.setattr(strava_mod, "_strava_client_for_token",
                        lambda token_row: _FakeStravaClient())
    monkeypatch.setattr(strava_mod, "_fetch_all_strava", _fetch)

    r = client.post(f"/api/projects/{ids['name']}/strava/sync")
    assert r.status_code == 200, r.text
    assert fired["done"], "the fetch never ran — test is not exercising the window"

    assert "2024-06-02" in _stored_day_meta(engine, ids["name"])


# ── The mechanism, not just the outcome ──────────────────────────────────────

def test_the_conflict_is_actually_detected_and_the_mutation_re_runs(env, monkeypatch):
    """The outcome tests above would also pass if the save simply happened to
    read fresh state. This pins the mechanism: the compare-and-swap must see
    the concurrent write, and the mutation must be re-applied to a freshly
    loaded project rather than to the snapshot the CAS just rejected."""
    import src.project.repo_core as repo_core
    client, engine, ids = env
    import api.activities as activities_mod
    monkeypatch.setattr(activities_mod, "_schedule_gpx_enrichment",
                        lambda *a, **k: None, raising=False)

    calls = {"mutate": 0}
    conflicts = {"n": 0}
    real_quota = activities_mod.ensure_trip_days_quota

    def _quota_then_race(*a, **k):
        calls["mutate"] += 1
        result = real_quota(*a, **k)
        if calls["mutate"] == 1:
            _concurrent_day_meta_write(client, ids["name"], {"2024-06-02": {"note": "during"}})
        return result

    monkeypatch.setattr(activities_mod, "ensure_trip_days_quota", _quota_then_race)

    real_save = repo_core.ProjectCoreMixin.save_project

    def _counting_save(self, sess, uid, project, **kw):
        try:
            return real_save(self, sess, uid, project, **kw)
        except repo_core.StaleWriteError:
            conflicts["n"] += 1
            raise

    monkeypatch.setattr(repo_core.ProjectCoreMixin, "save_project", _counting_save)

    r = client.post(
        f"/api/projects/{ids['name']}/activities/import-gpx",
        files={"file": ("t.gpx", _gpx_bytes(), "application/gpx+xml")},
        data={"date": "2024-06-01", "start_time": "09:00", "end_time": "10:00",
              "activity_type": "Hike"},
    )
    assert r.status_code == 200, r.text
    assert conflicts["n"] >= 1, "the CAS never detected the concurrent write"
    assert calls["mutate"] >= 2, "the mutation did not re-run on fresh state"
    assert "2024-06-02" in _stored_day_meta(engine, ids["name"])


def test_a_quota_refusal_surfaces_as_402_instead_of_being_retried(env, monkeypatch):
    """ensure_trip_days_quota now runs inside the retry callback. Its 402 must
    escape the loop on the first attempt — retrying it would burn all five
    attempts and surface the wrong error (a 409) for a billing limit."""
    from fastapi import HTTPException
    client, engine, ids = env
    import api.activities as activities_mod
    monkeypatch.setattr(activities_mod, "_schedule_gpx_enrichment",
                        lambda *a, **k: None, raising=False)

    calls = {"n": 0}

    def _refuse(*a, **k):
        calls["n"] += 1
        raise HTTPException(status_code=402, detail={"resource": "trip_days"})

    monkeypatch.setattr(activities_mod, "ensure_trip_days_quota", _refuse)

    r = client.post(
        f"/api/projects/{ids['name']}/activities/import-gpx",
        files={"file": ("t.gpx", _gpx_bytes(), "application/gpx+xml")},
        data={"date": "2024-06-01", "start_time": "09:00", "end_time": "10:00",
              "activity_type": "Hike"},
    )
    assert r.status_code == 402, r.text
    assert calls["n"] == 1, "the quota refusal was retried instead of surfacing"
