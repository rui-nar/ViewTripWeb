"""Regression test for the share-tile half of issue #132.

``_refresh_share_tiles`` loads the project, builds features, then renders tiles.
Queued once per mutation with no coalescing, two rapid mutations ran two of those
concurrently — and the task that *writes last* need not be the one that *read
last*, so the tiles a viewer sees could end up rendered from the older state.

The stats refresh (issue #45) already solved exactly this with a running/dirty
loop; both now share ``_run_coalesced``, so a burst collapses into one render
that always reruns after the last mutation.
"""
from __future__ import annotations

import json
import threading

import polyline as polyline_lib
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import api.project_shared as shared_module
import api.share as share_mod
import models.db as db_module
import src.tile_renderer as tile_renderer
from models.project_db import DBActivity, DBProject, DBProjectItem
from models.user import UserInfo

_LINE_BEFORE = [(60.0, 24.0), (61.0, 25.0)]
_LINE_AFTER = [(10.0, 4.0), (11.0, 5.0)]


@pytest.fixture
def env(tmp_path, monkeypatch):
    # File-backed: the worker thread and the test's own writes need real,
    # separate connections (an in-memory StaticPool engine shares just one).
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tiles.db'}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(shared_module, "_coalesce_state", {})

    with Session(engine) as sess:
        user = UserInfo(display_name="Alice", email="a@b.c")
        sess.add(user); sess.commit(); sess.refresh(user)
        uid = user.id
        project = DBProject(user_info_id=uid, name="Trip", share_token="tok123")
        sess.add(project); sess.commit(); sess.refresh(project)
        sess.add(DBActivity(
            id=111, user_info_id=uid, name="Ride", type="Ride",
            start_date="2026-06-01T00:00:00Z",
            summary_polyline=polyline_lib.encode(_LINE_BEFORE),
            start_latlng_json=json.dumps(list(_LINE_BEFORE[0])),
            end_latlng_json=json.dumps(list(_LINE_BEFORE[-1])),
        ))
        sess.add(DBProjectItem(project_id=project.id, position=0,
                               item_type="activity", activity_id=111))
        sess.commit()
    return engine, uid


def _mutate(engine, line) -> None:
    with Session(engine) as sess:
        act = sess.exec(select(DBActivity).where(DBActivity.id == 111)).first()
        act.summary_polyline = polyline_lib.encode(line)
        sess.add(act)
        sess.commit()


def test_burst_of_mutations_coalesces_into_one_final_render(env, monkeypatch):
    """A burst of N mutations must produce one coalesced render of the final state.

    Without coalescing each mutation renders independently and the last write can
    carry the older snapshot; with it, N calls arriving during an in-flight render
    collapse to exactly one rerun, which reads after the final commit.
    """
    engine, uid = env
    rendered: list[list] = []
    started = threading.Event()
    release = threading.Event()

    def fake_refresh_tile_cache(token, build):
        rendered.append(build())
        if len(rendered) == 1:
            started.set()
            release.wait(5)  # hold the first render so the burst piles up

    monkeypatch.setattr(tile_renderer, "refresh_tile_cache", fake_refresh_tile_cache)
    monkeypatch.setattr(share_mod, "invalidate_share_cache", lambda token: None)

    worker = threading.Thread(
        target=shared_module._refresh_share_tiles, args=(uid, "Trip"))
    worker.start()
    assert started.wait(5), "first tile render never started"

    # The newest state commits while the first (now stale) render is still in flight.
    _mutate(engine, _LINE_AFTER)
    for _ in range(5):
        shared_module._refresh_share_tiles(uid, "Trip")

    release.set()
    worker.join(10)
    assert not worker.is_alive()

    # One initial render + exactly one coalesced rerun — not six.
    assert len(rendered) == 2
    # …and the rerun is the one that read last, so it carries the final geometry.
    coords = rendered[-1][0]["geometry"]["coordinates"]
    assert coords[0] == pytest.approx([_LINE_AFTER[0][1], _LINE_AFTER[0][0]])


def test_single_refresh_still_renders(env, monkeypatch):
    """The coalescing wrapper must not swallow an uncontended refresh."""
    engine, uid = env
    rendered: list[tuple] = []
    monkeypatch.setattr(tile_renderer, "refresh_tile_cache",
                        lambda token, build: rendered.append((token, build())))
    monkeypatch.setattr(share_mod, "invalidate_share_cache", lambda token: None)

    shared_module._refresh_share_tiles(uid, "Trip")

    assert len(rendered) == 1
    token, features = rendered[0]
    assert token == "tok123"
    assert features[0]["properties"]["activity_id"] == 111
