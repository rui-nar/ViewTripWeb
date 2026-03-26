"""Strava OAuth + activity sync endpoints.

Routes:
    GET    /api/strava/connect              — returns OAuth URL to redirect user to
    GET    /api/strava/callback             — exchanges auth code, stores token, redirects to app
    GET    /api/strava/status               — {"connected": bool}
    DELETE /api/strava/disconnect           — removes stored Strava token
    GET    /api/strava/activities           — browse user's Strava activities (with filters)
    GET    /api/strava/cache/status         — cache age + activity count
    POST   /api/projects/{name}/strava/sync — syncs Strava activities into a project
"""
from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timezone
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlmodel import select

import reflex as rx

from api.deps import get_current_user
from app.models.project_db import DBProject, DBProjectItem, DBStravaCache
from app.models.user import StravaToken, UserInfo
from src.api.strava_client import StravaAPI
from src.auth.oauth import OAuth2Session
from src.config.settings import Config
from src.filters.filter_engine import FilterCriteria, FilterEngine
from src.models.activity import Activity
from src.project.project_io import ProjectIO
from src.project.project_repo import ProjectRepo

_project_repo = ProjectRepo()

router = APIRouter(tags=["strava"])

_cfg = Config("config/config.json")

# Redirect URI for Strava OAuth — override via env var in production
_CALLBACK_URI = os.environ.get(
    "STRAVA_REDIRECT_URI",
    "http://localhost:8000/api/strava/callback",
)

# Origin of the Flutter web client — where to redirect after OAuth
_FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5500")

# ── Activity cache ─────────────────────────────────────────────────────────────

# How long a cached activity list is considered fresh (seconds).
_CACHE_TTL = int(os.environ.get("STRAVA_CACHE_TTL", 3600))


def _load_cache(user_info_id: int) -> Dict[str, Any] | None:
    """Return the cached payload if it exists and is within TTL, else None."""
    with rx.session() as sess:
        row = sess.get(DBStravaCache, user_info_id)
    if row is None:
        return None
    age = time.time() - row.fetched_at
    if age > _CACHE_TTL:
        return None
    try:
        return {"fetched_at": row.fetched_at, "activities": json.loads(row.activities_json)}
    except Exception:
        return None


def _save_cache(user_info_id: int, raw_activities: List[Dict[str, Any]]) -> None:
    """Persist the raw Strava activity list to the DB cache."""
    with rx.session() as sess:
        row = sess.get(DBStravaCache, user_info_id)
        if row is None:
            row = DBStravaCache(user_info_id=user_info_id)
            sess.add(row)
        row.fetched_at = time.time()
        row.activities_json = json.dumps(raw_activities)
        sess.commit()


def _invalidate_cache(user_info_id: int) -> None:
    """Remove the cached activity row so the next request re-fetches from Strava."""
    with rx.session() as sess:
        row = sess.get(DBStravaCache, user_info_id)
        if row is not None:
            sess.delete(row)
            sess.commit()


def _fetch_all_strava(client: StravaAPI) -> List[Dict[str, Any]]:
    """Paginate through all Strava activities and return the raw list."""
    all_raw: List[Dict[str, Any]] = []
    page = 1
    while True:
        batch = client.get_activities(per_page=200, page=page)
        if not isinstance(batch, list) or not batch:
            break
        all_raw.extend(batch)
        if len(batch) < 200:
            break
        page += 1
    return all_raw


# ── Helpers ───────────────────────────────────────────────────────────────────

def _strava_client_for_token(token_row: StravaToken) -> StravaAPI:
    """Build a StravaAPI instance pre-loaded with tokens from the DB."""
    client = StravaAPI(_cfg)
    client.token_data = {
        "access_token": token_row.access_token,
        "refresh_token": token_row.refresh_token,
        "expires_at": token_row.expires_at,
    }
    return client


def _save_refreshed_token(sess, token_row: StravaToken, client: StravaAPI) -> None:
    """Persist token back to DB if StravaAPI refreshed it during the request."""
    new = client.token_data
    if (
        new.get("access_token") != token_row.access_token
        or new.get("expires_at", 0) != token_row.expires_at
    ):
        token_row.access_token = new.get("access_token", token_row.access_token)
        token_row.refresh_token = new.get("refresh_token", token_row.refresh_token)
        token_row.expires_at = new.get("expires_at", token_row.expires_at)
        sess.add(token_row)
        sess.commit()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/api/strava/connect")
