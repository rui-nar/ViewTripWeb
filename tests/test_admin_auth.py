"""Admin bootstrap + auth-wiring tests (issue #25).

Covers seeded admin creation/idempotency, forced password change through the
auth flow, ADMIN_EMAILS promotion, and the new token/me fields.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import models.db as db_module
from api.auth import router as auth_router
from src.admin.bootstrap import seed_admin
from models.user import LocalUser, UserInfo


@pytest.fixture
def engine(monkeypatch):
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_module, "engine", test_engine)
    SQLModel.metadata.create_all(test_engine)
    return test_engine


@pytest.fixture
def auth_client(engine):
    app = FastAPI()
    app.include_router(auth_router)
    return TestClient(app)


# ── 7. Seeded admin creation + idempotency ────────────────────────────────────

class TestSeedAdmin:
    def test_creates_admin_when_absent(self, engine):
        seed_admin()
        with Session(engine) as sess:
            local = sess.exec(
                select(LocalUser).where(LocalUser.username == "admin")
            ).first()
            assert local is not None
            assert local.verify("admin")
            assert local.password_change_required is True
            ui = sess.exec(
                select(UserInfo).where(UserInfo.local_auth_id == local.id)
            ).first()
            assert ui.is_admin is True
            assert ui.display_name == "admin"

    def test_idempotent(self, engine):
        seed_admin()
        seed_admin()
        seed_admin()
        with Session(engine) as sess:
            admins = sess.exec(
                select(LocalUser).where(LocalUser.username == "admin")
            ).all()
            assert len(admins) == 1

    def test_does_not_overwrite_changed_admin_password(self, engine):
        seed_admin()
        with Session(engine) as sess:
            local = sess.exec(
                select(LocalUser).where(LocalUser.username == "admin")
            ).first()
            local.password_hash = LocalUser.hash_password("newsecret")
            local.password_change_required = False
            sess.add(local)
            sess.commit()
        seed_admin()  # must be a no-op
        with Session(engine) as sess:
            local = sess.exec(
                select(LocalUser).where(LocalUser.username == "admin")
            ).first()
            assert local.verify("newsecret")
            assert local.password_change_required is False


# ── 8. Forced change through the auth flow ────────────────────────────────────

class TestForcedChange:
    def test_seeded_admin_login_requires_change(self, engine, auth_client):
        seed_admin()
        resp = auth_client.post("/api/auth/token",
                                json={"username": "admin", "password": "admin"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["user"]["password_change_required"] is True
        assert body["user"]["is_admin"] is True

    def test_change_password_clears_flag(self, engine, auth_client):
        seed_admin()
        login = auth_client.post("/api/auth/token",
                                 json={"username": "admin", "password": "admin"})
        token = login.json()["access_token"]

        resp = auth_client.post(
            "/api/auth/change-password",
            headers={"Authorization": f"Bearer {token}"},
            json={"current_password": "admin", "new_password": "brand-new-pw"},
        )
        assert resp.status_code == 200

        # Re-login: flag now cleared.
        relogin = auth_client.post(
            "/api/auth/token",
            json={"username": "admin", "password": "brand-new-pw"},
        )
        assert relogin.json()["user"]["password_change_required"] is False

    def test_change_password_response_itself_carries_cleared_flag(self, engine, auth_client):
        """Regression (issue #67): the client never re-logs in after a forced
        change — it re-fetches /me with the *old* token, which just echoes the
        old JWT's baked-in claim and never clears. change-password must return
        a fresh token/user reflecting the change directly, with no re-login."""
        seed_admin()
        login = auth_client.post("/api/auth/token",
                                 json={"username": "admin", "password": "admin"})
        old_token = login.json()["access_token"]

        resp = auth_client.post(
            "/api/auth/change-password",
            headers={"Authorization": f"Bearer {old_token}"},
            json={"current_password": "admin", "new_password": "brand-new-pw"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["user"]["password_change_required"] is False
        new_token = body["access_token"]
        assert new_token != old_token

        # The freshly issued token, used immediately, also reflects the change —
        # no re-login required for the router redirect to unblock.
        me = auth_client.get("/api/auth/me", headers={"Authorization": f"Bearer {new_token}"})
        assert me.json()["password_change_required"] is False


# ── 9. ADMIN_EMAILS promotion ─────────────────────────────────────────────────

class TestAdminEmailsPromotion:
    def test_register_promotes_matching_email_case_insensitive(
        self, engine, auth_client, monkeypatch
    ):
        monkeypatch.setenv("ADMIN_EMAILS", "Boss@Corp.IO, other@x.io")
        resp = auth_client.post("/api/auth/register", json={
            "username": "boss@corp.io", "password": "pw",
        })
        assert resp.status_code == 201
        assert resp.json()["user"]["is_admin"] is True

    def test_login_promotes_existing_user(self, engine, auth_client, monkeypatch):
        # Register a non-admin first (no ADMIN_EMAILS set).
        auth_client.post("/api/auth/register",
                         json={"username": "later@x.io", "password": "pw"})
        with Session(engine) as sess:
            ui = sess.exec(
                select(UserInfo).join(LocalUser,
                                      LocalUser.id == UserInfo.local_auth_id)
                .where(LocalUser.username == "later@x.io")
            ).first()
            assert ui.is_admin is False

        # Now promote via env and re-login.
        monkeypatch.setenv("ADMIN_EMAILS", "LATER@X.IO")
        resp = auth_client.post("/api/auth/token",
                                json={"username": "later@x.io", "password": "pw"})
        assert resp.json()["user"]["is_admin"] is True

    def test_non_matching_email_not_promoted(self, engine, auth_client, monkeypatch):
        monkeypatch.setenv("ADMIN_EMAILS", "someone@else.io")
        resp = auth_client.post("/api/auth/register",
                                json={"username": "nobody@x.io", "password": "pw"})
        assert resp.json()["user"]["is_admin"] is False


# ── 10. is_admin + password_change_required in token/me ───────────────────────

class TestTokenAndMeFields:
    def test_me_surfaces_admin_and_change_fields(self, engine, auth_client):
        seed_admin()
        login = auth_client.post("/api/auth/token",
                                 json={"username": "admin", "password": "admin"})
        token = login.json()["access_token"]
        me = auth_client.get("/api/auth/me",
                             headers={"Authorization": f"Bearer {token}"}).json()
        assert me["is_admin"] is True
        assert me["password_change_required"] is True

    def test_regular_user_me_has_false_flags(self, engine, auth_client):
        reg = auth_client.post("/api/auth/register",
                               json={"username": "plain@x.io", "password": "pw"})
        token = reg.json()["access_token"]
        me = auth_client.get("/api/auth/me",
                             headers={"Authorization": f"Bearer {token}"}).json()
        assert me["is_admin"] is False
        assert me["password_change_required"] is False
