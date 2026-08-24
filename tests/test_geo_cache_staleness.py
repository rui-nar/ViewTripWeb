"""Regression tests for issue #132 — stale refills of the full-res geo cache.

``GET /api/geo/project`` reads the project, gzips it, then writes the result into
``_geo_cache``. A read that started *before* a mutation used to happily persist
its pre-mutation snapshot right after that mutation had evicted the entry:

    T0  reader loads project from DB            (pre-mutation state)
    T1  mutation commits
    T2  bust_geo_cache()                        → cache empty; reader hasn't written
    T3  reader writes pre-mutation bytes        → wedged stale until the next bust

Since ``_geo_cache`` had no TTL and was only evicted by an explicit bust, every
later load served the old geometry — a page reload didn't help. The fix is a
per-project generation counter captured before the DB read: the write is
declined if a bust moved it meanwhile. A TTL bounds any future bug of this class.

Sibling coalescing test for the share-tile half of the issue lives in
``test_share_tile_coalescing.py``.
"""
from __future__ import annotations

import json

import polyline as polyline_lib
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import api.geo as geo_mod
import models.db as db_module
from api.deps import get_current_user
from api.geo import _geo_cache, _geo_gen, bust_geo_cache, router as geo_router, warm_geo_cache
from models.project_db import DBActivity, DBProject, DBProjectItem
from models.user import UserInfo

# Pre-mutation and post-mutation geometry — deliberately far apart so a payload
# built from the wrong snapshot is unmistakable.
_LINE_BEFORE = [(60.0, 24.0), (61.0, 25.0)]
_LINE_AFTER = [(10.0, 4.0), (11.0, 5.0)]


@pytest.fixture
def env(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_module, "engine", engine)
    SQLModel.metadata.create_all(engine)
    _geo_cache.clear()
    _geo_gen.clear()

    with Session(engine) as sess:
        user = UserInfo(display_name="Alice", email="a@b.c")
        sess.add(user)
        sess.commit()
        sess.refresh(user)
        uid = user.id
        project = DBProject(user_info_id=uid, name="Trip")
        sess.add(project)
        sess.commit()
        sess.refresh(project)
        pid = project.id

        sess.add(DBActivity(
            id=111, user_info_id=uid, name="Ride", type="Ride",
            start_date="2026-06-01T00:00:00Z",
            summary_polyline=polyline_lib.encode(_LINE_BEFORE),
            start_latlng_json=json.dumps(list(_LINE_BEFORE[0])),
            end_latlng_json=json.dumps(list(_LINE_BEFORE[-1])),
        ))
        sess.add(DBProjectItem(project_id=pid, position=0, item_type="activity", activity_id=111))
        sess.commit()

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(uid), "email": "a@b.c"}
    app.include_router(geo_router)
    yield TestClient(app), uid, engine


def _mutate(engine, uid: int, line) -> None:
    """Commit a new track geometry and bust the cache, as every mutation route does."""
    with Session(engine) as sess:
        act = sess.exec(select(DBActivity).where(DBActivity.id == 111)).first()
        act.summary_polyline = polyline_lib.encode(line)
        sess.add(act)
        sess.commit()
    bust_geo_cache(uid, "Trip")


def _first_coords(resp) -> list:
    feats = [f for f in resp.json()["features"] if f["properties"]["type"] == "activity"]
    assert len(feats) == 1
    return feats[0]["geometry"]["coordinates"]


def _keys_for(uid: int) -> list:
    return [k for k in _geo_cache if k[0] == uid and k[1] == "Trip"]


def test_read_racing_a_mutation_does_not_refill_the_cache(env, monkeypatch):
    """A read whose snapshot is invalidated mid-flight must not persist it.

    The mutation is interleaved between the reader's DB load and its cache write
    by hooking ``_gzip_geo`` — the last step before the write. On ``main`` the
    pre-mutation bytes land in the cache and every later load is a HIT serving
    the old geometry.
    """
    client, uid, engine = env
    orig_gzip = geo_mod._gzip_geo

    def _mutate_then_gzip(features):
        monkeypatch.setattr(geo_mod, "_gzip_geo", orig_gzip)  # only interleave once
        _mutate(engine, uid, _LINE_AFTER)
        return orig_gzip(features)

    monkeypatch.setattr(geo_mod, "_gzip_geo", _mutate_then_gzip)

    resp = client.get("/api/geo/project?name=Trip")
    assert resp.status_code == 200
    # The response itself is fine — it is as fresh as the read that produced it.
    assert _first_coords(resp)[0] == pytest.approx([_LINE_BEFORE[0][1], _LINE_BEFORE[0][0]])
    # …but nothing may be left behind, since it is already superseded.
    assert _keys_for(uid) == []

    # The next load recomputes and sees the post-mutation geometry.
    nxt = client.get("/api/geo/project?name=Trip")
    assert nxt.headers["x-cache"] == "MISS"
    assert _first_coords(nxt)[0] == pytest.approx([_LINE_AFTER[0][1], _LINE_AFTER[0][0]])


