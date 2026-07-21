"""Full account deletion — every owned row and file (issue #67 admin basket).

Covers the shared ``delete_user_and_data``/``purge_user_files`` helpers
against every table a user can own (directly or via a project), plus the two
endpoints that call them: the self-service ``DELETE /api/auth/me`` and the
admin-triggered ``DELETE /api/admin/users/{id}``.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import models.db as db_module
import src.admin.storage as storage_mod
from api.admin import router as admin_router
from api.auth import router as auth_router
from api.deps import get_current_user
from models.project_db import (
    DBActivity,
    DBEncounter,
    DBMemory,
    DBMemoryComment,
    DBMemoryLike,
    DBMemoryTranslation,
    DBPerson,
    DBPersonGroup,
    DBProject,
    DBProjectInvite,
    DBProjectItem,
    DBProjectMember,
    DBProjectSyncMeta,
    DBShareMemoryContent,
    DBShareVisit,
    DBStravaCache,
    DBDeviceKey,
    DBJournalEntry,
    DBRecoveryWrap,
)
from models.user import LocalUser, PolarstepsToken, StravaToken, UserInfo
from src.auth.account_deletion import delete_user_and_data, purge_user_files


@pytest.fixture
def engine(monkeypatch, tmp_path):
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_module, "engine", test_engine)
    monkeypatch.setattr(storage_mod, "_DATA_DIR", str(tmp_path))
    SQLModel.metadata.create_all(test_engine)
    return test_engine


def _mk_user(sess, *, display_name, email) -> UserInfo:
    local = LocalUser(username=email, password_hash=LocalUser.hash_password("pw"))
    sess.add(local)
    sess.commit()
    sess.refresh(local)
    ui = UserInfo(local_auth_id=local.id, display_name=display_name, email=email)
    sess.add(ui)
    sess.commit()
    sess.refresh(ui)
    return ui


def _seed_everything(sess, uid: int, *, other_uid: int) -> dict:
    """Create one row in every user/project-owned table, plus a row created by
    ``other_uid`` on ``uid``'s content (comment/like) to check cross-user cleanup."""
    proj = DBProject(user_info_id=uid, name="Trip")
    sess.add(proj)
    sess.commit()
    sess.refresh(proj)

    sess.add(DBProjectSyncMeta(project_id=proj.id))
    mem = DBMemory(project_id=proj.id, date="2025-01-01")
    sess.add(mem)
    sess.add(DBJournalEntry(project_id=proj.id, date="2025-01-01"))
    group = DBPersonGroup(project_id=proj.id, name="Friends")
    sess.add(group)
    sess.commit()
    sess.refresh(mem)
    sess.refresh(group)

    person = DBPerson(project_id=proj.id, name="Alex", group_id=group.id)
    sess.add(person)
    sess.commit()
    sess.refresh(person)

    sess.add(DBEncounter(project_id=proj.id, person_id=person.id, date="2025-01-01"))
    sess.add(DBProjectItem(project_id=proj.id, position=0, item_type="memory", memory_id=mem.id))
    sess.add(DBShareVisit(project_id=proj.id, token_type="full", visitor_type="registered",
                          user_info_id=other_uid))
    # This user visiting someone else's project (no project of their own here).
    sess.add(DBShareVisit(project_id=proj.id, token_type="full", visitor_type="registered",
                          user_info_id=uid))
    # Another user's comment/like on this user's memory, plus this user's own.
    sess.add(DBMemoryComment(memory_id=mem.id, user_info_id=other_uid, text="hi", created_at="t"))
    sess.add(DBMemoryComment(memory_id=mem.id, user_info_id=uid, text="mine", created_at="t"))
    sess.add(DBMemoryLike(memory_id=mem.id, user_info_id=other_uid, created_at="t"))
    sess.add(DBMemoryTranslation(memory_id=mem.id, lang_code="fr"))
    sess.add(DBShareMemoryContent(memory_id=mem.id, token_type="full"))
    sess.add(DBActivity(id=uid * 1000 + 1, user_info_id=uid, name="ride"))
    sess.add(DBStravaCache(user_info_id=uid))
    sess.add(StravaToken(user_info_id=uid))
    sess.add(PolarstepsToken(user_info_id=uid))
    sess.add(DBDeviceKey(user_info_id=uid, public_key="pk"))
    sess.add(DBRecoveryWrap(user_info_id=uid, method="recovery_key", wrapped_cmk="w", salt="s"))
    sess.commit()

    return {"project_id": proj.id, "memory_id": mem.id, "person_id": person.id,
            "group_id": group.id}


