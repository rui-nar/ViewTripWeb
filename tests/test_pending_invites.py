"""Pending invites addressed to an email (issue #110).

Before this, emailing someone sent them the project's shared link: there was no
record of who had been invited, no way to revoke one person's access without
cutting off everyone, and nothing tying the invite to the recipient. A pending
invite is targeted — its own token, only the named (and confirmed) address may
accept it, and it can be revoked on its own.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import models.db as db_module
from api.deps import get_current_user
from api.members import router as members_router, invites_router
from models.project_db import DBProject, DBProjectMember, DBProjectPendingInvite
from models.user import UserInfo
from src.utils.rate_limit import reset_rate_limits


class _FakeEmailService:
    def __init__(self):
        self.sent = []

    async def send(self, message):
        self.sent.append(message)


@pytest.fixture(autouse=True)
def _reset_limits():
    reset_rate_limits()
    yield
    reset_rate_limits()


@pytest.fixture
def fake_email(monkeypatch):
    fake = _FakeEmailService()
    monkeypatch.setattr("api.members.get_email_service", lambda: fake)
    return fake


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
        users = {
            # owner sends invites, so their own address must be confirmed.
            "owner": UserInfo(display_name="Owner", email="owner@e.com",
                              email_verified=True),
            # The person the invite is addressed to.
            "friend": UserInfo(display_name="Friend", email="friend@e.com",
                               email_verified=True),
            # Same address, but never confirmed it.
            "unconfirmed": UserInfo(display_name="Unconfirmed",
                                    email="friend@e.com", email_verified=False),
            # A different person entirely.
            "stranger": UserInfo(display_name="Stranger", email="stranger@e.com",
                                 email_verified=True),
            # Owner-equivalent rights but an unconfirmed address of their own.
            "unverified_owner": UserInfo(display_name="Unverified",
                                         email="unv@e.com", email_verified=False),
        }
        for u in users.values():
            sess.add(u)
        sess.commit()
        for u in users.values():
            sess.refresh(u)

        proj = DBProject(user_info_id=users["owner"].id, name="Trip")
        sess.add(proj)
        sess.commit()
        sess.refresh(proj)
        sess.add(DBProjectMember(project_id=proj.id,
                                 user_info_id=users["unverified_owner"].id,
                                 role="co-owner",
                                 invited_by=users["owner"].id))
        sess.add(DBProjectMember(project_id=proj.id,
                                 user_info_id=users["stranger"].id,
                                 role="viewer",
                                 invited_by=users["owner"].id))
        sess.commit()
        ids = {role: u.id for role, u in users.items()}
        ids["project"] = proj.id

    current = {"uid": ids["owner"]}
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(current["uid"])}
    app.include_router(members_router)
    app.include_router(invites_router)
    client = TestClient(app)

    def act_as(who: str):
        current["uid"] = ids[who]

    return client, engine, ids, act_as


def _invite(client, email="friend@e.com", role="editor"):
    return client.post("/api/projects/Trip/members/invite",
                       json={"role": role, "email": email})


# ── Creating ─────────────────────────────────────────────────────────────────

class TestCreate:
    def test_creates_a_pending_row(self, env, fake_email):
        client, engine, _, _ = env
        assert _invite(client).status_code == 200
        with Session(engine) as sess:
            row = sess.exec(select(DBProjectPendingInvite)).one()
        assert row.email == "friend@e.com"
        assert row.accepted_at is None

    def test_address_is_normalized(self, env, fake_email):
        """Stored lowercased, or it would never match the recipient's account."""
        client, engine, _, _ = env
        _invite(client, email="  Friend@E.COM ")
        with Session(engine) as sess:
            assert sess.exec(select(DBProjectPendingInvite)).one().email == "friend@e.com"

    def test_reinviting_resends_without_a_second_row(self, env, fake_email):
        client, engine, _, _ = env
        _invite(client)
        _invite(client)
        with Session(engine) as sess:
            assert len(sess.exec(select(DBProjectPendingInvite)).all()) == 1
        assert len(fake_email.sent) == 2

    def test_unverified_sender_refused(self, env, fake_email):
        """Otherwise an unconfirmed address can mail strangers from our domain."""
        client, _, ids, act_as = env
        act_as("unverified_owner")
        # Non-owner members address the trip via ?owner= (issue #106).
        r = client.post(
            f"/api/projects/Trip/members/invite?owner={ids['owner']}",
            json={"role": "editor", "email": "friend@e.com"})
        assert r.status_code == 403
        assert fake_email.sent == []

    def test_no_email_still_returns_the_shared_link(self, env, fake_email):
        """The copy-a-link flow is untouched by all of this."""
        client, engine, _, _ = env
        r = client.post("/api/projects/Trip/members/invite", json={"role": "editor"})
        assert r.status_code == 200
        assert r.json()["token"]
        with Session(engine) as sess:
            assert sess.exec(select(DBProjectPendingInvite)).all() == []
        assert fake_email.sent == []

    def test_response_does_not_leak_the_targeted_token(self, env, fake_email):
        """The caller asked to email someone, not to be handed that person's
        private join token."""
        client, engine, _, _ = env
        returned = _invite(client).json()["token"]
        with Session(engine) as sess:
            pending = sess.exec(select(DBProjectPendingInvite)).one()
        assert returned != pending.token

    def test_same_response_whether_or_not_the_address_has_an_account(
            self, env, fake_email):
        """Enumeration guard: the reply must not reveal who is registered."""
        client, _, _, _ = env
        known = _invite(client, email="friend@e.com")
        unknown = _invite(client, email="nobody@nowhere.com")
        assert known.status_code == unknown.status_code == 200
        assert known.json().keys() == unknown.json().keys()

    def test_capped_per_project(self, env, fake_email, monkeypatch):
        """Stops a runaway script or a typo'd loop filling the table for one
        trip. Rate limit raised out of the way so the cap is what bites."""
        import api.members as members_mod
        monkeypatch.setattr(members_mod, "_MAX_PENDING_PER_PROJECT", 3)
        monkeypatch.setattr(members_mod, "consume_rate_limit", lambda key: True)
        client, _, _, _ = env

        for i in range(3):
            assert _invite(client, email=f"p{i}@e.com").status_code == 200
        assert _invite(client, email="over@e.com").status_code == 409

        # Re-sending to someone already invited still works — it reuses the
        # existing row rather than adding to the count.
        assert _invite(client, email="p0@e.com").status_code == 200

    def test_rate_limited(self, env, fake_email):
        client, _, _, _ = env
        codes = [_invite(client, email=f"p{i}@e.com").status_code
                 for i in range(14)]
        assert 429 in codes, "an unbounded invite endpoint is a free mail relay"


