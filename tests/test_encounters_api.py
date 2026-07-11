"""API tests for encounters + timeline/sort integration (issue #40, phase 3)."""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import models.db as db_module
from api.deps import get_current_user
from api.encounters import router as encounters_router
from api.groups import router as groups_router
from api.people import router as people_router
from api.project_items import router as project_items_router
from api.projects import router as projects_router
from models.project_db import DBActivity, DBEncounter, DBPerson, DBPersonGroup, DBProject, DBProjectItem
from models.user import UserInfo


def _seed(engine):
    with Session(engine) as sess:
        u = UserInfo(display_name="A", email="a@e.com")
        sess.add(u); sess.commit(); sess.refresh(u)
        proj = DBProject(user_info_id=u.id, name="My Trip")
        sess.add(proj); sess.commit(); sess.refresh(proj)
        # One activity on 2024-06-01 so geo defaulting has a day location.
        act = DBActivity(
            id=111, user_info_id=u.id, name="Ride", type="Ride",
            distance=1000.0, moving_time=100, elapsed_time=120,
            total_elevation_gain=0.0,
            start_date_local="2024-06-01T09:00:00Z",
            start_latlng_json=json.dumps([48.0, 2.0]),
            end_latlng_json=json.dumps([48.5, 2.5]),
        )
        sess.add(act)
        sess.add(DBProjectItem(project_id=proj.id, position=0,
                               item_type="activity", activity_id=111))
        person = DBPerson(project_id=proj.id, name="Alice")
        sess.add(person); sess.commit(); sess.refresh(person)
        return u.id, person.id


@pytest.fixture
def env(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_module, "engine", engine)
    SQLModel.metadata.create_all(engine)
    uid, pid = _seed(engine)

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(uid), "email": "a@e.com"}
    app.include_router(encounters_router)
    app.include_router(groups_router)
    app.include_router(people_router)
    app.include_router(project_items_router)
    app.include_router(projects_router)
    return TestClient(app), engine, uid, pid