class TestDeleteUserAndData:
    def test_every_owned_table_is_emptied(self, engine, tmp_path):
        with Session(engine) as sess:
            target = _mk_user(sess, display_name="Target", email="t@x.io")
            other = _mk_user(sess, display_name="Other", email="o@x.io")
            uid, oid = target.id, other.id
            ids = _seed_everything(sess, uid, other_uid=oid)
            local_auth_id = target.local_auth_id

        user_dir = tmp_path / "users" / str(uid)
        user_dir.mkdir(parents=True)
        (user_dir / "photo.jpg").write_bytes(b"x")

        with Session(engine) as sess:
            delete_user_and_data(sess, uid)
        purge_user_files(uid)

        with Session(engine) as sess:
            assert sess.get(UserInfo, uid) is None
            assert sess.get(LocalUser, local_auth_id) is None
            assert sess.exec(select(DBProject).where(DBProject.id == ids["project_id"])).first() is None
            assert sess.exec(select(DBProjectSyncMeta)).first() is None
            assert sess.exec(select(DBMemory).where(DBMemory.id == ids["memory_id"])).first() is None
            assert sess.exec(select(DBJournalEntry)).first() is None
            assert sess.exec(select(DBPerson).where(DBPerson.id == ids["person_id"])).first() is None
            assert sess.exec(select(DBPersonGroup).where(DBPersonGroup.id == ids["group_id"])).first() is None
            assert sess.exec(select(DBEncounter)).first() is None
            assert sess.exec(select(DBProjectItem)).first() is None
            assert sess.exec(select(DBShareVisit)).first() is None  # both project- and visitor-scoped
            assert sess.exec(select(DBMemoryComment)).first() is None  # both this user's and other's
            assert sess.exec(select(DBMemoryLike)).first() is None
            assert sess.exec(select(DBMemoryTranslation)).first() is None
            assert sess.exec(select(DBShareMemoryContent)).first() is None
            assert sess.exec(select(DBActivity).where(DBActivity.user_info_id == uid)).first() is None
            assert sess.get(DBStravaCache, uid) is None
            assert sess.exec(select(StravaToken).where(StravaToken.user_info_id == uid)).first() is None
            assert sess.exec(select(PolarstepsToken).where(PolarstepsToken.user_info_id == uid)).first() is None
            assert sess.exec(select(DBDeviceKey).where(DBDeviceKey.user_info_id == uid)).first() is None
            assert sess.exec(select(DBRecoveryWrap).where(DBRecoveryWrap.user_info_id == uid)).first() is None
            # The other user (who commented/liked/visited) is untouched.
            assert sess.get(UserInfo, oid) is not None

        assert not user_dir.exists()

    def test_purge_user_files_is_noop_if_absent(self, engine):
        purge_user_files(999999)  # must not raise


def _seed_companionship(sess, owner_id: int, companion_id: int) -> dict:
    """Owner project with the companion as editor, plus the companion's
    footprint inside it: a journal entry, an imported activity, and the
    timeline items referencing both (issue #106)."""
    proj = DBProject(user_info_id=owner_id, name="Shared Trip")
    sess.add(proj)
    sess.commit()
    sess.refresh(proj)

    sess.add(DBProjectMember(project_id=proj.id, user_info_id=companion_id,
                             role="editor", invited_by=owner_id, created_at=0.0))
    sess.add(DBProjectInvite(project_id=proj.id, token="tok123",
                             created_by=owner_id, created_at=0.0))
    entry = DBJournalEntry(project_id=proj.id, user_info_id=companion_id,
                           date="2026-01-01")
    owner_entry = DBJournalEntry(project_id=proj.id, user_info_id=None,
                                 date="2026-01-02")  # legacy row = owner's
    act = DBActivity(id=companion_id * 1000 + 7, user_info_id=companion_id, name="ride")
    sess.add(entry); sess.add(owner_entry); sess.add(act)
    sess.commit()
    sess.refresh(entry); sess.refresh(owner_entry)

    sess.add(DBProjectItem(project_id=proj.id, position=0, item_type="journal",
                           journal_id=entry.id))
    sess.add(DBProjectItem(project_id=proj.id, position=1, item_type="journal",
                           journal_id=owner_entry.id))
    sess.add(DBProjectItem(project_id=proj.id, position=2, item_type="activity",
                           activity_id=act.id))
    sess.commit()

    return {"project_id": proj.id, "entry_id": entry.id,
            "owner_entry_id": owner_entry.id, "activity_id": act.id}


