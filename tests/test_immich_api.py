"""Tests for the Immich proxy endpoints (issue #33, workstream A).

Covers: config save success/failure (validated against Immich's
/api/users/me), status reflecting saved config, disconnect clearing it,
search proxying params + reshaping the response into the app's candidate
schema, thumbnail/original streaming bytes through, and that every route
requires auth and is scoped to the calling user.
"""
from __future__ import annotations

import requests
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import api.immich as immich_module
import models.db as db_module
from api.deps import get_current_user
from api.immich import router as immich_router
from models.user import ImmichToken, UserInfo


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, headers=None, content=b"", chunks=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.headers = headers or {}
        self.content = content
        self._chunks = chunks if chunks is not None else ([content] if content else [])

    def json(self):
        return self._json

    def iter_content(self, chunk_size=None):
        return iter(self._chunks)


def _seed_user(engine) -> int:
    with Session(engine) as sess:
        u = UserInfo(display_name="A", email="a@e.com")
        sess.add(u)
        sess.commit()
        sess.refresh(u)
        return u.id


def _seed_second_user(engine) -> int:
    with Session(engine) as sess:
        u = UserInfo(display_name="B", email="b@e.com")
        sess.add(u)
        sess.commit()
        sess.refresh(u)
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
    uid = _seed_user(engine)

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(uid), "email": "a@e.com"}
    app.include_router(immich_router)
    return TestClient(app), engine, uid


def _stored_token(engine, uid) -> ImmichToken | None:
    with Session(engine) as sess:
        return sess.exec(
            select(ImmichToken).where(ImmichToken.user_info_id == uid)
        ).first()


def _connect(engine, uid, server_url="https://immich.example.com", api_key="secret-key"):
    """Directly seed a connected ImmichToken row, bypassing PUT /config."""
    with Session(engine) as sess:
        sess.add(ImmichToken(user_info_id=uid, server_url=server_url, api_key=api_key))
        sess.commit()


# ── Status ────────────────────────────────────────────────────────────────────

def test_status_not_connected(env):
    client, _engine, _uid = env
    resp = client.get("/api/immich/status")
    assert resp.status_code == 200
    assert resp.json() == {"connected": False, "server_url": None}


def test_status_reflects_saved_config(env):
    client, engine, uid = env
    _connect(engine, uid, server_url="https://photos.home.arpa")
    resp = client.get("/api/immich/status")
    assert resp.status_code == 200
    assert resp.json() == {"connected": True, "server_url": "https://photos.home.arpa"}


# ── Config (PUT) ──────────────────────────────────────────────────────────────