def _create(client, pid, date, **kw):
    body = {"project_name": "My Trip", "person_id": pid, "date": date}
    body.update(kw)
    r = client.post("/api/encounters/", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create_with_group(client, gid, date, **kw):
    body = {"project_name": "My Trip", "group_id": gid, "date": date}
    body.update(kw)
    r = client.post("/api/encounters/", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _seed_group(engine, pid, name="Crew"):
    """A group in the same project as person [pid] (issue #56)."""
    with Session(engine) as sess:
        person = sess.get(DBPerson, pid)
        g = DBPersonGroup(project_id=person.project_id, name=name)
        sess.add(g); sess.commit(); sess.refresh(g)
        return g.id


def test_create_encounter_appears_as_item(env):
    client, _, _, pid = env
    eid = _create(client, pid, "2024-06-01", description="met at cafe")
    items = client.get("/api/projects/My Trip").json()["items"]
    enc_items = [it for it in items if it["item_type"] == "encounter"]
    assert len(enc_items) == 1
    enc = enc_items[0]["encounter"]
    assert enc["id"] == eid
    assert enc["person_id"] == pid
    assert enc["description"] == "met at cafe"


def test_encounter_defaults_to_day_location(env):
    client, _, _, pid = env
    _create(client, pid, "2024-06-01")  # start_of_day default
    enc = [it for it in client.get("/api/projects/My Trip").json()["items"]
           if it["item_type"] == "encounter"][0]["encounter"]
    assert enc["lat"] == 48.0 and enc["lon"] == 2.0


def test_custom_geo_is_respected(env):
    client, _, _, pid = env
    _create(client, pid, "2024-06-01", geo_mode="custom", lat=10.0, lon=20.0)
    enc = [it for it in client.get("/api/projects/My Trip").json()["items"]
           if it["item_type"] == "encounter"][0]["encounter"]
    assert enc["lat"] == 10.0 and enc["lon"] == 20.0


def test_person_page_lists_encounters(env):
    client, _, _, pid = env
    _create(client, pid, "2024-06-02", description="dinner")
    _create(client, pid, "2024-06-01", description="lunch")
    body = client.get(f"/api/people/{pid}").json()
    dates = [e["date"] for e in body["encounters"]]
    assert dates == ["2024-06-01", "2024-06-02"]  # ordered by date


def test_sort_orders_encounters_by_date(env):
    client, _, _, pid = env
    # Insert a later-dated encounter first, then an earlier one.
    _create(client, pid, "2024-06-03")
    _create(client, pid, "2024-06-01")
    assert client.put("/api/projects/My Trip/items/sort", json={}).status_code == 204
    items = client.get("/api/projects/My Trip").json()["items"]
    enc_dates = [it["encounter"]["date"] for it in items if it["item_type"] == "encounter"]
    assert enc_dates == ["2024-06-01", "2024-06-03"]


def test_update_encounter(env):
    client, _, _, pid = env
    eid = _create(client, pid, "2024-06-01", description="old")
    r = client.put(f"/api/encounters/{eid}", json={
        "person_id": pid, "date": "2024-06-02", "geo_mode": "custom",
        "lat": 1.0, "lon": 2.0, "description": "new",
    })
    assert r.status_code == 204
    enc = [it for it in client.get("/api/projects/My Trip").json()["items"]
           if it["item_type"] == "encounter"][0]["encounter"]
    assert enc["date"] == "2024-06-02" and enc["description"] == "new"


def test_delete_encounter_keeps_person(env):
    client, engine, _, pid = env
    eid = _create(client, pid, "2024-06-01")
    assert client.delete(f"/api/encounters/{eid}").status_code == 204
    with Session(engine) as sess:
        assert sess.get(DBEncounter, eid) is None
        assert sess.get(DBPerson, pid) is not None
    items = client.get("/api/projects/My Trip").json()["items"]
    assert not any(it["item_type"] == "encounter" for it in items)


def test_deleting_person_cascades_encounters(env):
    client, engine, _, pid = env
    eid = _create(client, pid, "2024-06-01")
    assert client.delete(f"/api/people/{pid}").status_code == 204
    with Session(engine) as sess:
        assert sess.get(DBEncounter, eid) is None
    items = client.get("/api/projects/My Trip").json()["items"]
    assert not any(it["item_type"] == "encounter" for it in items)


def test_encounter_requires_person_in_project(env):
    client, engine, uid, _ = env
    # A person in a different project of the same user.
    with Session(engine) as sess:
        p2 = DBProject(user_info_id=uid, name="Other")
        sess.add(p2); sess.commit(); sess.refresh(p2)
        other_person = DBPerson(project_id=p2.id, name="Zoe")
        sess.add(other_person); sess.commit(); sess.refresh(other_person)
        opid = other_person.id
    r = client.post("/api/encounters/", json={
        "project_name": "My Trip", "person_id": opid, "date": "2024-06-01",
    })
    assert r.status_code == 404


# ── Group encounters (issue #56) ────────────────────────────────────────────

def test_create_encounter_with_group(env):
    client, _, _, pid = env
    gid = _seed_group(env[1], pid)
    eid = _create_with_group(client, gid, "2024-06-01", description="met the crew")
    enc = [it for it in client.get("/api/projects/My Trip").json()["items"]
           if it["item_type"] == "encounter"][0]["encounter"]
    assert enc["id"] == eid
    assert enc["group_id"] == gid
    assert enc["person_id"] is None


def test_create_encounter_requires_exactly_one_of_person_or_group(env):
    client, engine, _, pid = env
    gid = _seed_group(engine, pid)
    # Neither set.
    r = client.post("/api/encounters/", json={
        "project_name": "My Trip", "date": "2024-06-01",
    })
    assert r.status_code == 400
    # Both set.
    r = client.post("/api/encounters/", json={
        "project_name": "My Trip", "person_id": pid, "group_id": gid,
        "date": "2024-06-01",
    })
    assert r.status_code == 400


def test_encounter_requires_group_in_project(env):
    client, engine, uid, _ = env
    with Session(engine) as sess:
        p2 = DBProject(user_info_id=uid, name="Other")
        sess.add(p2); sess.commit(); sess.refresh(p2)
        other_group = DBPersonGroup(project_id=p2.id, name="Other crew")
        sess.add(other_group); sess.commit(); sess.refresh(other_group)
        ogid = other_group.id
    r = client.post("/api/encounters/", json={
        "project_name": "My Trip", "group_id": ogid, "date": "2024-06-01",
    })
    assert r.status_code == 404


def test_update_encounter_switches_person_to_group(env):
    client, engine, _, pid = env
    gid = _seed_group(engine, pid)
    eid = _create(client, pid, "2024-06-01")
    r = client.put(f"/api/encounters/{eid}", json={
        "group_id": gid, "date": "2024-06-01", "geo_mode": "custom",
        "lat": 1.0, "lon": 2.0,
    })
    assert r.status_code == 204
    enc = [it for it in client.get("/api/projects/My Trip").json()["items"]
           if it["item_type"] == "encounter"][0]["encounter"]
    assert enc["group_id"] == gid
    assert enc["person_id"] is None


def test_deleting_group_cascades_encounters(env):
    client, engine, _, pid = env
    gid = _seed_group(engine, pid)
    eid = _create_with_group(client, gid, "2024-06-01")
    assert client.delete(f"/api/groups/{gid}").status_code == 204
    with Session(engine) as sess:
        assert sess.get(DBEncounter, eid) is None
        assert sess.get(DBPersonGroup, gid) is None
    items = client.get("/api/projects/My Trip").json()["items"]
    assert not any(it["item_type"] == "encounter" for it in items)
