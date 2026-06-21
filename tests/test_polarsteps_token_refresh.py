"""Gracious Polarsteps token-expiry handling.

Polarsteps' unofficial API authenticates with a single ``remember_token``
cookie and has no refresh endpoint. Two behaviours keep users connected:

1. The client captures any *rotated* cookie Polarsteps hands back (sliding
   expiry) so the freshest token can be persisted — pushing expiry out without
   user action.
2. The read endpoints persist that rotated token and raise a 401 whose detail
   contains "polarsteps", so the client can tell a Polarsteps cookie expiry
   apart from an app-JWT expiry and show an inline reconnect panel.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import api.polarsteps as ps_api
import models.db as db_module
from api.deps import get_current_user
from api.polarsteps import POLARSTEPS_TOKEN_EXPIRED_DETAIL, router as polarsteps_router
from models.user import PolarstepsToken, UserInfo
from src.api.polarsteps_client import PolarstepsClient


# ── Client: rotated-cookie capture ──────────────────────────────────────────────

class _FakeResp:
    status_code = 200

    def json(self):
        return {"ok": True}

    def raise_for_status(self):
        pass


def test_client_captures_rotated_cookie():
    c = PolarstepsClient("1|old")

    def fake_get(url, params=None, timeout=None):
        # Simulate Polarsteps refreshing the remember_token cookie.
        c._session.cookies.set("remember_token", "1|new", domain=".polarsteps.com")
        return _FakeResp()

    c._session.get = fake_get  # type: ignore[method-assign]
    c._get("/users/1")

    assert c.current_token == "1|new"
    assert c.token_rotated is True


def test_client_no_rotation_leaves_token_unchanged():
    c = PolarstepsClient("1|same")

    def fake_get(url, params=None, timeout=None):
        return _FakeResp()  # cookie jar untouched → no rotation

    c._session.get = fake_get  # type: ignore[method-assign]
    c._get("/users/1")

    assert c.current_token == "1|same"
    assert c.token_rotated is False


# ── Endpoint: persist rotation + detectable 401 ─────────────────────────────────

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
    return TestClient(app), engine, uid


def _stored_token(engine, uid) -> str:
    with Session(engine) as sess:
        tok = sess.exec(
            select(PolarstepsToken).where(PolarstepsToken.user_info_id == uid)
        ).first()
        return tok.remember_token


def test_trips_persists_rotated_token(env, monkeypatch):
    client, engine, uid = env

    class _FakeClient:
        token_rotated = True
        current_token = "1|new"

        def __init__(self, token):
            pass

        def get_trips(self, user_id):
            return [{"id": 7, "name": "Trip", "steps": []}]

    monkeypatch.setattr(ps_api, "PolarstepsClient", _FakeClient)

    resp = client.get("/api/polarsteps/trips")
    assert resp.status_code == 200
    assert _stored_token(engine, uid) == "1|new"  # rotation captured


def test_trips_unchanged_token_not_rewritten(env, monkeypatch):
    client, engine, uid = env

    class _FakeClient:
        token_rotated = False
        current_token = "1|old"

        def __init__(self, token):
            pass

        def get_trips(self, user_id):
            return [{"id": 7, "name": "Trip", "steps": []}]

    monkeypatch.setattr(ps_api, "PolarstepsClient", _FakeClient)

    resp = client.get("/api/polarsteps/trips")
    assert resp.status_code == 200
    assert _stored_token(engine, uid) == "1|old"


def test_expired_token_raises_detectable_401(env, monkeypatch):
    client, _engine, _uid = env

    class _FakeClient:
        token_rotated = False
        current_token = "1|old"

        def __init__(self, token):
            pass

        def get_trips(self, user_id):
            raise PermissionError("Invalid or expired Polarsteps token")

    monkeypatch.setattr(ps_api, "PolarstepsClient", _FakeClient)

    resp = client.get("/api/polarsteps/trips")
    assert resp.status_code == 401
    assert resp.json()["detail"] == POLARSTEPS_TOKEN_EXPIRED_DETAIL
    # The marker the Flutter client keys off, distinct from app-JWT "Token expired".
    assert "polarsteps" in resp.json()["detail"].lower()
