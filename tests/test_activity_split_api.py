"""API + repo integration tests for activity split + local-activity delete (#31, phase 2)."""
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
from api.projects import router as projects_router
from models.project_db import DBActivity, DBProject, DBProjectItem
from models.user import UserInfo
from src.models.track_edit import align_points, recompute_track_metrics

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
        # Sandwich the activity between two segments to verify item ordering.
        sess.add(DBProjectItem(project_id=proj.id, position=0,
                               item_type="segment", segment_json=json.dumps({"id": "s0"})))
        sess.add(DBProjectItem(project_id=proj.id, position=1,
                               item_type="activity", activity_id=111))
        sess.add(DBProjectItem(project_id=proj.id, position=2,
                               item_type="segment", segment_json=json.dumps({"id": "s1"})))
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
    app.include_router(projects_router)
    return TestClient(app), engine


def test_split_yields_two_activities(env):
    client, engine = env
    resp = client.post("/api/projects/My Trip/activities/111/split", json={"split_index": 2})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    acts = {a["id"]: a for a in body["activities"]}
    assert 111 in acts                       # head keeps its id
    tail_ids = [i for i in acts if i < 0]
    assert len(tail_ids) == 1                 # exactly one local tail
    tail = acts[tail_ids[0]]
    assert tail["name"] == "Ride (2)"
    assert tail["manual"] is True
    assert acts[111]["is_edited"] is True
    assert tail["is_edited"] is True


def test_split_distances_sum_to_original(env):
    client, _ = env
    resp = client.post("/api/projects/My Trip/activities/111/split", json={"split_index": 2})
    acts = {a["id"]: a for a in resp.json()["activities"]}
    tail = next(a for i, a in acts.items() if i < 0)
    full = recompute_track_metrics(align_points(polyline_lib.encode(_TRACK), None)).distance
    assert acts[111]["distance"] + tail["distance"] == pytest.approx(full, rel=0.02)


def test_split_item_ordering(env):
    client, engine = env
    client.post("/api/projects/My Trip/activities/111/split", json={"split_index": 2})
    resp = client.get("/api/projects/My Trip")
    items = resp.json()["items"]
    types = [it["item_type"] for it in items]
    assert types == ["segment", "activity", "activity", "segment"]
    # Head immediately precedes the tail; tail is the negative id.
    assert items[1]["activity_id"] == 111
    assert items[2]["activity_id"] < 0


def test_split_index_out_of_range(env):
    client, _ = env
    resp = client.post("/api/projects/My Trip/activities/111/split", json={"split_index": 0})
    assert resp.status_code == 422
    resp = client.post("/api/projects/My Trip/activities/111/split", json={"split_index": 99})
    assert resp.status_code == 422


def test_delete_local_removes_row_and_item(env):
    client, engine = env
    resp = client.post("/api/projects/My Trip/activities/111/split", json={"split_index": 2})
    tail_id = next(i for i in (a["id"] for a in resp.json()["activities"]) if i < 0)

    resp = client.delete(f"/api/projects/My Trip/activities/{tail_id}/local")
    assert resp.status_code == 204

    with Session(engine) as sess:
        assert sess.get(DBActivity, tail_id) is None
    # Head remains, tail item gone.
    body = client.get("/api/projects/My Trip").json()
    ids = [it.get("activity_id") for it in body["items"] if it["item_type"] == "activity"]
    assert ids == [111]


def test_delete_local_rejects_strava_id(env):
    client, _ = env
    # 111 is a real Strava id (>= 0) — must not be row-deleted via this endpoint.
    resp = client.delete("/api/projects/My Trip/activities/111/local")
    assert resp.status_code == 404
