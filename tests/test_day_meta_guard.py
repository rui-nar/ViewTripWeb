"""PUT /day-meta must not let a caller delete day-meta for a day whose content
they cannot see (issue #387).

The endpoint replaces the whole map, so "the user cleared this day's notes"
and "the trip-end prune dropped a day it should not have" arrive as the same
payload — a key that is simply absent. #372 settled which days may go, but
only client-side, and only a current client asks. These tests pin the server's
own rule: a drop is refused only when the caller demonstrably could not have
known what they were dropping.

The second test is the one that matters most — a guard that blocks clearing
notes on an ordinary day would be far worse than the hole it closes. See
day_meta_editor.dart's _persist: emptying a day REMOVES its key.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import models.db as db_module
from api.deps import get_current_user
from api.journal import router as journal_router
from api.projects import router as projects_router
from models.project_db import (
    DBActivity,
    DBProject,
    DBProjectItem,
    DBProjectMember,
)
from models.user import UserInfo


@pytest.fixture()
def env(monkeypatch, tmp_path):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "get_session", lambda: Session(engine))
    import api.projects as projects_mod
    import api.journal as journal_mod
    monkeypatch.setattr(projects_mod, "get_session", lambda: Session(engine))
    monkeypatch.setattr(journal_mod, "get_session", lambda: Session(engine))
    monkeypatch.setattr(journal_mod, "_DATA_DIR", str(tmp_path))

    SQLModel.metadata.create_all(engine)

    with Session(engine) as sess:
        users = {
            who: UserInfo(display_name=who.capitalize(), email=f"{who}@e.com")
            for who in ("owner", "editor")
        }
        for u in users.values():
            sess.add(u)
        sess.commit()
        for u in users.values():
            sess.refresh(u)
        ids = {who: u.id for who, u in users.items()}

        proj = DBProject(user_info_id=ids["owner"], name="Trip")
        sess.add(proj)
        sess.commit()
        sess.refresh(proj)
        ids["project"] = proj.id
        sess.add(DBProjectMember(
            project_id=proj.id, user_info_id=ids["editor"], role="editor",
            invited_by=ids["owner"]))
        sess.commit()

    current = {"uid": ids["owner"]}
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(current["uid"])}
    app.include_router(projects_router)
    app.include_router(journal_router)
    return TestClient(app), engine, ids, lambda who: current.update(uid=ids[who])


def _put(client, day_meta: dict):
    r = client.put("/api/projects/Trip/day-meta", json={"day_meta": day_meta})
    assert r.status_code == 204, r.text


def _stored(engine):
    """Read the stored row directly: the project payload normalises day-meta to
    the fields the client knows, which would hide what this guard preserves."""
    import json as _json
    with Session(engine) as sess:
        row = sess.exec(select(DBProject).where(DBProject.name == "Trip")).one()
        return _json.loads(row.day_meta_json) if row.day_meta_json else {}


def _companion_journal(client, act_as, ids, date: str):
    act_as("editor")
    r = client.post(f"/api/journal/?owner={ids['owner']}", json={
        "project_name": "Trip", "date": date,
        "geo_mode": "custom", "lat": 1.0, "lon": 2.0,
        "description": "editor's private note",
    })
    assert r.status_code == 201, r.text
    act_as("owner")


def test_a_day_pinned_only_by_another_members_journal_survives_a_drop(env):
    """The hole #387 closes: a stale client prunes past the trip end date and
    drops a day it has no way of knowing is still on screen for someone else."""
    client, engine, ids, act_as = env
    _put(client, {"2026-07-04": {"note": "shared notes"},
                  "2026-07-05": {"note": "keep me"}})
    _companion_journal(client, act_as, ids, "2026-07-04")

    _put(client, {"2026-07-05": {"note": "keep me"}})

    assert _stored(engine) == {
        "2026-07-04": {"note": "shared notes"},
        "2026-07-05": {"note": "keep me"},
    }


def test_clearing_the_notes_on_an_ordinary_day_still_removes_it(env):
    """day_meta_editor._persist removes the key when a day is emptied. A guard
    that blocked this would break the commonest edit in the app."""
    client, engine, ids, _ = env
    with Session(engine) as sess:
        sess.add(DBActivity(id=77, user_info_id=ids["owner"], name="Ride",
                            start_date="2026-07-04T06:00:00Z",
                            start_date_local="2026-07-04T08:00:00"))
        sess.add(DBProjectItem(project_id=ids["project"], position=0,
                               item_type="activity", activity_id=77))
        sess.commit()
    _put(client, {"2026-07-04": {"note": "my notes"}})

    _put(client, {})

    assert _stored(engine) == {}


def test_clearing_a_day_the_caller_can_see_via_their_own_journal_still_works(env):
    """Their own journal is visible to them, so they know what they are
    dropping — nothing to protect them from."""
    client, engine, ids, act_as = env
    r = client.post("/api/journal/", json={
        "project_name": "Trip", "date": "2026-07-04",
        "geo_mode": "custom", "lat": 1.0, "lon": 2.0,
        "description": "my own note",
    })
    assert r.status_code == 201, r.text
    _put(client, {"2026-07-04": {"note": "my notes"}})

    _put(client, {})

    assert _stored(engine) == {}


def test_an_empty_entry_on_an_invisibly_pinned_day_is_still_dropped(env):
    """Nothing to lose, so nothing to protect — the guard must not pin empty
    rows in place forever."""
    client, engine, ids, act_as = env
    _put(client, {"2026-07-04": {}})
    _companion_journal(client, act_as, ids, "2026-07-04")

    _put(client, {})

    assert _stored(engine) == {}


def test_a_day_with_no_content_at_all_still_prunes(env):
    """The ordinary trip-end prune from #358 must keep working."""
    client, engine, _, _ = env
    _put(client, {"2026-07-04": {"note": "past the end date"},
                  "2026-07-01": {"note": "keep"}})

    _put(client, {"2026-07-01": {"note": "keep"}})

    assert _stored(engine) == {"2026-07-01": {"note": "keep"}}


def test_the_journals_author_can_still_drop_their_own_day(env):
    """Symmetry check: the editor sees their own journal, so for them the day
    is not invisible and their own drop goes through."""
    client, engine, ids, act_as = env
    _put(client, {"2026-07-04": {"note": "shared notes"}})
    _companion_journal(client, act_as, ids, "2026-07-04")

    act_as("editor")
    r = client.put(f"/api/projects/Trip/day-meta?owner={ids['owner']}",
                   json={"day_meta": {}})
    assert r.status_code == 204, r.text

    act_as("owner")
    assert _stored(engine) == {}
