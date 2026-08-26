"""API tests for the poster job endpoints (issue #14, Unit A)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import api.poster as poster_module
import models.db as db_module
import src.poster.poster_job_runner as job_runner_module
import src.poster.poster_renderer as renderer_module
import src.poster.tile_stitcher as tile_stitcher
from PIL import Image
from api.deps import get_current_user
from api.poster import poster_public_router, router as poster_router
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
    app.include_router(poster_public_router)
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


def test_config_theme_defaults_to_dark_and_is_stored_on_the_job(env, monkeypatch):
    """The poster's colour scheme travels in the request config, so the
    background runner replays exactly what the client asked for. Dark is the
    default: a poster is composed over satellite imagery."""
    client, engine, _, _ = env
    monkeypatch.setattr(poster_module, "run_poster_job", lambda job_id: None)

    r = client.post("/api/projects/My Trip/poster", json=_BODY)  # no theme given
    job_id = r.json()["job_id"]
    with Session(engine) as sess:
        assert json.loads(sess.get(DBPosterJob, job_id).request_json)["config"]["theme"] == "dark"

    body = {**_BODY, "config": {**_BODY["config"], "theme": "light"}}
    r = client.post("/api/projects/My Trip/poster", json=body)
    job_id = r.json()["job_id"]
    with Session(engine) as sess:
        assert json.loads(sess.get(DBPosterJob, job_id).request_json)["config"]["theme"] == "light"


def test_config_layout_defaults_to_radial_and_is_stored_on_the_job(env, monkeypatch):
    """The perimeter layout (src/poster/perimeter_placement.py) is an opt-in
    prototype: a request that doesn't ask for it keeps the radial placement."""
    client, engine, _, _ = env
    monkeypatch.setattr(poster_module, "run_poster_job", lambda job_id: None)

    r = client.post("/api/projects/My Trip/poster", json=_BODY)  # no layout given
    job_id = r.json()["job_id"]
    with Session(engine) as sess:
        assert json.loads(sess.get(DBPosterJob, job_id).request_json)["config"]["layout"] == "radial"

    body = {**_BODY, "config": {**_BODY["config"], "layout": "perimeter"}}
    r = client.post("/api/projects/My Trip/poster", json=body)
    job_id = r.json()["job_id"]
    with Session(engine) as sess:
        assert json.loads(sess.get(DBPosterJob, job_id).request_json)["config"]["layout"] == "perimeter"


def test_paper_size_defaults_to_a0_and_is_stored_on_the_job(env, monkeypatch):
    """paper_size is a top-level request field (like orientation), not part
    of config; a request that omits it must default to 'A0' so an old
    client's poster renders byte-for-byte the same as before."""
    client, engine, _, _ = env
    monkeypatch.setattr(poster_module, "run_poster_job", lambda job_id: None)

    r = client.post("/api/projects/My Trip/poster", json=_BODY)  # no paper_size given
    job_id = r.json()["job_id"]
    with Session(engine) as sess:
        assert json.loads(sess.get(DBPosterJob, job_id).request_json)["paper_size"] == "A0"

    body = {**_BODY, "paper_size": "A3"}
    r = client.post("/api/projects/My Trip/poster", json=body)
    job_id = r.json()["job_id"]
    with Session(engine) as sess:
        assert json.loads(sess.get(DBPosterJob, job_id).request_json)["paper_size"] == "A3"


def test_paper_size_rejects_an_unknown_value(env, monkeypatch):
    client, _, _, _ = env
    monkeypatch.setattr(poster_module, "run_poster_job", lambda job_id: None)
    body = {**_BODY, "paper_size": "A5"}
    assert client.post("/api/projects/My Trip/poster", json=body).status_code == 422


