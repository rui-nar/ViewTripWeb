"""API tests for companion roles — viewer and co-owner (issue #109).

Covers the invite-role flow (creation, the co-owner-invite cap, accept
granting the invite's role) and the four-tier access matrix (viewer /
editor / co-owner / owner) on representative routes. The editor/owner
baseline is already covered by test_project_members.py; this file focuses
on what issue #109 adds.
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
from api.people import router as people_router
from api.projects import router as projects_router
from models.project_db import DBProject, DBProjectMember
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
        users = {
            role: UserInfo(display_name=role.capitalize(), email=f"{role}@e.com")
            for role in ("owner", "coowner", "editor", "viewer", "stranger")
        }
        for u in users.values():
            sess.add(u)
        sess.commit()
        for u in users.values():
            sess.refresh(u)
        proj = DBProject(user_info_id=users["owner"].id, name="Trip")
        sess.add(proj); sess.commit(); sess.refresh(proj)
        ids = {role: u.id for role, u in users.items()}
        ids["project"] = proj.id

    current = {"uid": ids["owner"]}
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(current["uid"])}
    app.include_router(members_router)
    app.include_router(invites_router)
    app.include_router(projects_router)
    app.include_router(people_router)

    client = TestClient(app)

    def act_as(who: str):
        current["uid"] = ids[who]

    return client, engine, ids, act_as


def _invite(client, act_as, role: str | None = None) -> str:
    """Owner creates an invite with the given role, returns the token.

    Revokes any existing invite first: creation is idempotent (returns the
    existing token, ignoring the requested role) — callers that need a
    specific role must not silently inherit a stale one.
    """
    act_as("owner")
    client.delete("/api/projects/Trip/members/invite")
    body = {"role": role} if role else None
    r = client.post("/api/projects/Trip/members/invite", json=body)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _join(client, act_as, who: str, role: str | None = None) -> None:
    token = _invite(client, act_as, role)
    act_as(who)
    r = client.post(f"/api/invites/{token}/accept")
    assert r.status_code == 200, r.text


# ── Invite role flow ───────────────────────────────────────────────────────────

def test_invite_defaults_to_editor_role(env):
    client, _, _, act_as = env
    act_as("owner")
    r = client.post("/api/projects/Trip/members/invite")
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "editor"


def test_invite_with_explicit_role_and_accept_grants_it(env):
    client, engine, ids, act_as = env
    _join(client, act_as, "viewer", role="viewer")
    with Session(engine) as sess:
        m = sess.exec(select(DBProjectMember)).first()
        assert m.user_info_id == ids["viewer"]
        assert m.role == "viewer"


def test_invite_preview_shows_role(env):
    client, _, _, act_as = env
    token = _invite(client, act_as, role="viewer")
    act_as("stranger")
    r = client.get(f"/api/invites/{token}")
    assert r.status_code == 200
    assert r.json()["role"] == "viewer"


def test_only_owner_may_create_coowner_invite(env):
    client, _, ids, act_as = env
    _join(client, act_as, "coowner", role="co-owner")
    act_as("coowner")
    r = client.post(f"/api/projects/Trip/members/invite?owner={ids['owner']}",
                     json={"role": "co-owner"})
    assert r.status_code == 403
    # ...but a co-owner may still create editor/viewer invites.
    r = client.post(f"/api/projects/Trip/members/invite?owner={ids['owner']}",
                     json={"role": "viewer"})
    assert r.status_code == 200


def test_viewer_and_editor_cannot_create_or_revoke_invite(env):
    client, _, ids, act_as = env
    _join(client, act_as, "editor", role="editor")
    _join(client, act_as, "viewer", role="viewer")
    for who in ("editor", "viewer"):
        act_as(who)
        r = client.post(f"/api/projects/Trip/members/invite?owner={ids['owner']}")
        assert r.status_code == 403
        r = client.delete(f"/api/projects/Trip/members/invite?owner={ids['owner']}")
        assert r.status_code == 403


def test_coowner_can_create_and_revoke_invite(env):
    client, _, ids, act_as = env
    _join(client, act_as, "coowner", role="co-owner")
    act_as("coowner")
    r = client.post(f"/api/projects/Trip/members/invite?owner={ids['owner']}")
    assert r.status_code == 200
    r = client.delete(f"/api/projects/Trip/members/invite?owner={ids['owner']}")
    assert r.status_code == 204


# ── Viewer: read-only ──────────────────────────────────────────────────────────

def test_viewer_can_read_but_not_write(env):
    client, _, ids, act_as = env
    _join(client, act_as, "viewer", role="viewer")
    act_as("viewer")
    q = f"?owner={ids['owner']}"
    assert client.get(f"/api/projects/Trip/meta{q}").status_code == 200
    assert client.get(f"/api/projects/Trip/members{q}").status_code == 200
    r = client.put(f"/api/projects/Trip/day-meta{q}", json={"day_meta": {}})
    assert r.status_code == 403
    r = client.put(f"/api/projects/Trip{q}", json={"trip_start": "2026-01-01"})
    assert r.status_code == 403


def test_viewer_can_read_person_but_not_create_one(env):
    client, _, ids, act_as = env
    act_as("owner")
    person_id = client.post(
        f"/api/people/", json={"project_name": "Trip", "name": "Ana"}
    ).json()["id"]
    _join(client, act_as, "viewer", role="viewer")
    act_as("viewer")
    r = client.get(f"/api/people/{person_id}")
    assert r.status_code == 200
    r = client.post(f"/api/people/?owner={ids['owner']}",
                     json={"project_name": "Trip", "name": "Bob"})
    assert r.status_code == 403


def test_viewer_can_leave_but_not_remove_others(env):
    client, engine, ids, act_as = env
    _join(client, act_as, "viewer", role="viewer")
    act_as("viewer")
    r = client.delete(f"/api/projects/Trip/members/{ids['stranger']}?owner={ids['owner']}")
    assert r.status_code == 403
    r = client.delete(f"/api/projects/Trip/members/{ids['viewer']}?owner={ids['owner']}")
    assert r.status_code == 204
    with Session(engine) as sess:
        assert sess.exec(select(DBProjectMember)).first() is None


# ── Co-owner: editor + rename/share-links/member-management ───────────────────

def test_coowner_can_rename_but_not_delete(env):
    client, _, ids, act_as = env
    _join(client, act_as, "coowner", role="co-owner")
    act_as("coowner")
    q = f"?owner={ids['owner']}"
    r = client.put(f"/api/projects/Trip{q}", json={"new_name": "Renamed"})
    assert r.status_code == 200, r.text
    r = client.delete(f"/api/projects/Renamed{q}")
    assert r.status_code == 403


def test_coowner_can_remove_editor_and_viewer(env):
    client, engine, ids, act_as = env
    _join(client, act_as, "coowner", role="co-owner")
    _join(client, act_as, "editor", role="editor")
    act_as("coowner")
    r = client.delete(f"/api/projects/Trip/members/{ids['editor']}?owner={ids['owner']}")
    assert r.status_code == 204
    with Session(engine) as sess:
        remaining = {m.user_info_id for m in sess.exec(select(DBProjectMember)).all()}
        assert remaining == {ids["coowner"]}


def test_coowner_cannot_remove_another_coowner(env):
    client, engine, ids, act_as = env
    _join(client, act_as, "coowner", role="co-owner")
    # Only the strict owner can create a second co-owner invite.
    _join(client, act_as, "editor", role="co-owner")
    act_as("coowner")
    r = client.delete(f"/api/projects/Trip/members/{ids['editor']}?owner={ids['owner']}")
    assert r.status_code == 403
    act_as("owner")
    r = client.delete(f"/api/projects/Trip/members/{ids['editor']}?owner={ids['owner']}")
    assert r.status_code == 204
    with Session(engine) as sess:
        remaining = {m.user_info_id for m in sess.exec(select(DBProjectMember)).all()}
        assert remaining == {ids["coowner"]}


def test_coowner_can_still_leave_without_owner_permission(env):
    client, engine, ids, act_as = env
    _join(client, act_as, "coowner", role="co-owner")
    act_as("coowner")
    r = client.delete(f"/api/projects/Trip/members/{ids['coowner']}?owner={ids['owner']}")
    assert r.status_code == 204
    with Session(engine) as sess:
        assert sess.exec(select(DBProjectMember)).first() is None


# ── caller_role on project payloads (client capability model, issue #109) ─────

def test_meta_and_full_payload_carry_caller_role(env):
    client, _, ids, act_as = env
    _join(client, act_as, "viewer", role="viewer")
    q = f"?owner={ids['owner']}"

    act_as("owner")
    assert client.get("/api/projects/Trip/meta").json()["caller_role"] == "owner"
    assert client.get("/api/projects/Trip").json()["caller_role"] == "owner"

    act_as("viewer")
    assert client.get(f"/api/projects/Trip/meta{q}").json()["caller_role"] == "viewer"
    assert client.get(f"/api/projects/Trip{q}").json()["caller_role"] == "viewer"
