"""API tests for project sharing endpoints — split out of api/projects.py into
api/project_shares.py. Covers the previously-untested happy paths: share-link
create/revoke (both full and no-memories variants), share-info, and visitors."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import models.db as db_module
from api.deps import get_current_user
from api.project_shares import router as project_shares_router
from models.project_db import DBProject, DBShareVisit
from models.user import UserInfo


def _seed(engine) -> int:
    with Session(engine) as sess:
        u = UserInfo(display_name="A", email="a@e.com")
        sess.add(u); sess.commit(); sess.refresh(u)
        proj = DBProject(user_info_id=u.id, name="My Trip")
        sess.add(proj); sess.commit(); sess.refresh(proj)
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
    app.include_router(project_shares_router)
    return TestClient(app), engine, uid


def test_create_share_link_is_idempotent(env):
    client, *_ = env
    r1 = client.post("/api/projects/My Trip/share")
    assert r1.status_code == 200, r1.text
    token1 = r1.json()["share_token"]
    assert token1

    r2 = client.post("/api/projects/My Trip/share")
    assert r2.json()["share_token"] == token1  # same token returned, not regenerated


def test_create_share_link_project_not_found(env):
    client, *_ = env
    resp = client.post("/api/projects/No Such Trip/share")
    assert resp.status_code == 404


def test_share_info_reflects_created_tokens(env):
    client, *_ = env
    resp = client.get("/api/projects/My Trip/share-info")
    assert resp.status_code == 200
    assert resp.json() == {"share_token": None, "share_token_no_memories": None}

    token = client.post("/api/projects/My Trip/share").json()["share_token"]
    resp = client.get("/api/projects/My Trip/share-info")
    assert resp.json()["share_token"] == token
    assert resp.json()["share_token_no_memories"] is None


def test_revoke_share_link_clears_token(env):
    client, *_ = env
    client.post("/api/projects/My Trip/share")
    resp = client.delete("/api/projects/My Trip/share")
    assert resp.status_code == 204

    info = client.get("/api/projects/My Trip/share-info").json()
    assert info["share_token"] is None


def test_revoke_share_link_without_existing_token_is_noop(env):
    client, *_ = env
    resp = client.delete("/api/projects/My Trip/share")
    assert resp.status_code == 204


def test_create_no_memories_link_is_idempotent(env):
    client, *_ = env
    r1 = client.post("/api/projects/My Trip/share/no-memories")
    assert r1.status_code == 200, r1.text
    token1 = r1.json()["share_token_no_memories"]
    assert token1

    r2 = client.post("/api/projects/My Trip/share/no-memories")
    assert r2.json()["share_token_no_memories"] == token1


def test_revoke_no_memories_link_clears_token(env):
    client, *_ = env
    client.post("/api/projects/My Trip/share/no-memories")
    resp = client.delete("/api/projects/My Trip/share/no-memories")
    assert resp.status_code == 204

    info = client.get("/api/projects/My Trip/share-info").json()
    assert info["share_token_no_memories"] is None


def test_full_and_no_memories_tokens_are_independent(env):
    client, *_ = env
    full = client.post("/api/projects/My Trip/share").json()["share_token"]
    no_mem = client.post("/api/projects/My Trip/share/no-memories").json()["share_token_no_memories"]
    assert full != no_mem

    client.delete("/api/projects/My Trip/share")
    info = client.get("/api/projects/My Trip/share-info").json()
    assert info["share_token"] is None
    assert info["share_token_no_memories"] == no_mem  # untouched by revoking the other


def test_share_visitors_empty_when_no_visits(env):
    client, *_ = env
    resp = client.get("/api/projects/My Trip/share/visitors")
    assert resp.status_code == 200
    assert resp.json() == {
        "full": {"anonymous_count": 0, "registered": []},
        "no_memories": {"anonymous_count": 0, "registered": []},
    }


def test_share_visitors_counts_anonymous_and_registered(env):
    client, engine, uid = env
    with Session(engine) as sess:
        proj = sess.exec(
            select(DBProject).where(DBProject.name == "My Trip")
        ).first()
        visitor = UserInfo(display_name="Visitor", email="v@e.com")
        sess.add(visitor); sess.commit(); sess.refresh(visitor)
        sess.add(DBShareVisit(
            project_id=proj.id, token_type="full", visitor_type="anonymous",
            anonymous_id="anon-1", last_seen_at=100.0,
        ))
        sess.add(DBShareVisit(
            project_id=proj.id, token_type="full", visitor_type="registered",
            user_info_id=visitor.id, last_seen_at=200.0,
        ))
        sess.add(DBShareVisit(
            project_id=proj.id, token_type="no_memories", visitor_type="anonymous",
            anonymous_id="anon-2", last_seen_at=150.0,
        ))
        sess.commit()

    resp = client.get("/api/projects/My Trip/share/visitors")
    assert resp.status_code == 200
    body = resp.json()
    assert body["full"]["anonymous_count"] == 1
    assert body["full"]["registered"] == [
        {"display_name": "Visitor", "email": "v@e.com", "last_seen_at": 200.0}
    ]
    assert body["no_memories"]["anonymous_count"] == 1
    assert body["no_memories"]["registered"] == []


def test_share_visitors_project_not_found(env):
    client, *_ = env
    resp = client.get("/api/projects/No Such Trip/share/visitors")
    assert resp.status_code == 404