def test_title_fields_default_to_top_left_project_name_and_unscaled(env, monkeypatch):
    """Omitting title_position/title_text/title_scale entirely must store
    defaults that reproduce the pre-feature hardcoded placement exactly
    (top-left corner, the project's own name, unscaled hero_title)."""
    client, engine, _, _ = env
    monkeypatch.setattr(poster_module, "run_poster_job", lambda job_id: None)

    job_id = client.post("/api/projects/My Trip/poster", json=_BODY).json()["job_id"]
    with Session(engine) as sess:
        stored = json.loads(sess.get(DBPosterJob, job_id).request_json)
    assert stored["title_position"] == {"x": 0.0, "y": 0.0}
    assert stored["title_text"] is None
    assert stored["title_scale"] == 1.0


def test_title_fields_are_stored_when_given(env, monkeypatch):
    client, engine, _, _ = env
    monkeypatch.setattr(poster_module, "run_poster_job", lambda job_id: None)

    body = {
        **_BODY,
        "title_position": {"x": 0.3, "y": 0.7},
        "title_text": "A slice of the trip",
        "title_scale": 1.4,
    }
    job_id = client.post("/api/projects/My Trip/poster", json=body).json()["job_id"]
    with Session(engine) as sess:
        stored = json.loads(sess.get(DBPosterJob, job_id).request_json)
    assert stored["title_position"] == {"x": 0.3, "y": 0.7}
    assert stored["title_text"] == "A slice of the trip"
    assert stored["title_scale"] == 1.4


def test_title_scale_is_clamped_not_rejected(env, monkeypatch):
    """Out-of-range title_scale must be silently clamped to 0.5-2.0, not
    bounced with a 422/500 — the API is the trust boundary, the Flutter
    slider's own clamping is not relied on."""
    client, engine, _, _ = env
    monkeypatch.setattr(poster_module, "run_poster_job", lambda job_id: None)

    too_big = client.post(
        "/api/projects/My Trip/poster", json={**_BODY, "title_scale": 999.0})
    assert too_big.status_code == 201, too_big.text
    with Session(engine) as sess:
        stored = json.loads(sess.get(DBPosterJob, too_big.json()["job_id"]).request_json)
    assert stored["title_scale"] == 2.0

    too_small = client.post(
        "/api/projects/My Trip/poster", json={**_BODY, "title_scale": -3.0})
    assert too_small.status_code == 201, too_small.text
    with Session(engine) as sess:
        stored = json.loads(sess.get(DBPosterJob, too_small.json()["job_id"]).request_json)
    assert stored["title_scale"] == 0.5


def test_config_layout_rejects_an_unknown_value(env, monkeypatch):
    client, _, _, _ = env
    monkeypatch.setattr(poster_module, "run_poster_job", lambda job_id: None)
    body = {**_BODY, "config": {**_BODY["config"], "layout": "spiral"}}
    assert client.post("/api/projects/My Trip/poster", json=body).status_code == 422


def test_config_theme_rejects_an_unknown_value(env, monkeypatch):
    client, _, _, _ = env
    monkeypatch.setattr(poster_module, "run_poster_job", lambda job_id: None)
    body = {**_BODY, "config": {**_BODY["config"], "theme": "sepia"}}
    assert client.post("/api/projects/My Trip/poster", json=body).status_code == 422


def test_full_run_produces_downloadable_png_and_pdf(env, monkeypatch):
    """The runner (executed synchronously by TestClient's BackgroundTasks)
    takes the job from pending to done and writes real files. The Mapbox
    basemap is faked out — a real fetch would need a token and network, and a
    failed fetch now fails the job instead of falling back to grey."""
    client, engine, uid, _ = env
    monkeypatch.setattr(
        renderer_module, "render_basemap",
        lambda bounds, w, h, tile_fetcher=None: Image.new("RGB", (w, h), (120, 140, 160)),
    )

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


def test_job_fails_with_actionable_error_when_basemap_unavailable(env, monkeypatch):
    """With no MAPBOX_TOKEN configured, the job must end 'failed' with an
    error message that names the missing token — not 'done' with a silent
    grey background (issue #14 feedback, point 1)."""
    client, _, _, _ = env
    monkeypatch.setattr(tile_stitcher, "_mapbox_token", lambda: "")

    job_id = client.post("/api/projects/My Trip/poster", json=_BODY).json()["job_id"]
    body = client.get(f"/api/projects/My Trip/poster/{job_id}").json()
    assert body["status"] == "failed"
    assert "MAPBOX_TOKEN" in (body["error_message"] or "")

    # And the unfinished job's file is not downloadable.
    r = client.get(f"/api/projects/My Trip/poster/{job_id}/download", params={"format": "png"})
    assert r.status_code == 404


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