# ── Owner-side listing and revoking ──────────────────────────────────────────

class TestOwnerList:
    def test_lists_pending(self, env, fake_email):
        client, _, _, _ = env
        _invite(client)
        rows = client.get("/api/projects/Trip/members/pending").json()["invites"]
        assert [r["email"] for r in rows] == ["friend@e.com"]

    def test_accepted_invites_drop_off_the_list(self, env, fake_email):
        client, engine, _, act_as = env
        _invite(client)
        with Session(engine) as sess:
            token = sess.exec(select(DBProjectPendingInvite)).one().token
        act_as("friend")
        client.post(f"/api/invites/{token}/accept")
        act_as("owner")
        assert client.get("/api/projects/Trip/members/pending").json()["invites"] == []

    def test_viewer_cannot_list(self, env, fake_email):
        client, _, ids, act_as = env
        _invite(client)
        act_as("stranger")  # a viewer on this project
        assert client.get(
            f"/api/projects/Trip/members/pending?owner={ids['owner']}"
        ).status_code == 403


class TestRevoke:
    def test_revoke_kills_the_token(self, env, fake_email):
        client, engine, _, act_as = env
        _invite(client)
        with Session(engine) as sess:
            row = sess.exec(select(DBProjectPendingInvite)).one()
            invite_id, token = row.id, row.token

        assert client.delete(
            f"/api/projects/Trip/members/pending/{invite_id}").status_code == 204

        act_as("friend")
        assert client.post(f"/api/invites/{token}/accept").status_code == 404

    def test_revoking_one_leaves_the_others(self, env, fake_email):
        """The whole point: the shared link can only be revoked for everyone."""
        client, engine, _, _ = env
        _invite(client, email="a@e.com")
        _invite(client, email="b@e.com")
        with Session(engine) as sess:
            first = sess.exec(select(DBProjectPendingInvite)
                              .where(DBProjectPendingInvite.email == "a@e.com")).one()
            first_id = first.id

        client.delete(f"/api/projects/Trip/members/pending/{first_id}")
        rows = client.get("/api/projects/Trip/members/pending").json()["invites"]
        assert [r["email"] for r in rows] == ["b@e.com"]

    def test_unknown_id_is_404(self, env):
        client, _, _, _ = env
        assert client.delete(
            "/api/projects/Trip/members/pending/9999").status_code == 404

    def test_viewer_cannot_revoke(self, env, fake_email):
        client, engine, ids, act_as = env
        _invite(client)
        with Session(engine) as sess:
            invite_id = sess.exec(select(DBProjectPendingInvite)).one().id
        act_as("stranger")
        assert client.delete(
            f"/api/projects/Trip/members/pending/{invite_id}"
            f"?owner={ids['owner']}").status_code == 403


