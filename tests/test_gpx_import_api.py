"""API tests for GPX activity import (POST /{name}/activities/import-gpx)."""
from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import models.db as db_module
from api.deps import get_current_user
from api.activities import router as activities_router
from models.project_db import DBActivity, DBProject, DBProjectMember
from models.user import UserInfo


def _gpx_xml(tracks):
    """Build a GPX 1.1 XML string. `tracks` is a list of segment-lists, where
    each segment is a list of (lat, lon, ele) tuples. Mirrors the helper in
    tests/test_gpx_import.py."""
    parts = ['<?xml version="1.0"?>',
             '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">']
    for segments in tracks:
        parts.append("<trk>")
        for segment in segments:
            parts.append("<trkseg>")
            for lat, lon, ele in segment:
                parts.append(f'<trkpt lat="{lat}" lon="{lon}"><ele>{ele}</ele></trkpt>')
            parts.append("</trkseg>")
        parts.append("</trk>")
    parts.append("</gpx>")
    return "\n".join(parts)


_TRACK = [(48.0, 2.0, 100.0), (48.001, 2.001, 110.0), (48.002, 2.002, 105.0)]
_SINGLE_TRACK_GPX = _gpx_xml([[_TRACK]]).encode("utf-8")
_MULTI_TRACK_GPX = _gpx_xml([[_TRACK], [_TRACK]]).encode("utf-8")


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
        viewer = UserInfo(display_name="Viewer", email="viewer@e.com")
        sess.add(owner); sess.add(viewer); sess.commit()
        sess.refresh(owner); sess.refresh(viewer)
        proj = DBProject(user_info_id=owner.id, name="Trip")
        sess.add(proj); sess.commit(); sess.refresh(proj)
        sess.add(DBProjectMember(
            project_id=proj.id, user_info_id=viewer.id, role="viewer",
            invited_by=owner.id, created_at=time.time(),
        ))
        sess.commit()
        ids = {"owner": owner.id, "viewer": viewer.id}

    current = {"uid": ids["owner"]}
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(current["uid"])}
    app.include_router(activities_router)
    client = TestClient(app)

    def act_as(who: str):
        current["uid"] = ids[who]

    return client, engine, ids, act_as


def _post_import(client, *, filename="track.gpx", content=_SINGLE_TRACK_GPX,
                  date="2024-06-01", start_time="09:00", end_time="10:00",
                  activity_type="Hike", owner=None):
    data = {
        "date": date, "start_time": start_time, "end_time": end_time,
        "activity_type": activity_type,
    }
    params = {"owner": owner} if owner is not None else {}
    return client.post(
        "/api/projects/Trip/activities/import-gpx",
        params=params,
        files={"file": (filename, content, "application/gpx+xml")},
        data=data,
    )


def test_happy_path_imports_gpx_activity(env, monkeypatch):
    client, engine, ids, act_as = env

    import api.activities as activities_mod

    def _no_enrich(*a, **k):
        raise AssertionError("GPX import must not schedule Strava enrichment")

    monkeypatch.setattr(activities_mod, "_enrich_activities_background", _no_enrich)

    resp = _post_import(client)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    activity_id = body["activity_id"]
    assert body["total"] == 1

    track_resp = client.get(f"/api/projects/Trip/activities/{activity_id}/track")
    assert track_resp.status_code == 200, track_resp.text
    act = track_resp.json()
    assert act["source"] == "gpx"
    assert act["manual"] is True
    assert act["type"] == "Hike"
    assert act["distance"] > 0
    assert act["total_elevation_gain"] > 0
    assert act["map"]["summary_polyline"]
    # start/end times: 09:00 -> 10:00 on 2024-06-01 = 3600s.
    assert act["elapsed_time"] == 3600
    assert act["moving_time"] == 3600

    from src.gpx.importer import gpx_track_to_points, parse_gpx_bytes
    from src.models.track_edit import recompute_track_metrics

    gpx = parse_gpx_bytes(_SINGLE_TRACK_GPX)
    expected = recompute_track_metrics(gpx_track_to_points(gpx))
    assert act["distance"] == pytest.approx(expected.distance, rel=1e-6)
    assert act["total_elevation_gain"] == pytest.approx(expected.total_elevation_gain, rel=1e-6)

    with Session(engine) as sess:
        row = sess.get(DBActivity, activity_id)
        assert row.source == "gpx"


def test_multi_track_gpx_rejected(env):
    client, *_ = env
    resp = _post_import(client, content=_MULTI_TRACK_GPX)
    assert resp.status_code == 422
    errors = resp.json()["detail"]["errors"]
    assert any("single track" in e.lower() for e in errors)


def test_end_time_before_start_time_rejected(env):
    client, *_ = env
    resp = _post_import(client, start_time="10:00", end_time="09:00")
    assert resp.status_code == 422
    errors = resp.json()["detail"]["errors"]
    assert any("end time" in e.lower() for e in errors)


def test_viewer_role_forbidden(env):
    client, _, ids, act_as = env
    act_as("viewer")
    resp = _post_import(client, owner=ids["owner"])
    assert resp.status_code == 403


def test_synthetic_ids_do_not_collide(env):
    client, *_ = env
    r1 = _post_import(client, filename="a.gpx")
    assert r1.status_code == 200, r1.text
    r2 = _post_import(client, filename="b.gpx")
    assert r2.status_code == 200, r2.text
    assert r1.json()["activity_id"] != r2.json()["activity_id"]