def test_config_success_validates_and_saves(env, monkeypatch):
    client, engine, uid = env
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        return _FakeResponse(status_code=200, json_data={"id": "user-1"})

    monkeypatch.setattr(immich_module.requests, "get", fake_get)

    resp = client.put(
        "/api/immich/config",
        json={"server_url": "https://immich.example.com/", "api_key": "abc123"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"connected": True, "server_url": "https://immich.example.com"}

    # Validated against /api/users/me (ping requires no auth, so it can't
    # verify the key) with the x-api-key header.
    assert captured["url"] == "https://immich.example.com/api/users/me"
    assert captured["headers"]["x-api-key"] == "abc123"

    tok = _stored_token(engine, uid)
    assert tok is not None
    assert tok.server_url == "https://immich.example.com"
    assert tok.api_key == "abc123"


def test_config_upserts_existing_row(env, monkeypatch):
    client, engine, uid = env
    _connect(engine, uid, server_url="https://old.example.com", api_key="old-key")

    monkeypatch.setattr(
        immich_module.requests, "get",
        lambda *a, **k: _FakeResponse(status_code=200, json_data={}),
    )
    resp = client.put(
        "/api/immich/config",
        json={"server_url": "https://new.example.com", "api_key": "new-key"},
    )
    assert resp.status_code == 200

    with Session(engine) as sess:
        rows = sess.exec(select(ImmichToken).where(ImmichToken.user_info_id == uid)).all()
    assert len(rows) == 1  # upsert, not a second row
    assert rows[0].server_url == "https://new.example.com"
    assert rows[0].api_key == "new-key"


def test_config_rejects_invalid_key(env, monkeypatch):
    client, engine, uid = env
    monkeypatch.setattr(
        immich_module.requests, "get",
        lambda *a, **k: _FakeResponse(status_code=401),
    )
    resp = client.put(
        "/api/immich/config",
        json={"server_url": "https://immich.example.com", "api_key": "bad-key"},
    )
    assert resp.status_code == 422
    assert "HTTP 401" in resp.json()["detail"]
    assert _stored_token(engine, uid) is None  # nothing saved on failure


def test_config_rejects_unreachable_server(env, monkeypatch):
    client, engine, uid = env

    def fake_get(*a, **k):
        raise requests.ConnectionError("no route to host")

    monkeypatch.setattr(immich_module.requests, "get", fake_get)
    resp = client.put(
        "/api/immich/config",
        json={"server_url": "https://unreachable.example.com", "api_key": "k"},
    )
    assert resp.status_code == 422
    assert "Could not reach Immich" in resp.json()["detail"]
    assert _stored_token(engine, uid) is None


# ── Disconnect ────────────────────────────────────────────────────────────────

def test_disconnect_clears_config(env):
    client, engine, uid = env
    _connect(engine, uid)
    resp = client.delete("/api/immich/disconnect")
    assert resp.status_code == 204
    assert _stored_token(engine, uid) is None
    assert client.get("/api/immich/status").json()["connected"] is False


def test_disconnect_is_noop_when_not_connected(env):
    client, _engine, _uid = env
    resp = client.delete("/api/immich/disconnect")
    assert resp.status_code == 204


# ── Search ────────────────────────────────────────────────────────────────────

def test_search_requires_connection(env):
    client, _engine, _uid = env
    resp = client.post(
        "/api/immich/search",
        json={"taken_after": "2024-01-01T00:00:00Z", "taken_before": "2024-01-02T00:00:00Z"},
    )
    assert resp.status_code == 400
    assert "not connected" in resp.json()["detail"].lower()


def test_search_proxies_params_and_reshapes_response(env, monkeypatch):
    client, engine, uid = env
    _connect(engine, uid, server_url="https://immich.example.com", api_key="secret-key")
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _FakeResponse(status_code=200, json_data={
            "assets": {
                "items": [
                    {
                        "id": "asset-1",
                        "fileCreatedAt": "2024-06-15T10:30:00.000Z",
                        "exifInfo": {"latitude": 48.85, "longitude": 2.35},
                    },
                    {
                        "id": "asset-2",
                        "fileCreatedAt": "2024-06-15T11:00:00.000Z",
                        "exifInfo": {},
                    },
                    {
                        # No exifInfo at all — must not blow up.
                        "id": "asset-3",
                        "fileCreatedAt": "2024-06-15T12:00:00.000Z",
                    },
                ],
                "total": 3, "count": 3, "nextPage": None, "facets": [],
            },
            "albums": {"items": [], "total": 0, "count": 0, "nextPage": None, "facets": []},
        })

    monkeypatch.setattr(immich_module.requests, "post", fake_post)

    resp = client.post(
        "/api/immich/search",
        json={"taken_after": "2024-06-15T00:00:00Z", "taken_before": "2024-06-15T23:59:59Z"},
    )
    assert resp.status_code == 200, resp.text

    # Params mapped to Immich's exact field names.
    assert captured["url"] == "https://immich.example.com/api/search/metadata"
    assert captured["headers"]["x-api-key"] == "secret-key"
    assert captured["json"]["takenAfter"] == "2024-06-15T00:00:00Z"
    assert captured["json"]["takenBefore"] == "2024-06-15T23:59:59Z"
    assert captured["json"]["withExif"] is True

    candidates = resp.json()["candidates"]
    assert len(candidates) == 3
    assert candidates[0] == {
        "id": "asset-1",
        "taken_at": "2024-06-15T10:30:00.000Z",
        "lat": 48.85,
        "lon": 2.35,
        "thumb_url": "/api/immich/assets/asset-1/thumbnail",
    }
    # No CORS-forbidden server info leaks into the candidate.
    assert "immich.example.com" not in str(candidates)
    assert "secret-key" not in str(candidates)
    # Missing/empty exif -> null lat/lon, not an error.
    assert candidates[1]["lat"] is None and candidates[1]["lon"] is None
    assert candidates[2]["lat"] is None and candidates[2]["lon"] is None


def test_search_upstream_failure_maps_to_502(env, monkeypatch):
    client, engine, uid = env
    _connect(engine, uid)
    monkeypatch.setattr(
        immich_module.requests, "post",
        lambda *a, **k: _FakeResponse(status_code=500),
    )
    resp = client.post(
        "/api/immich/search",
        json={"taken_after": "2024-01-01T00:00:00Z", "taken_before": "2024-01-02T00:00:00Z"},
    )
    assert resp.status_code == 502


# ── Asset proxying ────────────────────────────────────────────────────────────

def test_thumbnail_streams_bytes_through(env, monkeypatch):
    client, engine, uid = env
    _connect(engine, uid, server_url="https://immich.example.com", api_key="secret-key")
    captured = {}

    def fake_get(url, headers=None, timeout=None, stream=None):
        captured["url"] = url
        captured["headers"] = headers
        return _FakeResponse(status_code=200, headers={"content-type": "image/jpeg"},
                              content=b"\xff\xd8\xff\xfake-jpeg-bytes")

    monkeypatch.setattr(immich_module.requests, "get", fake_get)
    resp = client.get("/api/immich/assets/asset-1/thumbnail")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.content == b"\xff\xd8\xff\xfake-jpeg-bytes"
    assert captured["url"] == "https://immich.example.com/api/assets/asset-1/thumbnail"
    assert captured["headers"]["x-api-key"] == "secret-key"


def test_original_streams_bytes_through(env, monkeypatch):
    client, engine, uid = env
    _connect(engine, uid, server_url="https://immich.example.com", api_key="secret-key")

    def fake_get(url, headers=None, timeout=None, stream=None):
        return _FakeResponse(status_code=200, headers={"content-type": "image/heic"},
                              content=b"original-bytes")

    monkeypatch.setattr(immich_module.requests, "get", fake_get)
    resp = client.get("/api/immich/assets/asset-1/original")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/heic"
    assert resp.content == b"original-bytes"


def test_asset_not_found_maps_to_404(env, monkeypatch):
    client, engine, uid = env
    _connect(engine, uid)
    monkeypatch.setattr(
        immich_module.requests, "get",
        lambda *a, **k: _FakeResponse(status_code=404),
    )
    resp = client.get("/api/immich/assets/missing/thumbnail")
    assert resp.status_code == 404


def test_asset_proxy_requires_connection(env):
    client, _engine, _uid = env
    resp = client.get("/api/immich/assets/asset-1/thumbnail")
    assert resp.status_code == 400
    resp = client.get("/api/immich/assets/asset-1/original")
    assert resp.status_code == 400


# ── Per-user scoping ──────────────────────────────────────────────────────────

def test_search_and_status_are_scoped_to_calling_user(monkeypatch):
    """One user's Immich config must never be visible to another user."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_module, "engine", engine)
    SQLModel.metadata.create_all(engine)
    uid_a = _seed_user(engine)
    uid_b = _seed_second_user(engine)
    _connect(engine, uid_a, server_url="https://a.example.com", api_key="key-a")

    app = FastAPI()
    app.include_router(immich_router)

    app.dependency_overrides[get_current_user] = lambda: {"sub": str(uid_b), "email": "b@e.com"}
    client_b = TestClient(app)
    resp = client_b.get("/api/immich/status")
    assert resp.json() == {"connected": False, "server_url": None}
    # User B has no config, so search/asset routes must reject with "not connected",
    # never reach out using user A's stored server/key.
    resp = client_b.post(
        "/api/immich/search",
        json={"taken_after": "2024-01-01T00:00:00Z", "taken_before": "2024-01-02T00:00:00Z"},
    )
    assert resp.status_code == 400


# ── Auth required ─────────────────────────────────────────────────────────────

@pytest.fixture
def unauth_client(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_module, "engine", engine)
    SQLModel.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(immich_router)  # no dependency override — real auth applies
    return TestClient(app)


@pytest.mark.parametrize("method,path", [
    ("get", "/api/immich/status"),
    ("put", "/api/immich/config"),
    ("delete", "/api/immich/disconnect"),
    ("post", "/api/immich/search"),
    ("get", "/api/immich/assets/x/thumbnail"),
    ("get", "/api/immich/assets/x/original"),
])
def test_routes_require_auth(unauth_client, method, path):
    resp = getattr(unauth_client, method)(path)
    # HTTPBearer(auto_error=True) rejects a missing Authorization header with 403;
    # a present-but-invalid token would 401 via decode_token — either way, no route
    # here answers without a valid bearer token.
    assert resp.status_code in (401, 403)
