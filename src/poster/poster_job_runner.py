"""Background runner for async A0 poster-generation jobs (issue #14).

``run_poster_job`` is invoked via ``BackgroundTasks.add_task`` from
``api/poster.py`` right after a ``DBPosterJob`` row is created with
status="pending". The actual rendering (basemap + route + memory pins/cards)
lives in ``src/poster/poster_renderer.py`` (Unit E) — this module owns only
the job-row lifecycle: marking it "running", invoking the renderer with a
``progress`` callback that updates ``job.stage`` between steps, and marking it
"done"/"failed" with the resulting file paths or error.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from models.db import get_session
from models.project_db import DBPosterJob
from src.poster.poster_renderer import render_poster

_log = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def _poster_dir(user_id: str, job_id: int) -> Path:
    p = _DATA_DIR / "users" / user_id / "posters" / str(job_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def run_poster_job(job_id: int) -> None:
    """Render the poster for *job_id*, updating its status as it progresses.

    Looks up the job row, marks it "running", renders the real poster (real
    basemap + pins/cards/route), and marks it "done" with the resulting file
    paths. Any exception is caught and recorded as a "failed" status with
    ``error_message`` rather than propagating (this runs detached, as a
    FastAPI background task).
    """
    with get_session() as sess:
        job = sess.get(DBPosterJob, job_id)
        if job is None:
            return
        job.status = "running"
        job.stage = "starting"
        sess.add(job)
        sess.commit()
        user_info_id = job.user_info_id
        project_id = job.project_id
        request = json.loads(job.request_json or "{}")

    def _progress(stage: str) -> None:
        """Persist a progress label onto the job row for polling clients."""
        with get_session() as s:
            j = s.get(DBPosterJob, job_id)
            if j is not None:
                j.stage = stage
                s.add(j)
                s.commit()

    try:
        poster_dir = _poster_dir(str(user_info_id), job_id)
        png_path, pdf_path = render_poster(
            job_id=job_id,
            user_info_id=user_info_id,
            project_id=project_id,
            request=request,
            poster_dir=poster_dir,
            progress=_progress,
        )

        with get_session() as sess:
            job = sess.get(DBPosterJob, job_id)
            job.status = "done"
            job.stage = "complete"
            job.result_png_path = str(png_path)
            job.result_pdf_path = str(pdf_path)
            job.completed_at = time.time()
            sess.add(job)
            sess.commit()
    except Exception as exc:
        _log.exception("Poster job %s failed", job_id)
        with get_session() as sess:
            job = sess.get(DBPosterJob, job_id)
            if job is not None:
                job.status = "failed"
                job.error_message = str(exc)
                job.completed_at = time.time()
                sess.add(job)
                sess.commit()
