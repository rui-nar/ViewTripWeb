"""Tests for the shared Activity-parse-drop logging fix (issue #205, Unit A).

`Activity.from_strava_api(raw)` used to be wrapped in a bare
`except Exception: pass` at five call sites (api/activities.py, api/strava.py
x2, api/projects.py, src/project/project_io.py — the latter is covered
separately in tests/test_project_io.py), silently discarding malformed
activities with zero trace. `parse_activities_or_log` centralises the parsing
and logs exactly one WARNING per call, naming the call site and the count
dropped vs. total. This file tests the helper directly, then exercises it
through three of the real call sites to confirm the wiring.
"""
from __future__ import annotations

import logging
import time

import polyline as polyline_lib
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import api.strava as strava_module
import models.db as db_module
from api.activities import router as activities_router
from api.deps import get_current_user
from api.projects import router as projects_router
from api.strava import router as strava_router
from models.project_db import DBProject
from models.user import StravaToken, UserInfo
from src.models.activity import parse_activities_or_log

_TRACK = [(48.0, 2.0), (48.0, 2.01)]


def _valid_raw(act_id: int, start: str = "2024-06-02T10:00:00Z") -> dict:
    return {
        "id": act_id,
        "name": "Ride",
        "type": "Ride",
        "distance": 1000.0,
        "moving_time": 100,
        "elapsed_time": 120,
        "total_elevation_gain": 10.0,
        "start_date": start,
        "start_date_local": start,
        "map": {"summary_polyline": polyline_lib.encode(_TRACK)},
    }


_MALFORMED_RAW = {"id": 999, "start_date": "not-a-date"}


# ---------------------------------------------------------------------------
# The helper, directly
# ---------------------------------------------------------------------------

def test_parse_activities_or_log_skips_malformed_and_logs_once(caplog):
    raw_list = [_valid_raw(1), _MALFORMED_RAW, _valid_raw(2), _MALFORMED_RAW]

    with caplog.at_level(logging.WARNING, logger="src.models.activity"):
        result = parse_activities_or_log(raw_list, "my_source")

    assert [a.id for a in result] == [1, 2]
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "my_source" in warnings[0].message
    assert "2/4" in warnings[0].message


def test_parse_activities_or_log_all_valid_logs_nothing(caplog):
    raw_list = [_valid_raw(1), _valid_raw(2)]

    with caplog.at_level(logging.WARNING, logger="src.models.activity"):
        result = parse_activities_or_log(raw_list, "my_source")

    assert len(result) == 2
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


def test_parse_activities_or_log_all_malformed_returns_empty(caplog):
    raw_list = [_MALFORMED_RAW, _MALFORMED_RAW]

    with caplog.at_level(logging.WARNING, logger="src.models.activity"):
        result = parse_activities_or_log(raw_list, "my_source")

    assert result == []
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "2/2" in warnings[0].message


@pytest.mark.parametrize("source", [
    "activities_add", "strava_browse", "strava_sync",
    "projects_unimported", "project_io_load",
])
def test_parse_activities_or_log_names_the_call_site(source, caplog):
    with caplog.at_level(logging.WARNING, logger="src.models.activity"):
        parse_activities_or_log([_MALFORMED_RAW], source)

    assert source in caplog.text


# ---------------------------------------------------------------------------
# Through the real call sites
# ---------------------------------------------------------------------------

@pytest.fixture
def env(monkeypatch):
    """Single owner + one empty project, with activities/projects/strava routers."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_module, "engine", engine)
    SQLModel.metadata.create_all(engine)

    with Session(engine) as sess:
        owner = UserInfo(display_name="Owner", email="owner@e.com")
        sess.add(owner)
        sess.commit()
        sess.refresh(owner)
        proj = DBProject(user_info_id=owner.id, name="Trip")
        sess.add(proj)
        sess.commit()
        owner_id = owner.id

    # Deliberately no StravaToken row here: add_activities doesn't need one,
    # and a token row would make its background enrichment task try to build
    # a real StravaAPI (which needs strava.client_id/secret, unset in tests).
    # Tests that need a token add one directly via `engine`.
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(owner_id)}
    app.include_router(activities_router)
    app.include_router(projects_router)
    app.include_router(strava_router)

    return TestClient(app), engine, owner_id


def test_add_activities_drops_malformed_and_logs(env, caplog):
    """api/activities.py:add_activities — source 'activities_add'."""
    client, _engine, _owner_id = env
    with caplog.at_level(logging.WARNING, logger="src.models.activity"):
        resp = client.post(
            "/api/projects/Trip/activities",
            json={"activities": [_valid_raw(1), _MALFORMED_RAW, _valid_raw(2)]},
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["added"] == 2
    warnings = [r for r in caplog.records
                if r.levelno == logging.WARNING and r.name == "src.models.activity"]
    assert len(warnings) == 1
    assert "activities_add" in warnings[0].message
    assert "1/3" in warnings[0].message


def _add_strava_token(engine, owner_id: int) -> None:
    with Session(engine) as sess:
        sess.add(StravaToken(
            user_info_id=owner_id, access_token="tok", refresh_token="ref",
            expires_at=time.time() + 3600,
        ))
        sess.commit()


def test_strava_sync_drops_malformed_and_logs(env, caplog, monkeypatch):
    """api/strava.py:strava_sync — source 'strava_sync'."""
    client, engine, owner_id = env
    _add_strava_token(engine, owner_id)
    raw_list = [_valid_raw(10), _MALFORMED_RAW, _valid_raw(11)]

    class _FakeClient:
        def __init__(self):
            self.token_data = {"access_token": "tok", "refresh_token": "ref",
                                "expires_at": time.time() + 3600}

    monkeypatch.setattr(strava_module, "_strava_client_for_token", lambda *_a, **_k: _FakeClient())
    monkeypatch.setattr(strava_module, "_fetch_all_strava", lambda *_a, **_k: raw_list)

    with caplog.at_level(logging.WARNING, logger="src.models.activity"):
        resp = client.post("/api/projects/Trip/strava/sync")

    assert resp.status_code == 200, resp.text
    assert resp.json()["added"] == 2
    warnings = [r for r in caplog.records
                if r.levelno == logging.WARNING and r.name == "src.models.activity"]
    assert len(warnings) == 1
    assert "strava_sync" in warnings[0].message
    assert "1/3" in warnings[0].message


def test_sync_check_drops_malformed_and_logs(env, caplog, monkeypatch):
    """api/projects.py:sync_check ("unimported activities") — source 'projects_unimported'."""
    client, engine, owner_id = env
    _add_strava_token(engine, owner_id)
    raw_list = [_valid_raw(20), _MALFORMED_RAW, _valid_raw(21)]

    monkeypatch.setattr(
        strava_module, "_load_cache",
        lambda uid: {"fetched_at": time.time(), "activities": raw_list},
    )

    with caplog.at_level(logging.WARNING, logger="src.models.activity"):
        resp = client.get("/api/projects/Trip/sync/check")

    assert resp.status_code == 200, resp.text
    assert len(resp.json()["strava"]) == 2
    warnings = [r for r in caplog.records
                if r.levelno == logging.WARNING and r.name == "src.models.activity"]
    assert len(warnings) == 1
    assert "projects_unimported" in warnings[0].message
    assert "1/3" in warnings[0].message
