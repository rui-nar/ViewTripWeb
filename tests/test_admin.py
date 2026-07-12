"""Tests for the admin dashboard API (issue #25).

Covers gating, metrics, per-user isolation, recent-signup windowing, seeded
admin + forced change, ADMIN_EMAILS promotion, token/me fields, user search,
and the tier-gated password reset (including the key E2EE-safety block).
"""
from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import api.admin as admin_mod
import models.db as db_module
import src.admin.storage as storage_mod
from api.admin import router as admin_router
from api.deps import get_current_user
from models.project_db import DBActivity, DBMemory, DBProject
from models.user import LocalUser, UserInfo


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def engine(monkeypatch, tmp_path):
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_module, "engine", test_engine)
    monkeypatch.setattr(storage_mod, "_DATA_DIR", str(tmp_path))
    storage_mod.refresh_storage_cache()
    SQLModel.metadata.create_all(test_engine)
    yield test_engine
    storage_mod.refresh_storage_cache()


def _admin_app(engine, user_payload: dict) -> FastAPI:
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: user_payload
    app.include_router(admin_router)
    return app


def _mk_user(sess, *, display_name, email, is_admin=False, provider="local",
             created_at=None, username=None):
    local = LocalUser(
        username=username or email or display_name,
        password_hash=LocalUser.hash_password("pw"),
    )
    sess.add(local)
    sess.commit()
    sess.refresh(local)
    ui = UserInfo(
        local_auth_id=local.id,
        display_name=display_name,
        email=email,
        auth_provider=provider,
        is_admin=is_admin,
    )
    if created_at is not None:
        ui.created_at = created_at
    sess.add(ui)
    sess.commit()
    sess.refresh(ui)
    return ui, local


@pytest.fixture
def admin_client(engine):
    with Session(engine) as sess:
        admin_ui, _ = _mk_user(sess, display_name="admin", email="admin@x.io",
                               is_admin=True)
        admin_id = admin_ui.id
    payload = {"sub": str(admin_id), "email": "admin@x.io", "auth_provider": "local"}
    return TestClient(_admin_app(engine, payload)), admin_id


# ── 1. Gating ─────────────────────────────────────────────────────────────────

_ADMIN_ROUTES = [
    ("get", "/api/admin/stats"),
    ("get", "/api/admin/storage/refresh"),
    ("get", "/api/admin/users/search?q=a"),
    ("post", "/api/admin/users/1/reset-password"),
    ("post", "/api/admin/users/1/set-admin"),
    ("delete", "/api/admin/users/999999"),
]


class TestGating:
    def _call(self, client, method, path):
        if method == "get":
            return client.get(path)
        if method == "delete":
            return client.delete(path)
        body = {"is_admin": True} if "set-admin" in path else {}
        return client.post(path, json=body)

    @pytest.mark.parametrize("method,path", _ADMIN_ROUTES)
    def test_admin_reaches_route(self, admin_client, engine, method, path):
        client, _ = admin_client
        # Ensure the reset target exists so it's a 200/valid path, not a 404.
        with Session(engine) as sess:
            _mk_user(sess, display_name="target", email="t@x.io")
        resp = self._call(client, method, path)
        assert resp.status_code != 403 and resp.status_code != 401

    @pytest.mark.parametrize("method,path", _ADMIN_ROUTES)
    def test_non_admin_gets_403(self, engine, method, path):
        with Session(engine) as sess:
            ui, _ = _mk_user(sess, display_name="joe", email="joe@x.io")
            uid = ui.id
        payload = {"sub": str(uid), "email": "joe@x.io", "auth_provider": "local"}
        client = TestClient(_admin_app(engine, payload))
        resp = self._call(client, method, path)
        assert resp.status_code == 403

    @pytest.mark.parametrize("method,path", _ADMIN_ROUTES)
    def test_unauthenticated_gets_401(self, engine, method, path):
        # No dependency override → real HTTPBearer runs and rejects.
        app = FastAPI()
        app.include_router(admin_router)
        client = TestClient(app)
        resp = self._call(client, method, path)
        assert resp.status_code in (401, 403)  # missing bearer → 403 from HTTPBearer

    def test_unauthenticated_stats_is_401_or_403(self, engine):
        app = FastAPI()
        app.include_router(admin_router)
        resp = TestClient(app).get("/api/admin/stats")
        # FastAPI HTTPBearer returns 403 when the header is absent.
        assert resp.status_code in (401, 403)


# ── 2 & 3. Totals + per-user breakdown + isolation ────────────────────────────

