"""Tests for the asynchronous segment route-resolution flow.

The resolve-route endpoint no longer runs HAFAS + Overpass synchronously (which
caused proxy 504s on long routes). Instead it marks the segment
``route_status="pending"`` and returns 202; a background task
(``_resolve_route_job``) does the slow work and writes the result back.

Covers:
  1. Trigger returns 202 and marks the segment pending (job mocked out)
  2. Trigger 404s for a missing segment, 400s for a non-transport segment
  3. _resolve_route_job success path writes polyline + route_status="resolved"
  4. _resolve_route_job failure path writes route_status="failed" + route_error
     and leaves the great-circle geometry intact
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import models.db as db_module
import api.projects as projects_mod
from api.deps import get_current_user
from api.projects import router as projects_router, _resolve_route_job
from models.project_db import DBProject, DBProjectItem
from models.user import UserInfo
from src.models.project import ConnectingSegment, ProjectItem, SegmentEndpoint
from src.project.project_io import ProjectIO
from src.project.project_repo import StaleWriteError


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_app(user_payload: dict) -> FastAPI:
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: user_payload
    app.include_router(projects_router)
    return app


def _segment_json(seg: ConnectingSegment) -> str:
    item = ProjectItem(item_type="segment", segment=seg)
    return json.dumps(ProjectIO._serialise_item(item)["segment"])


def _add_segment(engine, project_id: int, seg: ConnectingSegment) -> None:
    with Session(engine) as sess:
        sess.add(DBProjectItem(
            project_id=project_id, position=0, item_type="segment",
            segment_json=_segment_json(seg),
        ))
        sess.commit()


def _load_segment(engine, user_id: int, name: str, seg_id: str) -> ConnectingSegment:
    project = projects_mod._repo.get_project(_open(engine), user_id, name)
    return next(s for i in project.items
               if (s := i.segment) and i.item_type == "segment" and s.id == seg_id)


def _open(engine) -> Session:
    return Session(engine)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def env(monkeypatch):
    """In-memory DB + TestClient wired to one user and one project."""
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_module, "engine", test_engine)
    # Keep the geo-cache bust cheap and side-effect-free.
    monkeypatch.setattr(projects_mod, "bust_geo_cache", lambda *a, **k: None)

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


def _train_segment(seg_id: str = "seg-1") -> ConnectingSegment:
    return ConnectingSegment(
        id=seg_id, segment_type="train", label="Helsinki → Rovaniemi",
        start=SegmentEndpoint(60.1719, 24.9414),
        end=SegmentEndpoint(66.5039, 25.7294),
    )


# ── 1. Trigger returns 202 + pending ────────────────────────────────────────────

def test_trigger_returns_202_and_marks_pending(env, monkeypatch):
    client, user_id, project_id, engine = env
    _add_segment(engine, project_id, _train_segment())

    # Mock the background job so the trigger is tested in isolation (TestClient
    # otherwise runs background tasks synchronously after the response).
    calls: list = []
    monkeypatch.setattr(projects_mod, "_resolve_route_job",
                        lambda *a: calls.append(a))

    resp = client.post(
        "/api/projects/My Trip/segments/seg-1/resolve-route",
        json={"hafas_provider": "vr", "train_number": "273"},
    )
    assert resp.status_code == 202
    assert resp.json() == {"status": "pending", "route_status": "pending"}

    seg = _load_segment(engine, user_id, "My Trip", "seg-1")
    assert seg.route_status == "pending"
    assert seg.route_started_at is not None
    assert seg.train_number == "273"
    # The background task was scheduled with the right identifiers.
    assert calls and calls[0][:3] == (user_id, "My Trip", "seg-1")


def test_trigger_404_for_missing_segment(env, monkeypatch):
    client, *_ = env
    monkeypatch.setattr(projects_mod, "_resolve_route_job", lambda *a: None)
    resp = client.post(
        "/api/projects/My Trip/segments/nope/resolve-route", json={})
    assert resp.status_code == 404


def test_trigger_400_for_non_transport_segment(env, monkeypatch):
    client, user_id, project_id, engine = env
    _add_segment(engine, project_id,
                 ConnectingSegment(id="flt", segment_type="flight"))
    monkeypatch.setattr(projects_mod, "_resolve_route_job", lambda *a: None)
    resp = client.post(
        "/api/projects/My Trip/segments/flt/resolve-route", json={})
    assert resp.status_code == 400


# ── 2. Background job success ────────────────────────────────────────────────────

def test_job_success_writes_resolved(env, monkeypatch):
    client, user_id, project_id, engine = env
    _add_segment(engine, project_id, _train_segment())

    fake_line = [[24.94, 60.17], [25.0, 62.0], [25.73, 66.50]]
    monkeypatch.setattr(projects_mod, "_compute_segment_geometry",
                        lambda seg, params: (fake_line, 3))

    _resolve_route_job(user_id, "My Trip", "seg-1",
                       {"hafas_provider": "vr", "train_number": "273"})

    seg = _load_segment(engine, user_id, "My Trip", "seg-1")
    assert seg.route_status == "resolved"
    assert seg.route_mode == "rail"
    assert json.loads(seg.route_polyline) == fake_line
    assert seg.route_error is None
    assert seg.route_started_at is None


# ── 3. Background job failure ────────────────────────────────────────────────────

def test_job_failure_marks_failed_and_keeps_great_circle(env, monkeypatch):
    client, user_id, project_id, engine = env
    _add_segment(engine, project_id, _train_segment())

    def _boom(seg, params):
        raise RuntimeError("overpass exploded")

    monkeypatch.setattr(projects_mod, "_compute_segment_geometry", _boom)

    _resolve_route_job(user_id, "My Trip", "seg-1", {})

    seg = _load_segment(engine, user_id, "My Trip", "seg-1")
    assert seg.route_status == "failed"
    assert "overpass exploded" in seg.route_error
    # Geometry untouched → map still renders the great-circle arc.
    assert seg.route_mode == "great_circle"
    assert seg.route_polyline is None
    assert seg.route_started_at is None


# ── 4. Optimistic concurrency lock ───────────────────────────────────────────────

def test_save_project_optimistic_lock_detects_conflict(env):
    """Two writers that loaded the same version can't both commit silently."""
    client, user_id, project_id, engine = env
    _add_segment(engine, project_id, _train_segment())
    repo = projects_mod._repo

    # Two independent loads observe the same lock_version.
    with Session(engine) as s:
        p_a = repo.get_project(s, user_id, "My Trip")
    with Session(engine) as s:
        p_b = repo.get_project(s, user_id, "My Trip")
    assert p_a.lock_version == p_b.lock_version

    # Writer A commits first — bumps lock_version.
    with Session(engine) as s:
        repo.save_project(s, user_id, p_a, check_version=True)

    # Writer B still holds the stale version → conflict.
    with Session(engine) as s:
        with pytest.raises(StaleWriteError):
            repo.save_project(s, user_id, p_b, check_version=True)


def test_blind_save_does_not_raise(env):
    """Default save_project (check_version=False) overwrites regardless."""
    client, user_id, project_id, engine = env
    _add_segment(engine, project_id, _train_segment())
    repo = projects_mod._repo

    with Session(engine) as s:
        p = repo.get_project(s, user_id, "My Trip")
    with Session(engine) as s:
        repo.save_project(s, user_id, p, check_version=True)   # bump to 1
    # A blind save with a stale in-memory version still succeeds.
    p.lock_version = 0
    with Session(engine) as s:
        repo.save_project(s, user_id, p)  # no check → no raise