# ── Recipient side ───────────────────────────────────────────────────────────

def _token_for(engine, email="friend@e.com"):
    with Session(engine) as sess:
        return sess.exec(select(DBProjectPendingInvite)
                         .where(DBProjectPendingInvite.email == email)).one().token


class TestAccept:
    def test_addressed_recipient_can_accept(self, env, fake_email):
        client, engine, ids, act_as = env
        _invite(client)
        token = _token_for(engine)
        act_as("friend")

        r = client.post(f"/api/invites/{token}/accept")
        assert r.status_code == 200
        with Session(engine) as sess:
            member = sess.exec(select(DBProjectMember).where(
                DBProjectMember.user_info_id == ids["friend"])).one()
        assert member.role == "editor"

    def test_accept_stamps_accepted_at(self, env, fake_email):
        client, engine, _, act_as = env
        _invite(client)
        token = _token_for(engine)
        act_as("friend")
        client.post(f"/api/invites/{token}/accept")
        with Session(engine) as sess:
            assert sess.exec(select(DBProjectPendingInvite)).one().accepted_at is not None

    def test_accept_is_idempotent(self, env, fake_email):
        client, engine, ids, act_as = env
        _invite(client)
        token = _token_for(engine)
        act_as("friend")
        client.post(f"/api/invites/{token}/accept")
        assert client.post(f"/api/invites/{token}/accept").status_code == 200
        with Session(engine) as sess:
            members = sess.exec(select(DBProjectMember).where(
                DBProjectMember.user_info_id == ids["friend"])).all()
        assert len(members) == 1

    def test_a_different_account_cannot_accept(self, env, fake_email):
        """A forwarded link must not hand membership to whoever received it."""
        client, engine, ids, act_as = env
        _invite(client)
        token = _token_for(engine)
        act_as("stranger")

        r = client.post(f"/api/invites/{token}/accept")
        assert r.status_code == 403
        assert "friend@e.com" in r.json()["detail"]

    def test_unverified_recipient_cannot_accept(self, env, fake_email):
        """Same address, unconfirmed — matching on a mere claim is how someone
        else's invite gets stolen."""
        client, engine, _, act_as = env
        _invite(client)
        token = _token_for(engine)
        act_as("unconfirmed")
        assert client.post(f"/api/invites/{token}/accept").status_code == 403

    def test_role_is_carried_from_the_invite(self, env, fake_email):
        client, engine, ids, act_as = env
        _invite(client, role="viewer")
        token = _token_for(engine)
        act_as("friend")
        client.post(f"/api/invites/{token}/accept")
        with Session(engine) as sess:
            member = sess.exec(select(DBProjectMember).where(
                DBProjectMember.user_info_id == ids["friend"])).one()
        assert member.role == "viewer"