class TestStats:
    def _seed_two_users(self, engine, tmp_path_bytes=(0, 0)):
        with Session(engine) as sess:
            a, _ = _mk_user(sess, display_name="Alice", email="a@x.io", is_admin=True)
            b, _ = _mk_user(sess, display_name="Bob", email="b@x.io")
            aid, bid = a.id, b.id

            pa = DBProject(user_info_id=aid, name="A1")
            pa2 = DBProject(user_info_id=aid, name="A2")
            pb = DBProject(user_info_id=bid, name="B1")
            sess.add_all([pa, pa2, pb])
            sess.commit()
            sess.refresh(pa)
            sess.refresh(pb)

            sess.add(DBActivity(id=1, user_info_id=aid, name="ride"))
            sess.add(DBActivity(id=2, user_info_id=aid, name="run"))
            sess.add(DBActivity(id=3, user_info_id=bid, name="hike"))

            sess.add(DBMemory(project_id=pa.id, date="2025-01-01"))
            sess.add(DBMemory(project_id=pa.id, date="2025-01-02"))
            sess.add(DBMemory(project_id=pb.id, date="2025-01-03"))
            sess.commit()
        return aid, bid

    def test_totals(self, engine):
        aid, bid = self._seed_two_users(engine)
        payload = {"sub": str(aid), "email": "a@x.io", "auth_provider": "local"}
        client = TestClient(_admin_app(engine, payload))
        totals = client.get("/api/admin/stats").json()["totals"]
        assert totals["users"] == 2
        assert totals["projects"] == 3
        assert totals["activities"] == 3
        assert totals["memories"] == 3

    def test_per_user_breakdown_isolated(self, engine):
        aid, bid = self._seed_two_users(engine)
        payload = {"sub": str(aid), "email": "a@x.io", "auth_provider": "local"}
        client = TestClient(_admin_app(engine, payload))
        rows = {r["id"]: r for r in client.get("/api/admin/stats").json()["users"]}

        assert rows[aid]["project_count"] == 2
        assert rows[aid]["activity_count"] == 2
        assert rows[aid]["memory_count"] == 2
        # Bob's data never leaks into Alice's row.
        assert rows[bid]["project_count"] == 1
        assert rows[bid]["activity_count"] == 1
        assert rows[bid]["memory_count"] == 1
        # Every row carries an encryption tier (stub → none).
        assert all(r["encryption_tier"] == "none" for r in rows.values())

    def test_no_content_fields_returned(self, engine):
        aid, _ = self._seed_two_users(engine)
        payload = {"sub": str(aid), "email": "a@x.io", "auth_provider": "local"}
        client = TestClient(_admin_app(engine, payload))
        body = client.get("/api/admin/stats").json()
        blob = str(body).lower()
        # No memory/journal text keys.
        for row in body["users"]:
            assert "description" not in row
            assert "photos" not in row
        assert "description" not in blob

    def test_storage_reflected_in_totals(self, engine, tmp_path):
        with Session(engine) as sess:
            a, _ = _mk_user(sess, display_name="Alice", email="a@x.io", is_admin=True)
            aid = a.id
        d = tmp_path / "users" / str(aid)
        d.mkdir(parents=True)
        (d / "blob").write_bytes(b"z" * 128)
        storage_mod.refresh_storage_cache()

        payload = {"sub": str(aid), "email": "a@x.io", "auth_provider": "local"}
        client = TestClient(_admin_app(engine, payload))
        body = client.get("/api/admin/stats").json()
        assert body["totals"]["storage_bytes"] == 128
        row = next(r for r in body["users"] if r["id"] == aid)
        assert row["storage_bytes"] == 128


# ── 4. Recent sign-ups windowing ──────────────────────────────────────────────

class TestRecentSignups:
    def test_windowing(self, engine):
        now = time.time()
        with Session(engine) as sess:
            _mk_user(sess, display_name="admin", email="admin@x.io", is_admin=True,
                     created_at=now)  # recent
            _mk_user(sess, display_name="fresh", email="f@x.io", created_at=now - 3600)
            _mk_user(sess, display_name="old", email="o@x.io",
                     created_at=now - 30 * 24 * 3600)  # 30 days ago
            admin = sess.exec(select(UserInfo).where(UserInfo.email == "admin@x.io")).first()
            aid = admin.id
        payload = {"sub": str(aid), "email": "admin@x.io", "auth_provider": "local"}
        client = TestClient(_admin_app(engine, payload))
        totals = client.get("/api/admin/stats").json()["totals"]
        # admin + fresh are within 7 days; old is not.
        assert totals["recent_signups_7d"] == 2


# ── 12. User search ───────────────────────────────────────────────────────────

