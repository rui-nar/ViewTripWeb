"""update_sync_meta must return its body without DetachedInstanceError.

Regression: the endpoint built its response dict by reading meta.* AFTER the
`with get_session()` block closed. With expire_on_commit=True the committed row
is expired and detached, so attribute access raised DetachedInstanceError. The
values are now captured inside the session.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import models.db as db_module
from api.deps import get_current_user
from api.projects import router as projects_router
from models.project_db import DBProject
from models.user import UserInfo


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
        sess.add(u); sess.commit(); sess.refresh(u)
        sess.add(DBProject(user_info_id=u.id, name="My Trip")); sess.commit()
        uid = u.id

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(uid), "email": "a@e.com"}
    app.include_router(projects_router)
    return TestClient(app)


def test_update_sync_meta_returns_body(env):
    resp = env.put("/api/projects/My Trip/sync-meta", json={
        "auto_sync_enabled": True,
        "linked_ps_trip_id": 42,
        "last_ps_sync_at": 1234.5,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["auto_sync_enabled"] is True
    assert body["linked_ps_trip_id"] == 42
    assert body["last_ps_sync_at"] == 1234.5


def test_update_sync_meta_persists_across_calls(env):
    env.put("/api/projects/My Trip/sync-meta", json={"auto_sync_enabled": True})
    resp = env.put("/api/projects/My Trip/sync-meta", json={"linked_ps_trip_id": 7})
    assert resp.status_code == 200
    assert resp.json()["auto_sync_enabled"] is True   # earlier value retained
    assert resp.json()["linked_ps_trip_id"] == 7