def test_create_job_sets_a_download_token(env, monkeypatch):
    """The token backing the unauthenticated email download link is set at
    creation time, not left to the runner."""
    client, engine, uid, _ = env
    monkeypatch.setattr(poster_module, "run_poster_job", lambda job_id: None)

    job_id = client.post("/api/projects/My Trip/poster", json=_BODY).json()["job_id"]
    with Session(engine) as sess:
        job = sess.get(DBPosterJob, job_id)
        assert job.download_token


# ── Public (token-based) routes — reached from the notification email ───────

def _create_and_finish_job(client, engine, monkeypatch):
    """POST a job, let it run to completion (basemap faked out, same as
    test_full_run_produces_downloadable_png_and_pdf), and return
    (job_id, download_token)."""
    monkeypatch.setattr(
        renderer_module, "render_basemap",
        lambda bounds, w, h, tile_fetcher=None: Image.new("RGB", (w, h), (120, 140, 160)),
    )
    job_id = client.post("/api/projects/My Trip/poster", json=_BODY).json()["job_id"]
    with Session(engine) as sess:
        token = sess.get(DBPosterJob, job_id).download_token
    return job_id, token


def test_status_by_token_for_done_job(env, monkeypatch):
    client, engine, _, _ = env
    _job_id, token = _create_and_finish_job(client, engine, monkeypatch)

    r = client.get(f"/api/poster/{token}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "done"
    assert body["stage"] == "complete"
    assert body["error_message"] is None


def test_download_by_token_returns_png_and_pdf(env, monkeypatch):
    client, engine, _, _ = env
    _job_id, token = _create_and_finish_job(client, engine, monkeypatch)

    png = client.get(f"/api/poster/{token}/download", params={"format": "png"})
    assert png.status_code == 200
    assert png.headers["content-type"] == "image/png"
    assert png.content[:8] == b"\x89PNG\r\n\x1a\n"

    pdf = client.get(f"/api/poster/{token}/download", params={"format": "pdf"})
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content[:5] == b"%PDF-"


def test_download_by_token_404_when_job_not_done(env, monkeypatch):
    client, engine, _, _ = env
    monkeypatch.setattr(poster_module, "run_poster_job", lambda job_id: None)

    job_id = client.post("/api/projects/My Trip/poster", json=_BODY).json()["job_id"]
    with Session(engine) as sess:
        token = sess.get(DBPosterJob, job_id).download_token

    r = client.get(f"/api/poster/{token}/download", params={"format": "png"})
    assert r.status_code == 404


def test_status_by_token_404_for_unknown_token(env):
    """A wrong/missing token 404s the same as an unknown job — no leak of
    which job/user it would have belonged to."""
    client, _, _, _ = env
    r = client.get("/api/poster/not-a-real-token")
    assert r.status_code == 404


def test_download_by_token_404_for_unknown_token(env):
    client, _, _, _ = env
    r = client.get("/api/poster/not-a-real-token/download", params={"format": "png"})
    assert r.status_code == 404


# ── Notification email (issue #14 follow-up) ─────────────────────────────────

class _FakeEmailService:
    def __init__(self):
        self.sent = []

    async def send(self, message):
        self.sent.append(message)


def test_run_poster_job_sends_ready_email_on_success(env, monkeypatch):
    client, engine, uid, _ = env
    monkeypatch.setattr(
        renderer_module, "render_basemap",
        lambda bounds, w, h, tile_fetcher=None: Image.new("RGB", (w, h), (120, 140, 160)),
    )
    fake = _FakeEmailService()
    monkeypatch.setattr(job_runner_module, "get_email_service", lambda: fake)

    job_id = client.post("/api/projects/My Trip/poster", json=_BODY).json()["job_id"]

    assert len(fake.sent) == 1
    assert fake.sent[0].to == "a@e.com"
    with Session(engine) as sess:
        token = sess.get(DBPosterJob, job_id).download_token
    assert token in fake.sent[0].text_body
    assert f"/poster/{token}" in fake.sent[0].text_body


def test_run_poster_job_sends_failed_email_on_failure(env, monkeypatch):
    """The failure email is sent exactly once, and never carries the raw
    internal error_message (issue #14 constraint — it can contain internal
    detail like a stack-trace-derived Mapbox error)."""
    client, _, _, _ = env
    monkeypatch.setattr(tile_stitcher, "_mapbox_token", lambda: "")
    fake = _FakeEmailService()
    monkeypatch.setattr(job_runner_module, "get_email_service", lambda: fake)

    client.post("/api/projects/My Trip/poster", json=_BODY)

    assert len(fake.sent) == 1
    assert fake.sent[0].to == "a@e.com"
    assert "MAPBOX_TOKEN" not in fake.sent[0].text_body


# ── Interrupted-job recovery (issue #14 follow-up) ───────────────────────────
# A poster render is memory-heavy enough that its work-horse can be
# OOM-killed outright — no Python exception for run_poster_job's own
# try/except to catch, so the job row is stuck "running" and the user (who
# was promised an email) hears nothing at all unless something else notices.

def _project_id(engine, name="My Trip"):
    with Session(engine) as sess:
        return sess.exec(select(DBProject).where(DBProject.name == name)).first().id


def test_mark_job_interrupted_fails_the_job_and_sends_the_email(env, monkeypatch):
    client, engine, uid, _ = env
    fake = _FakeEmailService()
    monkeypatch.setattr(job_runner_module, "get_email_service", lambda: fake)

    with Session(engine) as sess:
        job = DBPosterJob(project_id=_project_id(engine), user_info_id=uid, status="running")
        sess.add(job); sess.commit(); sess.refresh(job)
        job_id = job.id

    job_runner_module.mark_job_interrupted(job_id, "work-horse killed (signal 9)")

    with Session(engine) as sess:
        row = sess.get(DBPosterJob, job_id)
    assert row.status == "failed"
    assert row.error_message == "work-horse killed (signal 9)"
    assert row.completed_at is not None
    assert len(fake.sent) == 1
    assert fake.sent[0].to == "a@e.com"


def test_mark_job_interrupted_is_a_noop_on_an_already_terminal_job(env, monkeypatch):
    """A race against the job actually finishing on its own must never
    overwrite that outcome or send a second, contradictory email."""
    client, engine, uid, _ = env
    fake = _FakeEmailService()
    monkeypatch.setattr(job_runner_module, "get_email_service", lambda: fake)

    with Session(engine) as sess:
        job = DBPosterJob(
            project_id=_project_id(engine), user_info_id=uid, status="done",
            result_png_path="/tmp/x.png",
        )
        sess.add(job); sess.commit(); sess.refresh(job)
        job_id = job.id

    job_runner_module.mark_job_interrupted(job_id, "should never apply")

    with Session(engine) as sess:
        row = sess.get(DBPosterJob, job_id)
    assert row.status == "done"
    assert row.error_message is None
    assert fake.sent == []


def test_mark_job_interrupted_never_raises_on_a_missing_job(env):
    client, engine, _, _ = env
    job_runner_module.mark_job_interrupted(999999, "x")  # must not raise


class TestSweepOrphanedPosterJobs:
    """Backstop for the API-startup case — mirrors
    src/jobs/route_jobs.py's sweep_orphaned_jobs, but never re-queues: a
    poster job that died mid-render almost always did so because of its own
    inputs, so re-running the identical render would just repeat the
    failure."""

    def test_pending_and_running_jobs_are_both_failed(self, env, monkeypatch):
        client, engine, uid, _ = env
        fake = _FakeEmailService()
        monkeypatch.setattr(job_runner_module, "get_email_service", lambda: fake)
        pid = _project_id(engine)

        with Session(engine) as sess:
            sess.add(DBPosterJob(project_id=pid, user_info_id=uid, status="pending"))
            sess.add(DBPosterJob(project_id=pid, user_info_id=uid, status="running"))
            sess.commit()

        assert job_runner_module.sweep_orphaned_poster_jobs() == 2
        with Session(engine) as sess:
            statuses = {j.status for j in sess.exec(select(DBPosterJob)).all()}
        assert statuses == {"failed"}
        assert len(fake.sent) == 2

    def test_terminal_jobs_are_left_alone(self, env, monkeypatch):
        client, engine, uid, _ = env
        fake = _FakeEmailService()
        monkeypatch.setattr(job_runner_module, "get_email_service", lambda: fake)
        pid = _project_id(engine)

        with Session(engine) as sess:
            sess.add(DBPosterJob(project_id=pid, user_info_id=uid, status="done"))
            sess.add(DBPosterJob(project_id=pid, user_info_id=uid, status="failed"))
            sess.commit()

        assert job_runner_module.sweep_orphaned_poster_jobs() == 0
        assert fake.sent == []

    def test_a_broken_sweep_does_not_stop_the_app_booting(self, env, monkeypatch):
        def _boom(*_a, **_kw):
            raise RuntimeError("db unavailable")

        monkeypatch.setattr(job_runner_module, "get_session", _boom)
        assert job_runner_module.sweep_orphaned_poster_jobs() == 0  # logged, not raised


# ── Preview (fast, synchronous, no job row) ──────────────────────────────────

def test_preview_returns_png_without_creating_a_job(env):
    client, engine, uid, _ = env

    with Session(engine) as sess:
        jobs_before = len(sess.exec(select(DBPosterJob)).all())

    r = client.post("/api/projects/My Trip/poster/preview", json=_BODY)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"

    with Session(engine) as sess:
        jobs_after = len(sess.exec(select(DBPosterJob)).all())
    assert jobs_after == jobs_before, "preview must not create a DBPosterJob row"


def test_preview_render_failure_returns_500_with_detail(env, monkeypatch):
    """A preview render failure must return a 500 whose detail carries the
    underlying error (issue #14 feedback, point 9 — a bare 500 left the
    'preview not available' report undiagnosable)."""
    client, _, _, _ = env

    def _boom(project_id, user_info_id, request):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(poster_module, "render_poster_preview", _boom)
    r = client.post("/api/projects/My Trip/poster/preview", json=_BODY)
    assert r.status_code == 500
    assert "kaboom" in r.json()["detail"]


def test_preview_404_for_unknown_project(env):
    client, _, _, _ = env
    r = client.post("/api/projects/Nonexistent/poster/preview", json=_BODY)
    assert r.status_code == 404


def test_preview_404_for_project_owned_by_another_user(env):
    client, _, _, other_uid = env

    other_app = FastAPI()
    other_app.dependency_overrides[get_current_user] = lambda: {"sub": str(other_uid), "email": "b@e.com"}
    other_app.include_router(poster_router)
    other_client = TestClient(other_app)

    r = other_client.post("/api/projects/My Trip/poster/preview", json=_BODY)
    assert r.status_code == 404


# ── Migration round-trip ─────────────────────────────────────────────────────

def test_poster_migration_upgrades_and_downgrades_cleanly(tmp_path, monkeypatch):
    """The posterjob migration applies and reverses cleanly from/to head."""
    db_path = tmp_path / "poster_migration_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    cfg = Config(str(_PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")

    # Targets the poster migration by revision id rather than "head"/"-1":
    # head is now a merge point with two parents (issue #33's ImmichToken
    # migration branched off the same revision), and a relative "-1" from a
    # merge point is an ambiguous walk -- alembic can't tell which parent
    # branch "one step back" means. An explicit revision id has no such
    # ambiguity and also exercises this migration's own upgrade/downgrade
    # specifically, regardless of what else later becomes head.
    command.upgrade(cfg, "604340be73bb")
    command.downgrade(cfg, "a1f37c2e8b04")
