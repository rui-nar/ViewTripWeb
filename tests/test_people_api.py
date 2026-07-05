"""API tests for the people directory (issue #40, phase 2)."""
from __future__ import annotations

import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import models.db as db_module
from api.deps import get_current_user
from api.people import router as people_router
from api.projects import router as projects_router
from models.project_db import DBPerson, DBProject
from models.user import UserInfo


def _seed(engine):
    with Session(engine) as sess:
        u = UserInfo(display_name="A", email="a@e.com")
        sess.add(u); sess.commit(); sess.refresh(u)
        proj = DBProject(user_info_id=u.id, name="My Trip")
        sess.add(proj); sess.commit(); sess.refresh(proj)
        other = UserInfo(display_name="B", email="b@e.com")
        sess.add(other); sess.commit(); sess.refresh(other)
        return u.id, other.id


@pytest.fixture
def env(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_module, "engine", engine)
    SQLModel.metadata.create_all(engine)
    uid, other_uid = _seed(engine)

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(uid), "email": "a@e.com"}
    app.include_router(people_router)
    app.include_router(projects_router)
    return TestClient(app), engine, uid, other_uid


def _jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), (200, 30, 30)).save(buf, "JPEG")
    return buf.getvalue()


def test_create_person_and_appears_in_project(env):
    client, _, _, _ = env
    resp = client.post("/api/people/", json={
        "project_name": "My Trip", "name": "Alice", "email": "alice@x.com",
        "phone": "123", "polarsteps": "alice", "notes": "met at hostel",
    })
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]

    # Surfaced in the full project payload (owner view).
    proj = client.get("/api/projects/My Trip").json()
    people = proj["people"]
    assert len(people) == 1
    assert people[0]["id"] == pid
    assert people[0]["name"] == "Alice"
    assert people[0]["polarsteps"] == "alice"


def test_create_person_without_name_is_allowed(env):
    client, _, _, _ = env
    resp = client.post("/api/people/", json={"project_name": "My Trip"})
    assert resp.status_code == 201, resp.text
    proj = client.get("/api/projects/My Trip").json()
    assert proj["people"][0]["name"] is None


def test_get_person_returns_encounters_key(env):
    client, _, _, _ = env
    pid = client.post("/api/people/", json={"project_name": "My Trip", "name": "Bob"}).json()["id"]
    resp = client.get(f"/api/people/{pid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Bob"
    assert body["encounters"] == []


def test_update_person(env):
    client, _, _, _ = env
    pid = client.post("/api/people/", json={"project_name": "My Trip", "name": "Bob"}).json()["id"]
    resp = client.put(f"/api/people/{pid}", json={"name": "Bobby", "email": "b@x.com"})
    assert resp.status_code == 204
    body = client.get(f"/api/people/{pid}").json()
    assert body["name"] == "Bobby"
    assert body["email"] == "b@x.com"


def test_delete_person(env):
    client, engine, _, _ = env
    pid = client.post("/api/people/", json={"project_name": "My Trip", "name": "Bob"}).json()["id"]
    resp = client.delete(f"/api/people/{pid}")
    assert resp.status_code == 204
    with Session(engine) as sess:
        assert sess.get(DBPerson, pid) is None


def test_cannot_access_another_users_person(env):
    client, engine, _, other_uid = env
    # Seed a project + person owned by the OTHER user.
    with Session(engine) as sess:
        p = DBProject(user_info_id=other_uid, name="Theirs")
        sess.add(p); sess.commit(); sess.refresh(p)
        person = DBPerson(project_id=p.id, name="Secret")
        sess.add(person); sess.commit(); sess.refresh(person)
        other_pid = person.id
    assert client.get(f"/api/people/{other_pid}").status_code == 403
    assert client.put(f"/api/people/{other_pid}", json={"name": "x"}).status_code == 403
    assert client.delete(f"/api/people/{other_pid}").status_code == 403


def test_avatar_upload_serve_delete(env):
    client, _, _, _ = env
    pid = client.post("/api/people/", json={"project_name": "My Trip", "name": "Bob"}).json()["id"]

    up = client.post(f"/api/people/{pid}/avatar",
                     files={"file": ("a.jpg", _jpeg_bytes(), "image/jpeg")})
    assert up.status_code == 201, up.text
    assert client.get(f"/api/people/{pid}").json()["avatar_photo"] is not None

    assert client.get(f"/api/people/{pid}/avatar").status_code == 200
    assert client.get(f"/api/people/{pid}/avatar/thumb").status_code == 200

    assert client.delete(f"/api/people/{pid}/avatar").status_code == 204
    assert client.get(f"/api/people/{pid}").json()["avatar_photo"] is None
    assert client.get(f"/api/people/{pid}/avatar").status_code == 404