class TestSearch:
    @pytest.fixture
    def client(self, engine):
        with Session(engine) as sess:
            admin, _ = _mk_user(sess, display_name="admin", email="admin@x.io",
                                is_admin=True, username="admin")
            _mk_user(sess, display_name="Charlie Brown", email="charlie@peanuts.io",
                     username="charlie")
            _mk_user(sess, display_name="Zed", email="zed@other.io", username="zeddy")
            aid = admin.id
        payload = {"sub": str(aid), "email": "admin@x.io", "auth_provider": "local"}
        return TestClient(_admin_app(engine, payload))

    def test_matches_email_case_insensitive(self, client):
        res = client.get("/api/admin/users/search?q=PEANUTS").json()
        assert any(r["email"] == "charlie@peanuts.io" for r in res)

    def test_matches_display_name(self, client):
        res = client.get("/api/admin/users/search?q=brown").json()
        assert any(r["display_name"] == "Charlie Brown" for r in res)

    def test_matches_username(self, client):
        res = client.get("/api/admin/users/search?q=zeddy").json()
        assert any(r["username"] == "zeddy" for r in res)

    def test_excludes_non_matches(self, client):
        res = client.get("/api/admin/users/search?q=charlie").json()
        assert all(r["display_name"] != "Zed" for r in res)

    def test_respects_limit(self, client):
        res = client.get("/api/admin/users/search?q=@&limit=1").json()
        assert len(res) == 1

    def test_empty_query_returns_empty(self, client):
        assert client.get("/api/admin/users/search?q=").json() == []

    def test_results_carry_tier(self, client):
        res = client.get("/api/admin/users/search?q=charlie").json()
        assert res[0]["encryption_tier"] == "none"


# ── 13/14/15. Password reset ──────────────────────────────────────────────────

class TestResetPassword:
    @pytest.fixture
    def ctx(self, engine):
        with Session(engine) as sess:
            admin, _ = _mk_user(sess, display_name="admin", email="admin@x.io",
                                is_admin=True)
            target, target_local = _mk_user(sess, display_name="Target",
                                            email="target@x.io", username="target@x.io")
            google, _ = _mk_user(sess, display_name="Goog", email="g@x.io",
                                 provider="google")
            # Google shadow account: empty password hash.
            g_local = sess.get(LocalUser, google.local_auth_id)
            g_local.password_hash = b""
            sess.add(g_local)
            sess.commit()
            aid, tid, gid = admin.id, target.id, google.id
        payload = {"sub": str(aid), "email": "admin@x.io", "auth_provider": "local"}
        return TestClient(_admin_app(engine, payload)), engine, tid, gid

    def test_reset_none_tier_sets_temp_and_forces_change(self, ctx):
        client, engine, tid, _ = ctx
        resp = client.post(f"/api/admin/users/{tid}/reset-password", json={})
        assert resp.status_code == 200
        temp = resp.json()["temp_password"]
        assert temp

        with Session(engine) as sess:
            ui = sess.get(UserInfo, tid)
            local = sess.get(LocalUser, ui.local_auth_id)
            assert local.password_change_required is True
            assert local.verify(temp)  # new hash matches the returned temp password

    def test_reset_low_tier_allowed(self, ctx, monkeypatch):
        client, engine, tid, _ = ctx
        monkeypatch.setattr(admin_mod, "user_encryption_tier", lambda s, u: "low")
        resp = client.post(f"/api/admin/users/{tid}/reset-password", json={})
        assert resp.status_code == 200

    def test_reset_medium_blocked_409(self, ctx, monkeypatch):
        client, engine, tid, _ = ctx
        monkeypatch.setattr(admin_mod, "user_encryption_tier", lambda s, u: "medium")
        resp = client.post(f"/api/admin/users/{tid}/reset-password", json={})
        assert resp.status_code == 409
        with Session(engine) as sess:  # password untouched
            ui = sess.get(UserInfo, tid)
            local = sess.get(LocalUser, ui.local_auth_id)
            assert local.password_change_required is False

    def test_reset_high_blocked_409(self, ctx, monkeypatch):
        client, _, tid, _ = ctx
        monkeypatch.setattr(admin_mod, "user_encryption_tier", lambda s, u: "high")
        resp = client.post(f"/api/admin/users/{tid}/reset-password", json={})
        assert resp.status_code == 409

    def test_reset_google_user_409(self, ctx):
        client, _, _, gid = ctx
        resp = client.post(f"/api/admin/users/{gid}/reset-password", json={})
        assert resp.status_code == 409

    def test_reset_unknown_user_404(self, ctx):
        client, *_ = ctx
        resp = client.post("/api/admin/users/999999/reset-password", json={})
        assert resp.status_code == 404


# ── 16. Grant / revoke admin ──────────────────────────────────────────────────

