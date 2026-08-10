"""Route-level logging for Polarsteps failures (issue #205, Unit B).

``api/polarsteps.py`` used to turn a client failure straight into an
``HTTPException`` with no server-side trace at all — reconstructing what
happened required asking the affected user. These tests assert each of the
three ``except Exception as exc: raise HTTPException(..., 502, ...)`` sites
now logs before raising, in addition to keeping the existing response.
"""
from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import api.polarsteps as ps_api
import models.db as db_module
from api.deps import get_current_user
from api.polarsteps import router as polarsteps_router
from models.user import PolarstepsToken, UserInfo

_LOGGER = "api.polarsteps"


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
        u = UserInfo(display_name="A", email="a@e.com")
        sess.add(u)
        sess.commit()
        sess.refresh(u)
        sess.add(PolarstepsToken(
            user_info_id=u.id, remember_token="1|old",
            polarsteps_user_id=1, polarsteps_username="alice",
        ))
        sess.commit()
        uid = u.id

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(uid), "email": "a@e.com"}
    app.include_router(polarsteps_router)
    return TestClient(app), uid


def test_connect_logs_before_raising_502(env, monkeypatch, caplog):
    client, uid = env

    class _FakeClient:
        def __init__(self, token):
            pass

        def get_me(self):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(ps_api, "PolarstepsClient", _FakeClient)

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        resp = client.post("/api/polarsteps/connect", json={"remember_token": "1|x"})

    assert resp.status_code == 502
    assert "Could not reach Polarsteps" in resp.json()["detail"]
    assert "polarsteps connect failed" in caplog.text
    assert f"user_id={uid}" in caplog.text


def test_trips_logs_before_raising_502(env, monkeypatch, caplog):
    client, uid = env

    class _FakeClient:
        token_rotated = False
        current_token = "1|old"

        def __init__(self, token):
            pass

        def get_trips(self, user_id):
            raise RuntimeError("upstream broke")

    monkeypatch.setattr(ps_api, "PolarstepsClient", _FakeClient)

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        resp = client.get("/api/polarsteps/trips")

    assert resp.status_code == 502
    assert "upstream broke" in resp.json()["detail"]
    assert "polarsteps trips fetch failed" in caplog.text
    assert f"user_id={uid}" in caplog.text


def test_trip_steps_logs_before_raising_502(env, monkeypatch, caplog):
    client, uid = env

    class _FakeClient:
        token_rotated = False
        current_token = "1|old"

        def __init__(self, token):
            pass

        def get_trip_steps(self, trip_id):
            raise RuntimeError("upstream broke")

    monkeypatch.setattr(ps_api, "PolarstepsClient", _FakeClient)

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        resp = client.get("/api/polarsteps/trips/42/steps")

    assert resp.status_code == 502
    assert "polarsteps trip steps fetch failed" in caplog.text
    assert f"user_id={uid}" in caplog.text
    assert "trip_id=42" in caplog.text