class TestPreview:
    def test_names_the_address_it_was_sent_to(self, env, fake_email):
        client, engine, _, act_as = env
        _invite(client)
        token = _token_for(engine)
        act_as("friend")
        body = client.get(f"/api/invites/{token}").json()
        assert body["invited_email"] == "friend@e.com"
        assert body["project_name"] == "Trip"


class TestMyPendingInvites:
    def test_lists_invites_addressed_to_me(self, env, fake_email):
        client, _, _, act_as = env
        _invite(client)
        act_as("friend")
        rows = client.get("/api/invites/pending").json()["invites"]
        assert len(rows) == 1
        assert rows[0]["project_name"] == "Trip"
        assert rows[0]["owner_name"] == "Owner"

    def test_does_not_list_other_peoples_invites(self, env, fake_email):
        client, _, _, act_as = env
        _invite(client, email="friend@e.com")
        act_as("stranger")
        assert client.get("/api/invites/pending").json()["invites"] == []

    def test_empty_for_an_unverified_account(self, env, fake_email):
        client, _, _, act_as = env
        _invite(client)
        act_as("unconfirmed")
        assert client.get("/api/invites/pending").json()["invites"] == []

    def test_accepted_invites_are_not_listed(self, env, fake_email):
        client, engine, _, act_as = env
        _invite(client)
        token = _token_for(engine)
        act_as("friend")
        client.post(f"/api/invites/{token}/accept")
        assert client.get("/api/invites/pending").json()["invites"] == []


class TestAccountDeletionCleanup:
    def test_deleting_the_sender_removes_their_pending_invites(
            self, env, fake_email):
        """invited_by is a FK to userinfo — without explicit cleanup these
        outlive the sender as dangling rows."""
        from src.auth.account_deletion import delete_user_and_data

        client, engine, ids, _ = env
        _invite(client)
        with Session(engine) as sess:
            assert sess.exec(select(DBProjectPendingInvite)).all() != []
            delete_user_and_data(sess, ids["owner"])
            assert sess.exec(select(DBProjectPendingInvite)).all() == []


class TestDecline:
    def test_decline_removes_the_invite(self, env, fake_email):
        client, engine, _, act_as = env
        _invite(client)
        token = _token_for(engine)
        act_as("friend")

        assert client.delete(f"/api/invites/{token}").status_code == 204
        with Session(engine) as sess:
            assert sess.exec(select(DBProjectPendingInvite)).all() == []

    def test_declined_invite_cannot_then_be_accepted(self, env, fake_email):
        client, engine, _, act_as = env
        _invite(client)
        token = _token_for(engine)
        act_as("friend")
        client.delete(f"/api/invites/{token}")
        assert client.post(f"/api/invites/{token}/accept").status_code == 404

    def test_someone_else_cannot_decline_on_my_behalf(self, env, fake_email):
        client, engine, _, act_as = env
        _invite(client)
        token = _token_for(engine)
        act_as("stranger")
        assert client.delete(f"/api/invites/{token}").status_code == 404

    def test_shared_link_cannot_be_declined(self, env):
        """It has no per-person state, and deleting it would revoke everyone's
        access on behalf of an owner who never asked."""
        client, _, _, act_as = env
        token = client.post("/api/projects/Trip/members/invite",
                            json={"role": "editor"}).json()["token"]
        act_as("friend")
        assert client.delete(f"/api/invites/{token}").status_code == 409
