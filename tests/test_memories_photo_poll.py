"""``GET /api/projects/{name}/memory-photos`` — the post-import photo poll (issue #308).

For three minutes after a Polarsteps import the client polls, every 3 s, for one
piece of news: has a background photo download landed on any memory yet? It used
to ask that by re-fetching ``GET /{name}`` with the cache bypassed — 36 MB on a
180-day trip, up to sixty times, while the server was busy fetching those very
photos.

This route answers only the question. Two properties matter and are pinned here:

* it carries the photo **uuids**, not counts — a marker builds its thumbnail URL
  from ``photos.first``, so a count could never take a memory from "no photo" to
  "thumbnail";
* it carries nothing else, so its size is a function of the memory count alone
  and not of trip length.

The measurement that chose it over polling the (also uuid-carrying) ``/meta``:
on a 219-activity / 600-memory trip ``/meta`` is 492 KB and 92 ms to rebuild,
this is 75 KB and 7 ms — and ``_write_memory_photo`` busts the project's cached
payloads as each photo lands, so during the polling window a ``/meta`` poll is a
cache MISS almost every tick.
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import models.db as db_module
from api.deps import get_current_user
from api.geo import _geo_cache, _geo_gen
from api.projects import router as projects_router
from models.project_db import DBActivity, DBMemory, DBProject, DBProjectItem, DBProjectMember
from models.user import UserInfo


@pytest.fixture
def env(monkeypatch):
    """One project with three memories: two with photos, one with none yet."""
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
        owner = UserInfo(display_name="Alice", email="a@b.c")
        mate = UserInfo(display_name="Bob", email="b@b.c")
        stranger = UserInfo(display_name="Eve", email="e@b.c")
        sess.add_all([owner, mate, stranger])
        sess.commit()
        for u in (owner, mate, stranger):
            sess.refresh(u)
        owner_id, mate_id, stranger_id = owner.id, mate.id, stranger.id

        project = DBProject(user_info_id=owner_id, name="Trip")
        sess.add(project)
        sess.commit()
        sess.refresh(project)
        pid = project.id

        sess.add(DBProjectMember(project_id=pid, user_info_id=mate_id, role="viewer",
                                 invited_by=owner_id))

        mem_ids = {}
        for label, photos in (
            ("full", ["uuid-a", "uuid-b"]),
            # A falsy slot is a download that hasn't landed yet — api/photo_locks.py.
            ("partial", ["uuid-c", None]),
            ("empty", []),
        ):
            mem = DBMemory(project_id=pid, date="2026-06-01", name=label,
                           photos_json=json.dumps(photos))
            sess.add(mem)
            sess.flush()
            sess.add(DBProjectItem(project_id=pid, position=0, item_type="memory",
                                   memory_id=mem.id))
            mem_ids[label] = mem.id
        sess.commit()

    app = FastAPI()
    app.include_router(projects_router)
    caller = {"id": owner_id}
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(caller["id"])}

    def as_user(user_id: int) -> None:
        caller["id"] = user_id

    yield TestClient(app), mem_ids, owner_id, mate_id, stranger_id, as_user, engine


def _photos(client, *, owner: int | None = None):
    url = "/api/projects/Trip/memory-photos" + (f"?owner={owner}" if owner else "")
    resp = client.get(url)
    assert resp.status_code == 200, resp.text
    return resp.json()["photos"]


def test_the_payload_is_uuids_not_counts(env):
    client, mem_ids, *_ = env
    photos = _photos(client)
    # Uuids, in order: the marker builds its thumbnail URL from photos.first.
    assert photos[str(mem_ids["full"])] == ["uuid-a", "uuid-b"]


def test_unfilled_download_slots_are_filtered_out(env):
    client, mem_ids, *_ = env
    # A None slot is a queued download, not a photo — serving it would send the
    # marker after a thumbnail URL with a null uuid in it.
    assert _photos(client)[str(mem_ids["partial"])] == ["uuid-c"]


def test_a_memory_with_no_photos_is_present_and_empty(env):
    client, mem_ids, *_ = env
    # Present, not absent: the client merges by id, and "still nothing" has to
    # be distinguishable from "this memory is gone".
    assert _photos(client)[str(mem_ids["empty"])] == []


def test_a_landing_photo_takes_a_memory_from_zero_to_one(env):
    client, mem_ids, *_ = env
    from api.memories import _write_memory_photo

    empty_id = mem_ids["empty"]
    assert _photos(client)[str(empty_id)] == []

    # The real write path a background download takes, busts included.
    _write_memory_photo(empty_id, "uuid-late")

    assert _photos(client)[str(empty_id)] == ["uuid-late"]


def test_the_body_carries_nothing_but_the_photo_map(env):
    client, *_ = env
    body = client.get("/api/projects/Trip/memory-photos").json()
    # No items, no activities, no elevation_profile: the size of this response
    # is a function of the memory count, never of trip length (issue #308).
    assert list(body) == ["photos"]


def test_its_size_does_not_grow_with_the_trip(env):
    client, _mem_ids, owner_id, *_rest = env
    engine = env[-1]

    poll_before = len(client.get("/api/projects/Trip/memory-photos").content)
    details_before = len(client.get("/api/projects/Trip").content)

    with Session(engine) as sess:
        pid = sess.exec(select(DBProject).where(DBProject.name == "Trip")).one().id
        for i in range(40):
            act = DBActivity(
                id=1000 + i, user_info_id=owner_id, name=f"Leg {i}", type="Ride",
                start_date="2026-06-01T08:00:00Z",
                summary_polyline="a" * 4000,
                elevation_profile_json=json.dumps({
                    "distances_km": [round(j * 0.01, 3) for j in range(2000)],
                    "elevations_m": [500.0 + j % 900 for j in range(2000)],
                }),
            )
            sess.add(act)
            sess.add(DBProjectItem(project_id=pid, position=10 + i,
                                   item_type="activity", activity_id=act.id))
        sess.commit()
    _geo_cache.clear()
    _geo_gen.clear()

    poll_after = len(client.get("/api/projects/Trip/memory-photos").content)
    details_after = len(client.get("/api/projects/Trip").content)

    # This is the whole point of the endpoint: the details payload the poll used
    # to fetch grows without bound with trip length, and the poll payload does
    # not move at all. On the real 180-day trip that difference is 36 MB a tick.
    assert poll_after == poll_before
    assert details_after > details_before * 10


def test_a_member_reads_it_through_the_owner_param(env):
    client, mem_ids, owner_id, mate_id, _stranger_id, as_user, _engine = env
    as_user(mate_id)
    # Same auth boundary as /meta: any member, down to a viewer.
    assert _photos(client, owner=owner_id)[str(mem_ids["full"])] == ["uuid-a", "uuid-b"]


def test_a_non_member_cannot_read_it(env):
    client, _mem_ids, owner_id, _mate_id, stranger_id, as_user, _engine = env
    as_user(stranger_id)
    resp = client.get(f"/api/projects/Trip/memory-photos?owner={owner_id}")
    assert resp.status_code == 404, resp.text
