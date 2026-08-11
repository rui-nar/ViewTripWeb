"""Tests for the scheduled degraded-route retry sweep (issue #207).

A rail resolve that exhausted every Overpass strategy degrades to a straight
endpoint chord rather than failing — but nothing revisited it afterwards, even
though the Overpass mirrors that failed it are often back within minutes.
``retry_degraded_routes`` (``src/jobs/route_jobs.py``) is the scheduled sweep
that does: it re-queues any segment still degraded past a backoff window, up
to a retry cap, through the same resolve path a manual trigger uses.

Covers:
  1. Non-degraded / not-yet-resolved segments are left alone
  2. A segment inside its backoff window is left alone
  3. A segment that already exhausted MAX_DEGRADED_RETRIES is left alone
  4. An eligible segment that recovers: un-degrades, resets bookkeeping, raises
     the "recovered" notice
  5. An eligible segment that is still degraded: retry count increments, no
     notice
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import models.db as db_module
import api.segments as segments_mod
from api.deps import get_current_user
from api.segments import router as segments_router
from models.project_db import DBProject, DBProjectItem
from models.user import UserInfo
from src.jobs import route_jobs as route_jobs_mod
from src.models.project import ConnectingSegment, ProjectItem, SegmentEndpoint
from src.project.project_io import ProjectIO


def _make_app(user_payload: dict) -> FastAPI:
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: user_payload
    app.include_router(segments_router)
    return app


def _segment_json(seg: ConnectingSegment) -> str:
    item = ProjectItem(item_type="segment", segment=seg)
    return json.dumps(ProjectIO._serialise_item(item)["segment"])


def _add_segment(engine, project_id: int, seg: ConnectingSegment) -> None:
    with Session(engine) as sess:
        sess.add(DBProjectItem(
            project_id=project_id, position=0, item_type="segment",
            segment_id=seg.id, segment_json=_segment_json(seg),
        ))
        sess.commit()


def _load_segment(engine, user_id: int, name: str, seg_id: str) -> ConnectingSegment:
    project = segments_mod._repo.get_project(Session(engine), user_id, name)
    return next(s for i in project.items
               if (s := i.segment) and i.item_type == "segment" and s.id == seg_id)


@pytest.fixture
def env(monkeypatch):
    """In-memory DB + one user/project, wired the same way as the resolve tests."""
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_module, "engine", test_engine)
    monkeypatch.setattr(segments_mod, "bust_geo_cache", lambda *a, **k: None)
    monkeypatch.setattr(segments_mod, "warm_geo_cache", lambda *a, **k: None)
    monkeypatch.setattr(segments_mod, "warm_meta_cache", lambda *a, **k: None)

    SQLModel.metadata.create_all(test_engine)
    with Session(test_engine) as sess:
        user = UserInfo(display_name="Alice", email="alice@example.com")
        sess.add(user)
        sess.commit()
        sess.refresh(user)
        user_id = user.id
        project = DBProject(user_info_id=user_id, name="My Trip")
        sess.add(project)
        sess.commit()
        sess.refresh(project)
        project_id = project.id

    client = TestClient(_make_app({"sub": str(user_id), "email": "alice@example.com"}))
    yield client, user_id, project_id, test_engine


def _degraded_segment(
    seg_id: str = "seg-1",
    *,
    retry_count: int = 0,
    age_seconds: float = 20 * 60,
) -> ConnectingSegment:
    """A previously-resolved rail segment sitting on a degraded straight line."""
    degraded_at = (
        datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    ).isoformat()
    return ConnectingSegment(
        id=seg_id, segment_type="train", label="Helsinki → Rovaniemi",
        start=SegmentEndpoint(60.1719, 24.9414),
        end=SegmentEndpoint(66.5039, 25.7294),
        route_mode="rail",
        route_status="resolved",
        route_polyline=json.dumps([[24.9414, 60.1719], [25.7294, 66.5039]]),
        route_degraded=True,
        route_degraded_at=degraded_at,
        route_degraded_retry_count=retry_count,
    )


# ── 1/2/3 — segments the sweep must leave alone ─────────────────────────────────

def test_sweep_skips_non_degraded_segment(env):
    client, user_id, project_id, engine = env
    seg = _degraded_segment()
    seg.route_degraded = False
    _add_segment(engine, project_id, seg)

    assert route_jobs_mod.retry_degraded_routes() == 0
    assert _load_segment(engine, user_id, "My Trip", "seg-1").route_status == "resolved"


def test_sweep_skips_segment_still_inside_backoff(env):
    client, user_id, project_id, engine = env
    _add_segment(engine, project_id, _degraded_segment(age_seconds=30))  # 30s ago

    assert route_jobs_mod.retry_degraded_routes() == 0
    seg = _load_segment(engine, user_id, "My Trip", "seg-1")
    assert seg.route_status == "resolved"  # untouched, not flipped to pending
    assert seg.route_degraded is True


def test_sweep_skips_segment_past_retry_cap(env):
    client, user_id, project_id, engine = env
    _add_segment(engine, project_id, _degraded_segment(
        retry_count=route_jobs_mod.MAX_DEGRADED_RETRIES))

    assert route_jobs_mod.retry_degraded_routes() == 0


# ── 4/5 — eligible segments actually get retried ────────────────────────────────

def test_sweep_retries_and_recovers_raises_notice(env, monkeypatch):
    client, user_id, project_id, engine = env
    _add_segment(engine, project_id, _degraded_segment(retry_count=2))

    real_line = [[24.94, 60.17], [25.2, 61.0], [25.73, 66.50]]
    monkeypatch.setattr(segments_mod, "_compute_segment_geometry",
                        lambda seg, params: (real_line, 3, False, "relation_endpoints"))

    assert route_jobs_mod.retry_degraded_routes() == 1

    seg = _load_segment(engine, user_id, "My Trip", "seg-1")
    assert seg.route_status == "resolved"
    assert seg.route_started_at is None       # job ran to completion, not stuck pending
    assert seg.route_degraded is False
    assert seg.route_degraded_at is None
    assert seg.route_degraded_retry_count == 0
    assert seg.route_recovered_notice is True
    assert json.loads(seg.route_polyline) == real_line


def test_sweep_retries_and_still_degraded_increments_count(env, monkeypatch):
    client, user_id, project_id, engine = env
    _add_segment(engine, project_id, _degraded_segment(retry_count=1))

    straight = [[24.9414, 60.1719], [25.7294, 66.5039]]
    monkeypatch.setattr(segments_mod, "_compute_segment_geometry",
                        lambda seg, params: (straight, 2, True, "straight"))

    assert route_jobs_mod.retry_degraded_routes() == 1

    seg = _load_segment(engine, user_id, "My Trip", "seg-1")
    assert seg.route_status == "resolved"
    assert seg.route_degraded is True
    assert seg.route_degraded_retry_count == 2
    assert seg.route_recovered_notice is False


def test_sweep_handles_multiple_segments_independently(env, monkeypatch):
    client, user_id, project_id, engine = env
    _add_segment(engine, project_id, _degraded_segment("seg-1", retry_count=0))
    _add_segment(engine, project_id, _degraded_segment("seg-2", retry_count=0))

    real_line = [[24.94, 60.17], [25.73, 66.50]]
    monkeypatch.setattr(segments_mod, "_compute_segment_geometry",
                        lambda seg, params: (real_line, 2, False, "relation_endpoints"))

    assert route_jobs_mod.retry_degraded_routes() == 2
    for seg_id in ("seg-1", "seg-2"):
        seg = _load_segment(engine, user_id, "My Trip", seg_id)
        assert seg.route_degraded is False
        assert seg.route_recovered_notice is True
