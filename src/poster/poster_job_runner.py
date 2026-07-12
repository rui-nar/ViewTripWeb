"""Background runner for async A0 poster-generation jobs (issue #14).

``run_poster_job`` is invoked via ``BackgroundTasks.add_task`` from
``api/poster.py`` right after a ``DBPosterJob`` row is created with
status="pending". This unit only stubs the render: it draws a solid-colour
placeholder sized for the requested orientation and saves it as both PNG and
PDF. A later unit swaps the body of the "render" step for real tile-fetching +
compositing (see api/poster.py's ``_poster_dir`` for the on-disk layout this
writes into) without changing this function's signature — callers never
change.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from PIL import Image

from models.db import get_session
from models.project_db import DBPosterJob

_log = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"

# Placeholder dimensions per orientation — not A0-sized yet; a later unit
# replaces this stub with the real tile-stitched render.
_STUB_SIZE = {
    "landscape": (800, 600),
    "portrait": (600, 800),
}
_STUB_COLOR = (230, 230, 230)  # light grey


def _poster_dir(user_id: str, job_id: int) -> Path:
    p = _DATA_DIR / "users" / user_id / "posters" / str(job_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def run_poster_job(job_id: int) -> None:
    """Render the poster for *job_id*, updating its status as it progresses.

    Looks up the job row, marks it "running", renders a placeholder image, and
    marks it "done" with the resulting file paths. Any exception is caught and
    recorded as a "failed" status with ``error_message`` rather than propagating
    (this runs detached, as a FastAPI background task).
    """
    with get_session() as sess:
        job = sess.get(DBPosterJob, job_id)
        if job is None:
            return
        job.status = "running"
        job.stage = "rendering"
        sess.add(job)
        sess.commit()
        user_info_id = job.user_info_id
        request = json.loads(job.request_json or "{}")

    try:
        orientation = request.get("orientation", "landscape")
        size = _STUB_SIZE.get(orientation, _STUB_SIZE["landscape"])

        poster_dir = _poster_dir(str(user_info_id), job_id)
        png_path = poster_dir / "poster.png"
        pdf_path = poster_dir / "poster.pdf"

        img = Image.new("RGB", size, _STUB_COLOR)
        img.save(str(png_path), "PNG")
        img.save(str(pdf_path), "PDF", resolution=300.0)

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
