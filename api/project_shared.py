"""Shared infra for the api.projects.* route modules — no routes of its own.

Holds the single ``ProjectRepo`` instance, legacy file-path helpers, and the
background-task helpers (stats refresh, share-tile refresh) that are reused
across the Core/Activities/Item-ordering/Segments route modules.
"""
from __future__ import annotations

import os
import threading
from typing import Dict

from models.db import get_session
from sqlmodel import select

from api.project_access import resolve_project
from models.project_db import DBProject
from src.project.project_io import ProjectIO
from src.project.project_repo import ProjectRepo

_repo = ProjectRepo()

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


def _projects_dir(user_id: str) -> str:
    path = os.path.join(_DATA_DIR, "users", user_id, "projects")
    os.makedirs(path, exist_ok=True)
    return path


def _legacy_path(user_id: str, name: str) -> str:
    return os.path.join(_projects_dir(user_id), name + ProjectIO.EXTENSION)


def _get_project_row(sess, user_info_id: int, name: str) -> DBProject:
    return resolve_project(sess, user_info_id, name)


def _refresh_share_tiles(user_info_id: int, project_name: str) -> None:
    """Re-render raster tiles for any active share token(s) after a project mutation."""
    from api.share import _build_features, invalidate_share_cache
    from src.tile_renderer import refresh_tile_cache

    with get_session() as sess:
        row = sess.exec(
            select(DBProject).where(
                DBProject.user_info_id == user_info_id,
                DBProject.name == project_name,
            )
        ).first()
    if row is None:
        return
    tokens = [t for t in (row.share_token, row.share_token_no_memories) if t]
    if not tokens:
        return

    for token in tokens:
        invalidate_share_cache(token)

    with get_session() as sess:
        project = _repo.get_project_by_id(sess, row.id)
    if project is None:
        return
    features = _build_features(project)

    for token in tokens:
        refresh_tile_cache(token, lambda f=features: f)


# ── Coalesced background stats refresh (issue #45) ──────────────────────────────
# Every track mutation (edit/split/trim/…) queues a stats refresh, which recomputes
# and writes DBProject.stats_json. A rapid burst (delete→save→delete→save) used to
# stack one concurrent writer per save; on SQLite (single writer) those commits
# serialise behind each other and behind the next save's own commit via
# busy_timeout (30 s), so a save could wait the full window and fail with
# "database is locked". Since only the *latest* project state matters, we coalesce
# per project: at most one refresh runs at a time, and saves that arrive while one
# is in flight set a "rerun" flag so the final state is still captured exactly once.
_stats_refresh_lock = threading.Lock()
_stats_refresh_state: Dict[tuple, Dict[str, bool]] = {}


def _refresh_stats_background(user_info_id: int, project_name: str) -> None:
    """Recompute project stats, coalescing concurrent refreshes per project.

    If a refresh for this project is already running, mark it dirty and return
    immediately (no second concurrent SQLite writer); the in-flight refresh reruns
    once more when it finishes so the newest edit is always reflected.
    """
    key = (user_info_id, project_name)
    with _stats_refresh_lock:
        state = _stats_refresh_state.setdefault(key, {"running": False, "dirty": False})
        if state["running"]:
            state["dirty"] = True
            return
        state["running"] = True
    try:
        while True:
            with get_session() as sess:
                _repo.compute_and_cache_stats(sess, user_info_id, project_name)
            with _stats_refresh_lock:
                if not _stats_refresh_state[key]["dirty"]:
                    break
                _stats_refresh_state[key]["dirty"] = False
    finally:
        with _stats_refresh_lock:
            _stats_refresh_state[key]["running"] = False
