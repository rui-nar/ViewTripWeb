"""Every write a structural save could erase must be visible to the lock.

`save_project` rewrites the whole project row and the entire item list from the
caller's in-memory snapshot. `lock_version` is what stops that from silently
undoing a concurrent write: a writer that advances it turns the clobber into a
`StaleWriteError` the caller retries against reloaded state (issues #172/#173).

Two gaps this pins, both found by auditing every writer rather than by a bug
report:

* the `delete_*` handlers removed a `projectitem` row without advancing the
  counter, while their `create_*` counterparts did. Foreign keys are off in
  production (SQLite), so the structural save re-inserted the deleted row
  pointing at content that no longer exists — silently;
* `save_project`'s blind branch advanced the counter with a read-modify-write,
  which *erases* a bump committed in between rather than adding to it.
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

import models.db as db_module
from api.deps import get_current_user
from api.encounters import router as encounters_router
from api.journal import router as journal_router
from api.memories import router as memories_router
from models.project_db import DBProject, DBProjectItem
from models.user import UserInfo
from src.project.project_repo import ProjectRepo, bump_lock_version
from src.project.repo_core import StaleWriteError


@pytest.fixture
def env(monkeypatch, tmp_path):
    # File-backed: these tests need two sessions to be genuinely independent
    # transactions, which StaticPool's shared connection would fake.
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False})
    monkeypatch.setattr(db_module, "engine", engine)
    import api.journal as journal_mod
    monkeypatch.setattr(journal_mod, "_DATA_DIR", str(tmp_path))
    SQLModel.metadata.create_all(engine)

    with Session(engine) as sess:
        owner = UserInfo(display_name="Owner", email="owner@e.com")
        sess.add(owner); sess.commit(); sess.refresh(owner)
        proj = DBProject(user_info_id=owner.id, name="Trip",
                         day_meta_json=json.dumps({"2024-06-01": {"note": "keep"}}))
        sess.add(proj); sess.commit(); sess.refresh(proj)
        ids = {"owner": owner.id, "project": proj.id, "name": proj.name}

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(ids["owner"])}
    app.include_router(journal_router)
    app.include_router(memories_router)
    app.include_router(encounters_router)
    return TestClient(app), engine, ids


def _lock_version(engine, name="Trip"):
    with Session(engine) as sess:
        return sess.exec(select(DBProject).where(DBProject.name == name)).one().lock_version


def test_deleting_a_journal_entry_advances_the_lock(env):
    """The create_* handlers always bumped; the delete_* ones did not, so a
    structural save loaded before the delete re-inserted the orphaned row."""
    client, engine, ids = env
    r = client.post("/api/journal/", json={
        "project_name": "Trip", "date": "2024-06-01",
        "geo_mode": "custom", "lat": 1.0, "lon": 2.0, "description": "note",
    })
    assert r.status_code == 201, r.text
    journal_id = r.json()["id"]
    after_create = _lock_version(engine)

    r = client.delete(f"/api/journal/{journal_id}")
    assert r.status_code in (200, 204), r.text

    assert _lock_version(engine) == after_create + 1, (
        "the delete did not advance the lock; a structural save that loaded "
        "before it would pass the CAS and resurrect the item row"
    )


def test_a_structural_save_cannot_resurrect_a_deleted_item(env):
    """The effect the bump exists to produce, end to end."""
    client, engine, ids = env
    r = client.post("/api/journal/", json={
        "project_name": "Trip", "date": "2024-06-01",
        "geo_mode": "custom", "lat": 1.0, "lon": 2.0, "description": "note",
    })
    assert r.status_code == 201, r.text
    journal_id = r.json()["id"]

    repo = ProjectRepo()
    with Session(engine) as sess:
        # A structural writer loads the project — snapshot still holds the item.
        stale = repo.get_project(sess, ids["owner"], "Trip")
        assert stale is not None

        r = client.delete(f"/api/journal/{journal_id}")
        assert r.status_code in (200, 204), r.text

        # Its compare-and-swap must now fail rather than rewrite the item list
        # from the snapshot and re-create the row.
        with pytest.raises(StaleWriteError):
            repo.save_project(sess, ids["owner"], stale, check_version=True)

    with Session(engine) as sess:
        rows = sess.exec(
            select(DBProjectItem).where(DBProjectItem.journal_id == journal_id)
        ).all()
    assert rows == [], "the deleted item row came back"


def test_a_blind_save_adds_to_a_concurrent_bump_instead_of_erasing_it(env):
    """`row.lock_version = loaded + 1` writes the value this session loaded, so
    a bump committed in between is overwritten and the counter stands still —
    leaving the CAS blind to one of the two writes. It must increment in SQL."""
    client, engine, ids = env
    repo = ProjectRepo()

    with Session(engine) as sess:
        # Hold the ORM row, exactly as every endpoint does via resolve_project.
        # Without a strong reference SQLAlchemy's weak identity map drops it,
        # save_project re-reads a fresh row, and the read-modify-write happens
        # to be right — which is why this bug survived: it is invisible unless
        # the caller looks like a real caller.
        row = sess.exec(select(DBProject).where(DBProject.name == "Trip")).one()
        project = repo.get_project(sess, ids["owner"], "Trip")
        assert project is not None
        before = row.lock_version

        # Someone else's write lands while this session holds the row.
        with Session(engine) as other:
            bump_lock_version(other, ids["project"])
            other.commit()
        assert _lock_version(engine) == before + 1

        repo.save_project(sess, ids["owner"], project)   # blind mode
        sess.commit()

    assert _lock_version(engine) == before + 2, (
        "the blind save erased the concurrent bump instead of adding to it"
    )


def test_creating_a_segment_retries_a_concurrent_bump_instead_of_409ing(env, monkeypatch):
    """create_segment / update_segment did a single check_version=True save, so
    any bump landing inside the request — the user's own route-resolve job
    finishing, a companion adding a memory — surfaced as a 409 the client shows
    as "this trip changed elsewhere". repo_retry owns that policy; these two
    were the last endpoints not using it."""
    import api.segments as segments_mod
    from api.segments import router as segments_router

    client, engine, ids = env
    client.app.include_router(segments_router)

    # Land a real bump between the wrapper's load and its save, once.
    fired = {"done": False}
    real_quota = segments_mod.ensure_trip_days_quota

    def _quota_then_bump(*a, **k):
        result = real_quota(*a, **k)
        if not fired["done"]:
            fired["done"] = True
            with Session(engine) as other:
                bump_lock_version(other, ids["project"])
                other.commit()
        return result

    monkeypatch.setattr(segments_mod, "ensure_trip_days_quota", _quota_then_bump)

    r = client.post("/api/projects/Trip/segments", json={
        "segment_type": "train", "label": "TGV", "date": "2024-06-01",
        "start_lat": 48.0, "start_lon": 2.0, "end_lat": 49.0, "end_lon": 3.0,
        "insert_after_index": -1,
    })
    assert fired["done"], "the concurrent bump never ran"
    assert r.status_code in (200, 201), (
        f"expected the retry wrapper to absorb the conflict, got {r.status_code}: {r.text}"
    )