def strava_connect(current_user: Annotated[dict, Depends(get_current_user)]):
    """Return the Strava OAuth authorization URL."""
    if not _cfg.validate_strava_config():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Strava not configured (missing client_id/secret in config.json)",
        )
    from api.deps import create_access_token
    from app.models.user import UserInfo
    from sqlmodel import select

    # Pass the JWT as state so the callback can identify the user without a session cookie
    user_info_id = int(current_user["sub"])
    with rx.session() as sess:
        user_info = sess.exec(
            select(UserInfo).where(UserInfo.id == user_info_id)
        ).first()
        if user_info is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        state_token = create_access_token(user_info)

    oauth = OAuth2Session(_cfg)
    oauth.redirect_uri = _CALLBACK_URI
    base_url = oauth.authorization_url()
    return {"url": f"{base_url}&state={state_token}"}


@router.get("/api/strava/callback")
def strava_callback(
    code: str | None = None,
    error: str | None = None,
    state: str | None = None,
):
    """Handle Strava OAuth redirect.

    Strava sends the user here with ?code=... after authorising.
    We exchange the code for tokens and store them, then redirect
    back to the Flutter web app.

    Note: This endpoint is intentionally public — it's the OAuth redirect URI.
    The user must be identified via state (for production) or via a short-lived
    cookie. For now we use a simplified flow: the Flutter app passes the JWT in
    the state param and we decode it here.
    """
    if error or not code:
        return RedirectResponse(f"{_FRONTEND_ORIGIN}/settings?strava=error")

    # state carries the JWT so we know which user is connecting
    if not state:
        return RedirectResponse(f"{_FRONTEND_ORIGIN}/settings?strava=error&reason=no_state")

    from api.deps import decode_token
    try:
        payload = decode_token(state)
    except HTTPException:
        return RedirectResponse(f"{_FRONTEND_ORIGIN}/settings?strava=error&reason=invalid_state")

    user_info_id = int(payload["sub"])

    try:
        oauth = OAuth2Session(_cfg)
        oauth.redirect_uri = _CALLBACK_URI
        token_data = oauth.exchange_code(code)
    except Exception as exc:
        return RedirectResponse(
            f"{_FRONTEND_ORIGIN}/?strava=error&reason={str(exc)[:80]}"
        )

    with rx.session() as sess:
        existing = sess.exec(
            select(StravaToken).where(StravaToken.user_info_id == user_info_id)
        ).first()
        if existing:
            existing.access_token = token_data.get("access_token", "")
            existing.refresh_token = token_data.get("refresh_token", "")
            existing.expires_at = float(token_data.get("expires_at", time.time() + 21600))
            sess.add(existing)
        else:
            row = StravaToken(
                user_info_id=user_info_id,
                access_token=token_data.get("access_token", ""),
                refresh_token=token_data.get("refresh_token", ""),
                expires_at=float(token_data.get("expires_at", time.time() + 21600)),
            )
            sess.add(row)
        sess.commit()

    return RedirectResponse(f"{_FRONTEND_ORIGIN}/settings?strava=connected")


@router.get("/api/strava/status")
def strava_status(current_user: Annotated[dict, Depends(get_current_user)]):
    """Return whether the current user has connected their Strava account."""
    user_info_id = int(current_user["sub"])
    with rx.session() as sess:
        row = sess.exec(
            select(StravaToken).where(StravaToken.user_info_id == user_info_id)
        ).first()
    return {"connected": row is not None and bool(row.access_token)}


@router.delete("/api/strava/disconnect", status_code=status.HTTP_204_NO_CONTENT)
def strava_disconnect(current_user: Annotated[dict, Depends(get_current_user)]):
    """Remove the stored Strava token for the current user."""
    user_info_id = int(current_user["sub"])
    with rx.session() as sess:
        row = sess.exec(
            select(StravaToken).where(StravaToken.user_info_id == user_info_id)
        ).first()
        if row:
            sess.delete(row)
            sess.commit()


