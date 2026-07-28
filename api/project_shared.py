"""Shared infra for the api.projects.* route modules — no routes of its own.

Holds the single ``ProjectRepo`` instance, legacy file-path helpers, and the
background-task helpers (stats refresh, share-tile refresh) that are reused
across the Core/Activities/Item-ordering/Segments route modules.
"""
from __future__ import annotations

import os
import threading
from typing import Callable, Dict

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


# ── Coalesced background refreshes (issues #45, #132) ──────────────────────────
# Every mutation queues background work (stats recompute, share-tile re-render)
# that reads the project and then writes a derived artefact. Running a burst of
# those concurrently is wrong twice over: on SQLite the stats writers serialise
# behind each other and behind the next save's own commit via busy_timeout (30 s),
# so a save could wait the full window and fail with "database is locked" (#45);
# and for tiles, the task that *writes last* need not be the one that *read last*,
# so a burst could leave tiles rendered from an older state (#132).
#
# Since only the latest project state matters, we coalesce per key: at most one
# worker runs at a time, and requests arriving while one is in flight set a rerun
# flag so the final state is still captured — exactly once, after the last one.
_coalesce_lock = threading.Lock()
_coalesce_state: Dict[tuple, Dict[str, bool]] = {}


def _run_coalesced(key: tuple, work: Callable[[], None]) -> None:
    """Run *work*, collapsing calls that arrive while one is in flight for *key*.

    Returns immediately (marking the running worker dirty) if one is already
    running; that worker reruns *work* once more when it finishes, so the newest
    state is always the one reflected.
    """
    with _coalesce_lock:
        state = _coalesce_state.setdefault(key, {"running": False, "dirty": False})
        if state["running"]:
            state["dirty"] = True
            return
        state["running"] = True
    try:
        while True:
            work()
            with _coalesce_lock:
                if not _coalesce_state[key]["dirty"]:
                    break
                _coalesce_state[key]["dirty"] = False
    finally:
        with _coalesce_lock:
            _coalesce_state[key]["running"] = False


def _refresh_share_tiles(user_info_id: int, project_name: str) -> None:
    """Re-render raster tiles for any active share token(s) after a project mutation.

    Coalesced per project so a burst of mutations collapses into one render that
    always reflects the final state (and skips the redundant intermediate ones).
    """
    _run_coalesced(("tiles", user_info_id, project_name),
                   lambda: _refresh_share_tiles_once(user_info_id, project_name))


def _refresh_share_tiles_once(user_info_id: int, project_name: str) -> None:
    """One share-tile render pass — see :func:`_refresh_share_tiles`."""
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


def _refresh_stats_background(user_info_id: int, project_name: str) -> None:
    """Recompute project stats, coalescing concurrent refreshes per project.

    If a refresh for this project is already running, mark it dirty and return
    immediately (no second concurrent SQLite writer); the in-flight refresh reruns
    once more when it finishes so the newest edit is always reflected.
    """
    _run_coalesced(("stats", user_info_id, project_name),
                   lambda: _refresh_stats_once(user_info_id, project_name))


def _refresh_stats_once(user_info_id: int, project_name: str) -> None:
    """One stats recompute pass — see :func:`_refresh_stats_background`."""
    with get_session() as sess:
        _repo.compute_and_cache_stats(sess, user_info_id, project_name)