def test_warm_racing_a_mutation_does_not_refill_the_cache(env, monkeypatch):
    """``warm_geo_cache`` has the same read-then-write shape and the same guard."""
    client, uid, engine = env
    orig_gzip = geo_mod._gzip_geo

    def _mutate_then_gzip(features):
        monkeypatch.setattr(geo_mod, "_gzip_geo", orig_gzip)
        _mutate(engine, uid, _LINE_AFTER)
        return orig_gzip(features)

    monkeypatch.setattr(geo_mod, "_gzip_geo", _mutate_then_gzip)

    warm_geo_cache(uid, "Trip")
    assert _keys_for(uid) == []


def test_warm_after_the_bust_still_caches(env):
    """The guard must not break the normal path: warming after a bust still caches."""
    client, uid, engine = env
    _mutate(engine, uid, _LINE_AFTER)
    warm_geo_cache(uid, "Trip")
    assert (uid, "Trip", True) in _geo_cache
    assert (uid, "Trip", False) in _geo_cache
    assert client.get("/api/geo/project?name=Trip").headers["x-cache"] == "HIT"


def test_mutation_busts_the_low_res_cache_entry_too(env):
    """A project edit must not leave stale low-res geo behind (issue #212).

    ``bust_geo_cache`` pops every key sharing (uid, name) regardless of the
    variant slot, so this only needs the low-res endpoint to actually key into
    ``_geo_cache`` — this is the regression the low-res cache addition could
    have introduced (serving stale geo after an edit) if it used its own cache
    or skipped the generation check.

    Low-res geo is built from start_latlng/end_latlng, not summary_polyline
    (that's the whole point of the endpoint), so the mutation here has to move
    those columns rather than the shared ``_mutate`` helper's polyline.
    """
    client, uid, engine = env

    first = client.get("/api/geo/project/low-res?name=Trip")
    assert first.headers["x-cache"] == "MISS"
    before = _first_coords(first)
    assert before[0] == pytest.approx([_LINE_BEFORE[0][1], _LINE_BEFORE[0][0]])

    warm = client.get("/api/geo/project/low-res?name=Trip")
    assert warm.headers["x-cache"] == "HIT"

    with Session(engine) as sess:
        act = sess.exec(select(DBActivity).where(DBActivity.id == 111)).first()
        act.start_latlng_json = json.dumps(list(_LINE_AFTER[0]))
        act.end_latlng_json = json.dumps(list(_LINE_AFTER[-1]))
        sess.add(act)
        sess.commit()
    bust_geo_cache(uid, "Trip")

    after = client.get("/api/geo/project/low-res?name=Trip")
    assert after.headers["x-cache"] == "MISS", "stale low-res geo served after an edit"
    assert _first_coords(after)[0] == pytest.approx([_LINE_AFTER[0][1], _LINE_AFTER[0][0]])


def test_entry_expires_after_the_ttl(env, monkeypatch):
    """A HIT turns back into a MISS once the entry outlives ``_GEO_CACHE_TTL_S``."""
    client, uid, _engine = env
    clock = {"now": 1_000.0}
    monkeypatch.setattr(geo_mod, "monotonic", lambda: clock["now"])

    assert client.get("/api/geo/project?name=Trip").headers["x-cache"] == "MISS"
    clock["now"] += geo_mod._GEO_CACHE_TTL_S - 1
    assert client.get("/api/geo/project?name=Trip").headers["x-cache"] == "HIT"

    clock["now"] += 2  # now past the deadline
    assert geo_mod._geo_cache_get((uid, "Trip", False)) is None
    # Expiry evicts rather than leaving a dead entry behind for every read to skip.
    assert _keys_for(uid) == []
    assert client.get("/api/geo/project?name=Trip").headers["x-cache"] == "MISS"