@router.get("/api/strava/activities")
def strava_activities(
    current_user: Annotated[dict, Depends(get_current_user)],
    start_date: Optional[str] = None,   # YYYY-MM-DD
    end_date: Optional[str] = None,     # YYYY-MM-DD
    types: Optional[str] = None,        # comma-separated, e.g. "Run,Ride"
    project: Optional[str] = None,      # project name to compute in_project
    refresh: bool = False,              # bypass cache and re-fetch from Strava
    page: int = 1,                      # 1-based page number
    per_page: int = 50,                 # items per page (max 200)
):
    """Browse the current user's Strava activities with optional filters.

    Activities are served from a per-user cache (default TTL: 1 hour).
    Filters (date, type) are applied in-memory so filter changes are instant.
    Results are paginated: use ``page`` / ``per_page`` to walk through them.

    Pass ``refresh=true`` to force a full re-fetch and rebuild the cache.

    Response shape:
        {
          "activities": [...],   # page slice, each with "in_project" flag
          "total":     int,      # total matching activities (all pages)
          "page":      int,
          "per_page":  int,
          "has_more":  bool,
          "cached":    bool,
        }
    """
    user_info_id = int(current_user["sub"])
    user_id = current_user["sub"]

    cached = False
    with rx.session() as sess:
        token_row = sess.exec(
            select(StravaToken).where(StravaToken.user_info_id == user_info_id)
        ).first()
        if not token_row:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Strava not connected",
            )

        # Try to serve from cache
        raw_list: Optional[List[Dict[str, Any]]] = None
        if not refresh:
            cache = _load_cache(user_info_id)
            if cache is not None:
                raw_list = cache["activities"]
                cached = True

        # Cache miss or forced refresh — fetch everything from Strava
        if raw_list is None:
            client = _strava_client_for_token(token_row)
            raw_list = _fetch_all_strava(client)
            _save_cache(user_info_id, raw_list)
            _save_refreshed_token(sess, token_row, client)

    # Parse raw dicts → Activity objects
    activities: List[Activity] = []
    for raw in raw_list:
        try:
            activities.append(Activity.from_strava_api(raw))
        except Exception:
            pass

    # Apply date filters
    if start_date:
        try:
            sd = date.fromisoformat(start_date)
            cutoff = datetime(sd.year, sd.month, sd.day, tzinfo=timezone.utc)
            activities = [a for a in activities if a.start_date >= cutoff]
        except ValueError:
            pass
    if end_date:
        try:
            ed = date.fromisoformat(end_date)
            cutoff = datetime(ed.year, ed.month, ed.day, 23, 59, 59, tzinfo=timezone.utc)
            activities = [a for a in activities if a.start_date <= cutoff]
        except ValueError:
            pass

    # Apply type filter
    if types:
        type_set = {t.strip() for t in types.split(",") if t.strip()}
        criteria = FilterCriteria(activity_types=type_set)
        activities = FilterEngine.apply(activities, criteria)

    # Sort newest first (cache order may vary)
    activities.sort(key=lambda a: a.start_date, reverse=True)

    # Determine which activity IDs are already in the project
    in_project_ids: set = set()
    if project:
        with rx.session() as sess:
            proj_row = sess.exec(
                select(DBProject).where(
                    DBProject.user_info_id == user_info_id,
                    DBProject.name == project,
                )
            ).first()
            if proj_row:
                item_rows = sess.exec(
                    select(DBProjectItem).where(
                        DBProjectItem.project_id == proj_row.id,
                        DBProjectItem.item_type == "activity",
                    )
                ).all()
                in_project_ids = {r.activity_id for r in item_rows if r.activity_id is not None}

    total = len(activities)

    # Paginate
    per_page = max(1, min(per_page, 200))
    page = max(1, page)
    offset = (page - 1) * per_page
    page_activities = activities[offset: offset + per_page]
    has_more = (offset + per_page) < total

    result = []
    for a in page_activities:
        d = a.to_strava_dict()
        d["in_project"] = a.id in in_project_ids
        result.append(d)

    return {
        "activities": result,
        "total": total,
        "page": page,
        "per_page": per_page,
        "has_more": has_more,
        "cached": cached,
    }


@router.get("/api/strava/cache/status")
def strava_cache_status(current_user: Annotated[dict, Depends(get_current_user)]):
    """Return metadata about the current user's activity cache."""
    user_info_id = int(current_user["sub"])
    with rx.session() as sess:
        row = sess.get(DBStravaCache, user_info_id)
    if row is None or not row.activities_json:
        return {"cached": False, "count": 0, "age_seconds": None}
    try:
        age = time.time() - row.fetched_at
        count = len(json.loads(row.activities_json))
        return {"cached": True, "count": count, "age_seconds": round(age)}
    except Exception:
        return {"cached": False, "count": 0, "age_seconds": None}


@router.post("/api/projects/{name}/strava/sync")
def strava_sync(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Fetch all Strava activities and add new ones to the project.

    Paginates through the Strava activities endpoint (200 per page) until
    an empty page is returned. Only activities not already in the project are
    added. Returns the count added and the new total.
    """
    user_info_id = int(current_user["sub"])
    user_id = current_user["sub"]

    with rx.session() as sess:
        token_row = sess.exec(
            select(StravaToken).where(StravaToken.user_info_id == user_info_id)
        ).first()
        if not token_row:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Strava not connected — go to projects and click 'Connect Strava'",
            )

        client = _strava_client_for_token(token_row)

        # Fetch all activities from Strava and update cache
        all_raw = _fetch_all_strava(client)
        _save_cache(user_info_id, all_raw)

        activities = []
        for raw in all_raw:
            try:
                activities.append(Activity.from_strava_api(raw))
            except Exception:
                pass  # skip malformed entries

        # Load project and merge
        project = _project_repo.get_project(sess, user_info_id, name)
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        added = project.add_activities(activities)
        _project_repo.save_project(sess, user_info_id, project)

        # Persist refreshed token if StravaAPI auto-renewed it
        _save_refreshed_token(sess, token_row, client)

    return {"added": added, "total": len(project.activities)}