class TestCompanionCleanup:
    """Issue #106: deleting a user also removes their footprint in OTHER
    users' projects — membership, journal entries + items, activity items."""

    def test_deleting_companion_cleans_their_rows_in_owner_project(self, engine):
        with Session(engine) as sess:
            owner = _mk_user(sess, display_name="Owner", email="own@x.io")
            companion = _mk_user(sess, display_name="Comp", email="comp@x.io")
            oid, cid = owner.id, companion.id
            ids = _seed_companionship(sess, oid, cid)

        with Session(engine) as sess:
            delete_user_and_data(sess, cid)

        with Session(engine) as sess:
            assert sess.get(UserInfo, cid) is None
            assert sess.exec(select(DBProjectMember)).first() is None
            # The companion's journal entry, its item, and their activity item
            # are gone from the owner's project…
            assert sess.get(DBJournalEntry, ids["entry_id"]) is None
            assert sess.exec(select(DBProjectItem).where(
                DBProjectItem.journal_id == ids["entry_id"])).first() is None
            assert sess.exec(select(DBActivity).where(
                DBActivity.id == ids["activity_id"])).first() is None
            assert sess.exec(select(DBProjectItem).where(
                DBProjectItem.activity_id == ids["activity_id"])).first() is None
            # …while the owner's project, invite, and own (legacy) entry survive.
            assert sess.get(DBProject, ids["project_id"]) is not None
            assert sess.exec(select(DBProjectInvite)).first() is not None
            assert sess.get(DBJournalEntry, ids["owner_entry_id"]) is not None
            assert sess.exec(select(DBProjectItem).where(
                DBProjectItem.journal_id == ids["owner_entry_id"])).first() is not None

    def test_deleting_owner_removes_membership_and_invites(self, engine):
        with Session(engine) as sess:
            owner = _mk_user(sess, display_name="Owner", email="own@x.io")
            companion = _mk_user(sess, display_name="Comp", email="comp@x.io")
            oid, cid = owner.id, companion.id
            _seed_companionship(sess, oid, cid)

        with Session(engine) as sess:
            delete_user_and_data(sess, oid)

        with Session(engine) as sess:
            assert sess.get(UserInfo, oid) is None
            assert sess.exec(select(DBProject)).first() is None
            assert sess.exec(select(DBProjectMember)).first() is None
            assert sess.exec(select(DBProjectInvite)).first() is None
            assert sess.exec(select(DBJournalEntry)).first() is None
            assert sess.exec(select(DBProjectItem)).first() is None
            # The companion account itself is untouched.
            assert sess.get(UserInfo, cid) is not None


class TestSelfDeleteEndpoint:
    def test_delete_me_removes_account_and_data(self, engine):
        app = FastAPI()
        app.include_router(auth_router)
        client = TestClient(app)

        reg = client.post("/api/auth/register", json={
            "username": "jane", "password": "hunter2pass", "display_name": "Jane",
        })
        token = reg.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        uid = int(reg.json()["user"]["id"])

        with Session(engine) as sess:
            proj = DBProject(user_info_id=uid, name="Trip")
            sess.add(proj)
            sess.commit()
            sess.refresh(proj)
            sess.add(DBMemory(project_id=proj.id, date="2025-01-01"))
            sess.commit()

        resp = client.delete("/api/auth/me", headers=headers)
        assert resp.status_code == 200
        with Session(engine) as sess:
            assert sess.get(UserInfo, uid) is None
            assert sess.exec(select(DBProject).where(DBProject.user_info_id == uid)).first() is None
            assert sess.exec(select(DBMemory)).first() is None

    def test_delete_me_unknown_user_404(self, engine):
        app = FastAPI()
        app.dependency_overrides[get_current_user] = lambda: {
            "sub": "999999", "email": "x@x.io", "auth_provider": "local",
        }
        app.include_router(auth_router)
        client = TestClient(app)
        resp = client.delete("/api/auth/me")
        assert resp.status_code == 404


class TestAdminDeleteEndpoint:
    def _app(self, payload):
        app = FastAPI()
        app.dependency_overrides[get_current_user] = lambda: payload
        app.include_router(admin_router)
        return TestClient(app)

    def test_admin_delete_removes_data(self, engine):
        with Session(engine) as sess:
            admin = _mk_user(sess, display_name="admin", email="a@x.io")
            admin.is_admin = True
            sess.add(admin)
            sess.commit()
            target = _mk_user(sess, display_name="Target", email="t@x.io")
            aid, tid = admin.id, target.id
            _seed_everything(sess, tid, other_uid=aid)

        client = self._app({"sub": str(aid), "email": "a@x.io", "auth_provider": "local"})
        resp = client.delete(f"/api/admin/users/{tid}")
        assert resp.status_code == 200
        with Session(engine) as sess:
            assert sess.get(UserInfo, tid) is None
            assert sess.exec(select(DBProject)).first() is None
