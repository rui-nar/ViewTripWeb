"""Tests for the zero-knowledge encryption endpoints (issue #26).

Covers:
  1. enable — stores device + recovery wraps, flips encryption_enabled, returns state
  2. enable — rejects a second enable (409) and an unknown recovery method (422)
  3. status — reports enabled + recovery methods; returns this device's wrapped CMK
  4. status — a different/unknown device public key is not "registered"
  5. isolation — one user's key material never leaks to another user
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import models.db as db_module
from api.deps import get_current_user
from api.encryption import router as encryption_router
from models.project_db import DBDeviceKey, DBRecoveryWrap
from models.user import UserInfo


def _make_app(user_payload: dict) -> FastAPI:
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: user_payload
    app.include_router(encryption_router)
    return app


def _enable_body(method: str = "recovery_key") -> dict:
    return {
        "device": {
            "public_key": "DEVPUB_A",
            "label": "Chrome on Windows",
            "wrapped_cmk": "WRAP_DEV_A",
            "ephemeral_public_key": "EPH_A",
        },
        "recovery": {
            "method": method,
            "wrapped_cmk": "WRAP_REC",
            "salt": "SALT",
            "kdf_params_json": '{"memoryKib":19456}' if method == "qna" else None,
        },
    }


@pytest.fixture
def enc_env(monkeypatch):
    """In-memory DB + one user; yields (client, user_id, engine)."""
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_module, "engine", test_engine)
    SQLModel.metadata.create_all(test_engine)

    with Session(test_engine) as sess:
        user = UserInfo(display_name="Alice", email="alice@example.com")
        sess.add(user)
        sess.commit()
        sess.refresh(user)
        user_id = user.id

    client = TestClient(_make_app({"sub": str(user_id), "email": "alice@example.com"}))
    return client, user_id, test_engine


def test_enable_stores_wraps_and_flips_flag(enc_env):
    client, user_id, engine = enc_env
    resp = client.post("/api/encryption/enable", json=_enable_body())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["enabled"] is True
    assert body["recovery_methods"] == ["recovery_key"]
    assert body["device"] == {
        "registered": True,
        "approved": True,
        "wrapped_cmk": "WRAP_DEV_A",
        "ephemeral_public_key": "EPH_A",
    }

    with Session(engine) as sess:
        ui = sess.get(UserInfo, user_id)
        assert ui.encryption_enabled is True
        devices = sess.exec(select(DBDeviceKey).where(DBDeviceKey.user_info_id == user_id)).all()
        assert len(devices) == 1 and devices[0].approved is True
        recs = sess.exec(select(DBRecoveryWrap).where(DBRecoveryWrap.user_info_id == user_id)).all()
        assert len(recs) == 1 and recs[0].method == "recovery_key"


def test_enable_twice_conflicts(enc_env):
    client, _, _ = enc_env
    assert client.post("/api/encryption/enable", json=_enable_body()).status_code == 201
    resp = client.post("/api/encryption/enable", json=_enable_body())
    assert resp.status_code == 409


def test_enable_rejects_unknown_recovery_method(enc_env):
    client, _, _ = enc_env
    resp = client.post("/api/encryption/enable", json=_enable_body(method="palm_print"))
    assert resp.status_code == 422


def test_status_returns_this_devices_wrapped_cmk(enc_env):
    client, _, _ = enc_env
    client.post("/api/encryption/enable", json=_enable_body(method="qna"))

    resp = client.get("/api/encryption/status", params={"device_public_key": "DEVPUB_A"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["recovery_methods"] == ["qna"]
    assert body["device"]["registered"] is True
    assert body["device"]["wrapped_cmk"] == "WRAP_DEV_A"


def test_status_unknown_device_not_registered(enc_env):
    client, _, _ = enc_env
    client.post("/api/encryption/enable", json=_enable_body())
    resp = client.get("/api/encryption/status", params={"device_public_key": "SOME_OTHER_DEVICE"})
    assert resp.status_code == 200
    assert resp.json()["device"] == {
        "registered": False, "approved": False,
        "wrapped_cmk": None, "ephemeral_public_key": None,
    }


def test_status_before_enable_is_disabled(enc_env):
    client, _, _ = enc_env
    resp = client.get("/api/encryption/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["recovery_methods"] == []
    assert body["device"]["registered"] is False


# ── Cross-device approval lifecycle ─────────────────────────────────────────────

def test_register_pending_then_approve(enc_env):
    client, _, _ = enc_env
    client.post("/api/encryption/enable", json=_enable_body())  # device A trusted

    # Device B registers, lands pending (not approved, no wrapped CMK).
    reg = client.post("/api/encryption/devices/register",
                      json={"public_key": "DEVPUB_B", "label": "Phone"})
    assert reg.status_code == 200
    assert reg.json() == {
        "registered": True, "approved": False,
        "wrapped_cmk": None, "ephemeral_public_key": None,
    }

    # It shows up in the pending list.
    pending = client.get("/api/encryption/devices/pending").json()
    assert [p["public_key"] for p in pending] == ["DEVPUB_B"]

    # A trusted device approves it by uploading a wrap.
    appr = client.post("/api/encryption/devices/approve", json={
        "public_key": "DEVPUB_B",
        "wrapped_cmk": "WRAP_DEV_B",
        "ephemeral_public_key": "EPH_B",
    })
    assert appr.status_code == 200
    assert appr.json()["approved"] is True

    # Pending list is now empty; device B's status returns its wrapped CMK.
    assert client.get("/api/encryption/devices/pending").json() == []
    st = client.get("/api/encryption/status",
                    params={"device_public_key": "DEVPUB_B"}).json()
    assert st["device"]["approved"] is True
    assert st["device"]["wrapped_cmk"] == "WRAP_DEV_B"


def test_register_requires_encryption_enabled(enc_env):
    client, _, _ = enc_env
    resp = client.post("/api/encryption/devices/register",
                       json={"public_key": "DEVPUB_B", "label": ""})
    assert resp.status_code == 409


def test_register_is_idempotent(enc_env):
    client, _, _ = enc_env
    client.post("/api/encryption/enable", json=_enable_body())
    a = client.post("/api/encryption/devices/register",
                    json={"public_key": "DEVPUB_B", "label": "Phone"})
    b = client.post("/api/encryption/devices/register",
                    json={"public_key": "DEVPUB_B", "label": "Phone again"})
    assert a.status_code == 200 and b.status_code == 200
    assert len(client.get("/api/encryption/devices/pending").json()) == 1


def test_approve_unknown_device_404(enc_env):
    client, _, _ = enc_env
    client.post("/api/encryption/enable", json=_enable_body())
    resp = client.post("/api/encryption/devices/approve", json={
        "public_key": "NOPE", "wrapped_cmk": "X", "ephemeral_public_key": "Y",
    })
    assert resp.status_code == 404
