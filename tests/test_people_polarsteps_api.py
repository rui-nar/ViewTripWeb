"""Tests for viewing a person's Polarsteps trip (issue #40 follow-up)."""
from __future__ import annotations

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import api.people as people_module
import models.db as db_module
from api.deps import get_current_user
from api.people import router as people_router
from models.project_db import DBPerson, DBProject
from models.user import UserInfo


def _seed(engine):
    with Session(engine) as sess:
        u = UserInfo(display_name="A", email="a@e.com")
        sess.add(u); sess.commit(); sess.refresh(u)
        proj = DBProject(user_info_id=u.id, name="Trip")
        sess.add(proj); sess.commit(); sess.refresh(proj)
        with_handle = DBPerson(project_id=proj.id, name="Alice",
                               polarsteps="polarsteps.com/alice")
        no_handle = DBPerson(project_id=proj.id, name="Bob")
        sess.add(with_handle); sess.add(no_handle)
        sess.commit(); sess.refresh(with_handle); sess.refresh(no_handle)
        return u.id, with_handle.id, no_handle.id


class _FakeClient:
    token_rotated = False

    def get_user_by_username(self, username):
        if username == "private":
            resp = requests.Response()
            resp.status_code = 404
            raise requests.HTTPError(response=resp)
        return {
            "id": 99,
            "trips": [
                {"id": 5, "name": "Asia", "display_name": "Asia 2024",
                 "start_date": 1700000000, "end_date": 1701000000,
                 "steps": [{}, {}]},
            ],
        }

    def get_trip_steps(self, trip_id):
        return [
            {"id": 10, "display_name": "Bangkok", "type": 1,
             "start_time": 1700000000,
             "location": {"lat": 13.7, "lon": 100.5, "name": "Bangkok"}},
        ]


@pytest.fixture
def env(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_module, "engine", engine)
    SQLModel.metadata.create_all(engine)
    uid, with_id, no_id = _seed(engine)

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(uid), "email": "a@e.com"}
    app.include_router(people_router)
    return TestClient(app), monkeypatch, with_id, no_id


def test_person_without_handle_is_400(env):
    client, _, _, no_id = env
    r = client.get(f"/api/people/{no_id}/polarsteps/trips")
    assert r.status_code == 400
    assert "no Polarsteps" in r.json()["detail"]


def test_not_connected_is_400(env):
    client, _, with_id, _ = env
    # No PolarstepsToken seeded, no patch → _require_client raises "not connected".
    r = client.get(f"/api/people/{with_id}/polarsteps/trips")
    assert r.status_code == 400
    assert "not connected" in r.json()["detail"].lower()


def test_lists_trips(env):
    client, monkeypatch, with_id, _ = env
    monkeypatch.setattr(people_module, "_require_client", lambda uid: _FakeClient())
    r = client.get(f"/api/people/{with_id}/polarsteps/trips")
    assert r.status_code == 200, r.text
    trips = r.json()
    assert len(trips) == 1
    assert trips[0]["id"] == 5
    assert trips[0]["name"] == "Asia 2024"
    assert trips[0]["steps_count"] == 2


def test_lists_trip_steps(env):
    client, monkeypatch, with_id, _ = env
    monkeypatch.setattr(people_module, "_require_client", lambda uid: _FakeClient())
    r = client.get(f"/api/people/{with_id}/polarsteps/trips/5/steps")
    assert r.status_code == 200, r.text
    steps = r.json()
    assert len(steps) == 1
    assert steps[0]["lat"] == 13.7 and steps[0]["lon"] == 100.5
    assert steps[0]["location_name"] == "Bangkok"


def test_private_profile_is_404(env):
    client, monkeypatch, with_id, _ = env
    # Person handle resolves to "alice" normally; force the private path.
    with Session(db_module.engine) as sess:
        p = sess.get(DBPerson, with_id)
        p.polarsteps = "private"
        sess.add(p); sess.commit()
    monkeypatch.setattr(people_module, "_require_client", lambda uid: _FakeClient())
    r = client.get(f"/api/people/{with_id}/polarsteps/trips")
    assert r.status_code == 404


def test_handle_parsing():
    from api.people import _parse_ps_username
    assert _parse_ps_username("alice") == "alice"
    assert _parse_ps_username("@alice") == "alice"
    assert _parse_ps_username("https://www.polarsteps.com/alice/") == "alice"
    assert _parse_ps_username("polarsteps.com/alice/1234-trip") == "alice"
    assert _parse_ps_username("  ") is None
    assert _parse_ps_username(None) is None
