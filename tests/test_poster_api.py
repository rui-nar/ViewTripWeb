"""API tests for the poster job endpoints (issue #14, Unit A)."""
from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import api.poster as poster_module
import models.db as db_module
from api.deps import get_current_user
from api.poster import router as poster_router
from models.project_db import DBPosterJob, DBProject
from models.user import UserInfo

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

_BODY = {
    "bounds": {"north": 48.9, "south": 48.8, "east": 2.4, "west": 2.3},
    "orientation": "landscape",
    "config": {
        "distance": True, "elevation": False, "hero_photo": True,
        "all_photos": False, "memory_text": True, "counters": False,
        "tag_pie": False, "encounters": False,
    },
    "memories": [
        {"id": 1, "lat": 48.85, "lon": 2.35, "date": "2024-06-01",
         "name": "Day 1", "description": "Arrived", "photo_uuids": ["abc"]},
    ],
}


def _seed(engine):
    with Session(engine) as sess:
        u = UserInfo(display_name="A", email="a@e.com")
        sess.add(u); sess.commit(); sess.refresh(u)
        proj = DBProject(user_info_id=u.id, name="My Trip")
        sess.add(proj); sess.commit(); sess.refresh(proj)
        u2 = UserInfo(display_name="B", email="b@e.com")
        sess.add(u2); sess.commit(); sess.refresh(u2)
        return u.id, u2.id


@pytest.fixture
def env(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_module, "engine", engine)
    SQLModel.metadata.create_all(engine)
    uid, other_uid = _seed(engine)

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(uid), "email": "a@e.com"}
    app.include_router(poster_router)
    return TestClient(app), engine, uid, other_uid


def test_create_job_returns_id_and_stays_pending_until_run(env, monkeypatch):
    """POST creates a job and returns a job_id; the row starts 'pending' until
    the runner actually executes (patched out here so we control timing)."""
    client, engine, uid, _ = env
    monkeypatch.setattr(poster_module, "run_poster_job", lambda job_id: None)

    r = client.post("/api/projects/My Trip/poster", json=_BODY)
    assert r.status_code == 201, r.text
    job_id = r.json()["job_id"]
    assert isinstance(job_id, int)

    r = client.get(f"/api/projects/My Trip/poster/{job_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending"
    assert body["error_message"] is None

    with Session(engine) as sess:
        job = sess.get(DBPosterJob, job_id)
        assert job.user_info_id == uid
        assert job.status == "pending"


def test_full_stub_run_produces_downloadable_png_and_pdf(env):
    """The stub runner (executed synchronously by TestClient's BackgroundTasks)
    takes the job from pending to done and writes real files."""
    client, engine, uid, _ = env

    r = client.post("/api/projects/My Trip/poster", json=_BODY)
    assert r.status_code == 201, r.text
    job_id = r.json()["job_id"]

    status_body = client.get(f"/api/projects/My Trip/poster/{job_id}").json()
    assert status_body["status"] == "done"
    assert status_body["stage"] == "complete"
    assert status_body["error_message"] is None

    png = client.get(f"/api/projects/My Trip/poster/{job_id}/download", params={"format": "png"})
    assert png.status_code == 200
    assert png.headers["content-type"] == "image/png"
    assert png.content[:8] == b"\x89PNG\r\n\x1a\n"

    pdf = client.get(f"/api/projects/My Trip/poster/{job_id}/download", params={"format": "pdf"})
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content[:5] == b"%PDF-"

    with Session(engine) as sess:
        job = sess.get(DBPosterJob, job_id)
        assert job.result_png_path and Path(job.result_png_path).exists()
        assert job.result_pdf_path and Path(job.result_pdf_path).exists()
        assert job.completed_at is not None


def test_download_404_when_job_not_done(env, monkeypatch):
    client, _, _, _ = env
    monkeypatch.setattr(poster_module, "run_poster_job", lambda job_id: None)

    job_id = client.post("/api/projects/My Trip/poster", json=_BODY).json()["job_id"]
    r = client.get(f"/api/projects/My Trip/poster/{job_id}/download", params={"format": "png"})
    assert r.status_code == 404


def test_download_404_for_missing_job(env):
    client, _, _, _ = env
    r = client.get("/api/projects/My Trip/poster/999999/download", params={"format": "png"})
    assert r.status_code == 404


def test_status_and_download_404_for_other_users_job(env):
    """A job created by one user is invisible (404, not leaked) to another."""
    client, _, uid, other_uid = env
    job_id = client.post("/api/projects/My Trip/poster", json=_BODY).json()["job_id"]

    other_app = FastAPI()
    other_app.dependency_overrides[get_current_user] = lambda: {"sub": str(other_uid), "email": "b@e.com"}
    other_app.include_router(poster_router)
    other_client = TestClient(other_app)

    # The other user doesn't even own the project, so this 404s at project lookup.
    r = other_client.get(f"/api/projects/My Trip/poster/{job_id}")
    assert r.status_code == 404
    r = other_client.get(f"/api/projects/My Trip/poster/{job_id}/download", params={"format": "png"})
    assert r.status_code == 404


def test_create_job_404_for_unknown_project(env):
    client, _, _, _ = env
    r = client.post("/api/projects/Nonexistent/poster", json=_BODY)
    assert r.status_code == 404


# ── Migration round-trip ─────────────────────────────────────────────────────

def test_poster_migration_upgrades_and_downgrades_cleanly(tmp_path, monkeypatch):
    """The posterjob migration applies and reverses cleanly from/to head."""
    db_path = tmp_path / "poster_migration_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    cfg = Config(str(_PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")

    command.upgrade(cfg, "head")
    command.downgrade(cfg, "-1")