class TestSetAdmin:
    @pytest.fixture
    def ctx(self, engine):
        with Session(engine) as sess:
            admin, _ = _mk_user(sess, display_name="admin", email="admin@x.io",
                                is_admin=True)
            other_admin, _ = _mk_user(sess, display_name="Other admin",
                                       email="other-admin@x.io", is_admin=True)
            plain, _ = _mk_user(sess, display_name="Plain", email="plain@x.io")
            aid, oid, pid = admin.id, other_admin.id, plain.id
        payload = {"sub": str(aid), "email": "admin@x.io", "auth_provider": "local"}
        return TestClient(_admin_app(engine, payload)), engine, aid, oid, pid

    def test_grant_admin(self, ctx):
        client, engine, _, _, pid = ctx
        resp = client.post(f"/api/admin/users/{pid}/set-admin", json={"is_admin": True})
        assert resp.status_code == 200
        with Session(engine) as sess:
            assert sess.get(UserInfo, pid).is_admin is True

    def test_revoke_other_admin(self, ctx):
        client, engine, _, oid, _ = ctx
        resp = client.post(f"/api/admin/users/{oid}/set-admin", json={"is_admin": False})
        assert resp.status_code == 200
        with Session(engine) as sess:
            assert sess.get(UserInfo, oid).is_admin is False

    def test_cannot_revoke_own_admin(self, ctx):
        client, engine, aid, _, _ = ctx
        resp = client.post(f"/api/admin/users/{aid}/set-admin", json={"is_admin": False})
        assert resp.status_code == 409
        with Session(engine) as sess:
            assert sess.get(UserInfo, aid).is_admin is True

    def test_granting_own_admin_is_a_noop_not_blocked(self, ctx):
        client, _, aid, _, _ = ctx
        resp = client.post(f"/api/admin/users/{aid}/set-admin", json={"is_admin": True})
        assert resp.status_code == 200

    def test_set_admin_unknown_user_404(self, ctx):
        client, *_ = ctx
        resp = client.post("/api/admin/users/999999/set-admin", json={"is_admin": True})
        assert resp.status_code == 404

    def test_search_results_carry_is_admin(self, ctx):
        client, _, aid, oid, pid = ctx
        res = client.get("/api/admin/users/search?q=plain").json()
        assert res[0]["is_admin"] is False
        res = client.get("/api/admin/users/search?q=other-admin").json()
        assert res[0]["is_admin"] is True


# ── 17. Delete user ────────────────────────────────────────────────────────────

class TestDeleteUser:
    @pytest.fixture
    def ctx(self, engine):
        with Session(engine) as sess:
            admin, _ = _mk_user(sess, display_name="admin", email="admin@x.io",
                                is_admin=True)
            target, _ = _mk_user(sess, display_name="Target", email="target@x.io")
            tid = target.id
            sess.add(DBProject(user_info_id=tid, name="Trip"))
            sess.commit()
            proj = sess.exec(select(DBProject).where(DBProject.user_info_id == tid)).first()
            sess.add(DBMemory(project_id=proj.id, date="2025-01-01"))
            sess.add(DBActivity(id=42, user_info_id=tid, name="ride"))
            sess.commit()
            aid = admin.id
        payload = {"sub": str(aid), "email": "admin@x.io", "auth_provider": "local"}
        return TestClient(_admin_app(engine, payload)), engine, aid, tid

    def test_delete_removes_user_and_owned_data(self, ctx):
        client, engine, _, tid = ctx
        resp = client.delete(f"/api/admin/users/{tid}")
        assert resp.status_code == 200
        with Session(engine) as sess:
            assert sess.get(UserInfo, tid) is None
            assert sess.exec(select(DBProject).where(DBProject.user_info_id == tid)).first() is None
            assert sess.exec(select(DBMemory)).first() is None  # target was the only owner
            assert sess.exec(select(DBActivity).where(DBActivity.user_info_id == tid)).first() is None

    def test_delete_purges_storage(self, ctx, tmp_path):
        client, _, _, tid = ctx
        d = tmp_path / "users" / str(tid)
        d.mkdir(parents=True)
        (d / "photo.jpg").write_bytes(b"x")
        client.delete(f"/api/admin/users/{tid}")
        assert not d.exists()

    def test_cannot_delete_self(self, ctx):
        client, engine, aid, _ = ctx
        resp = client.delete(f"/api/admin/users/{aid}")
        assert resp.status_code == 409
        with Session(engine) as sess:
            assert sess.get(UserInfo, aid) is not None

    def test_delete_unknown_user_404(self, ctx):
        client, *_ = ctx
        resp = client.delete("/api/admin/users/999999")
        assert resp.status_code == 404
