"""API tests for people groups + membership (issue #50)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import models.db as db_module
from api.deps import get_current_user
from api.groups import router as groups_router
from api.people import router as people_router
from api.projects import router as projects_router
from models.project_db import DBPerson, DBPersonGroup, DBProject
from models.user import UserInfo


def _seed(engine):
    with Session(engine) as sess:
        u = UserInfo(display_name="A", email="a@e.com")
        sess.add(u); sess.commit(); sess.refresh(u)
        proj = DBProject(user_info_id=u.id, name="Trip")
        sess.add(proj); sess.commit(); sess.refresh(proj)
        alice = DBPerson(project_id=proj.id, name="Alice")
        bob = DBPerson(project_id=proj.id, name="Bob")
        sess.add(alice); sess.add(bob); sess.commit()
        sess.refresh(alice); sess.refresh(bob)
        other = UserInfo(display_name="B", email="b@e.com")
        sess.add(other); sess.commit(); sess.refresh(other)
        return u.id, alice.id, bob.id, other.id


@pytest.fixture
def env(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_module, "engine", engine)
    SQLModel.metadata.create_all(engine)
    uid, alice, bob, other = _seed(engine)

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(uid), "email": "a@e.com"}
    app.include_router(groups_router)
    app.include_router(people_router)
    app.include_router(projects_router)
    return TestClient(app), engine, alice, bob, other


def _create_group(client, **kw):
    body = {"project_name": "Trip"}
    body.update(kw)
    r = client.post("/api/groups/", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_create_group_appears_in_project(env):
    client, _, _, _, _ = env
    gid = _create_group(client, name="Hostel crew",
                        nationalities=["FR", "DE"],
                        socials=[{"network": "instagram", "handle": "crew"}])
    proj = client.get("/api/projects/Trip").json()
    groups = proj["groups"]
    assert len(groups) == 1
    assert groups[0]["id"] == gid
    assert groups[0]["name"] == "Hostel crew"
    assert groups[0]["nationalities"] == ["FR", "DE"]
    assert groups[0]["socials"] == [{"network": "instagram", "handle": "crew"}]


def test_get_group_members_empty_then_set(env):
    client, _, alice, bob, _ = env
    gid = _create_group(client, name="G")
    assert client.get(f"/api/groups/{gid}").json()["members"] == []

    r = client.put(f"/api/groups/{gid}/members", json={"person_ids": [alice, bob]})
    assert r.status_code == 204
    members = client.get(f"/api/groups/{gid}").json()["members"]
    assert sorted(m["id"] for m in members) == sorted([alice, bob])
    # group_id surfaced on the people in the project payload
    people = {p["id"]: p for p in client.get("/api/projects/Trip").json()["people"]}
    assert people[alice]["group_id"] == gid
    assert people[bob]["group_id"] == gid


def test_set_members_clears_removed(env):
    client, _, alice, bob, _ = env
    gid = _create_group(client, name="G")
    client.put(f"/api/groups/{gid}/members", json={"person_ids": [alice, bob]})
    # Now set to just alice → bob should be ungrouped.
    client.put(f"/api/groups/{gid}/members", json={"person_ids": [alice]})
    people = {p["id"]: p for p in client.get("/api/projects/Trip").json()["people"]}
    assert people[alice]["group_id"] == gid
    assert people[bob]["group_id"] is None


def test_person_moves_between_groups(env):
    client, _, alice, _, _ = env
    g1 = _create_group(client, name="G1")
    g2 = _create_group(client, name="G2")
    client.put(f"/api/groups/{g1}/members", json={"person_ids": [alice]})
    client.put(f"/api/groups/{g2}/members", json={"person_ids": [alice]})
    people = {p["id"]: p for p in client.get("/api/projects/Trip").json()["people"]}
    assert people[alice]["group_id"] == g2  # moved, only one group
    assert client.get(f"/api/groups/{g1}").json()["members"] == []


def test_update_group(env):
    client, _, _, _, _ = env
    gid = _create_group(client, name="Old")
    r = client.put(f"/api/groups/{gid}", json={"name": "New", "nationalities": ["IT"]})
    assert r.status_code == 204
    g = client.get(f"/api/groups/{gid}").json()
    assert g["name"] == "New" and g["nationalities"] == ["IT"]


def test_delete_group_ungroups_members(env):
    client, engine, alice, _, _ = env
    gid = _create_group(client, name="G")
    client.put(f"/api/groups/{gid}/members", json={"person_ids": [alice]})
    assert client.delete(f"/api/groups/{gid}").status_code == 204
    with Session(engine) as sess:
        assert sess.get(DBPersonGroup, gid) is None
        assert sess.get(DBPerson, alice) is not None       # person kept
        assert sess.get(DBPerson, alice).group_id is None  # ungrouped


def test_set_members_rejects_foreign_person(env):
    client, engine, _, _, other_uid = env
    gid = _create_group(client, name="G")
    with Session(engine) as sess:
        p2 = DBProject(user_info_id=other_uid, name="Theirs")
        sess.add(p2); sess.commit(); sess.refresh(p2)
        stranger = DBPerson(project_id=p2.id, name="Zoe")
        sess.add(stranger); sess.commit(); sess.refresh(stranger)
        sid = stranger.id
    r = client.put(f"/api/groups/{gid}/members", json={"person_ids": [sid]})
    assert r.status_code == 404


def test_cannot_access_another_users_group(env):
    client, engine, _, _, other_uid = env
    with Session(engine) as sess:
        p2 = DBProject(user_info_id=other_uid, name="Theirs")
        sess.add(p2); sess.commit(); sess.refresh(p2)
        g = DBPersonGroup(project_id=p2.id, name="Secret")
        sess.add(g); sess.commit(); sess.refresh(g)
        ogid = g.id
    assert client.get(f"/api/groups/{ogid}").status_code == 403
    assert client.put(f"/api/groups/{ogid}", json={"name": "x"}).status_code == 403
    assert client.delete(f"/api/groups/{ogid}").status_code == 403
