"""``/api/geo/project/low-res`` must load the project without heavy columns.

The payload is straight lines between each activity's start/end point plus
segment geometry — ``_compute_low_res_geo`` never reads ``summary_polyline`` or
``elevation_profile_json``. Loading them anyway meant every request paid for
those columns' SQLite overflow pages, which is why this endpoint took 13 s on a
cold cache in issue #178 — the client's whole budget for the pair of requests
its activity panel blocks on.
"""
from __future__ import annotations

import json

import polyline as polyline_lib
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import api.geo as geo_mod
import models.db as db_module
from api.deps import get_current_user
from api.geo import router as geo_router
from models.project_db import DBActivity, DBProject, DBProjectItem
from models.user import UserInfo

_LINE = [(60.0, 24.0), (60.5, 24.5), (61.0, 25.0)]


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
        user = UserInfo(display_name="Alice", email="a@b.c")
        sess.add(user)
        sess.commit()
        sess.refresh(user)
        uid = user.id
        project = DBProject(user_info_id=uid, name="Trip")
        sess.add(project)
        sess.commit()
        sess.refresh(project)

        sess.add(DBActivity(
            id=111, user_info_id=uid, name="Ride", type="Ride",
            start_date="2026-06-01T00:00:00Z",
            summary_polyline=polyline_lib.encode(_LINE),
            elevation_profile_json=json.dumps(
                {"distances_km": [0.0, 1.0], "elevations_m": [10.0, 20.0]}),
            start_latlng_json=json.dumps(list(_LINE[0])),
            end_latlng_json=json.dumps(list(_LINE[-1])),
        ))
        sess.add(DBProjectItem(project_id=project.id, position=0,
                               item_type="activity", activity_id=111))
        sess.commit()

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(uid), "email": "a@b.c"}
    app.include_router(geo_router)
    yield TestClient(app), uid


def test_the_project_is_loaded_without_the_heavy_columns(env, monkeypatch):
    client, _uid = env
    seen: list[dict] = []
    orig = geo_mod._repo.get_project

    def _spy(*args, **kwargs):
        seen.append(kwargs)
        return orig(*args, **kwargs)

    monkeypatch.setattr(geo_mod._repo, "get_project", _spy)

    assert client.get("/api/geo/project/low-res?name=Trip").status_code == 200
    assert seen, "the endpoint no longer loads the project through _repo.get_project"
    assert all(kw.get("include_heavy") is False for kw in seen), (
        f"low-res still reads the deferred heavy columns: {seen}")


def test_the_payload_is_unchanged_by_the_lighter_load(env):
    """Straight lines come from start/end latlng — never from the polyline."""
    client, _uid = env
    feats = client.get("/api/geo/project/low-res?name=Trip").json()["features"]
    acts = [f for f in feats if f["properties"]["type"] == "activity"]
    assert len(acts) == 1
    assert acts[0]["geometry"]["coordinates"] == [
        [_LINE[0][1], _LINE[0][0]],
        [_LINE[-1][1], _LINE[-1][0]],
    ]
