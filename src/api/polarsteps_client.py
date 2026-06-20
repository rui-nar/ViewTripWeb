"""Unofficial Polarsteps API client using remember_token cookie auth.

Requires Polarsteps-API-Version: 61 header (discovered from the web SPA bundle).
Token format: "{user_id}|{hash}" — user_id is parsed directly from the token.
"""
from __future__ import annotations

from typing import Any

import requests


# A step's `type` marks publication state: 0 = draft (unpublished/offline),
# 1 = published. Imports surface published steps only (issue #23).
_STEP_TYPE_DRAFT = 0


class PolarstepsClient:
    BASE_URL = "https://api.polarsteps.com"
    _API_VERSION = "61"
    _HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Polarsteps-API-Version": _API_VERSION,
    }

    def __init__(self, remember_token: str) -> None:
        self._session = requests.Session()
        self._session.cookies.set("remember_token", remember_token, domain=".polarsteps.com")
        self._session.headers.update(self._HEADERS)
        # user_id is the numeric prefix before the "|" in the token
        try:
            self._user_id = int(remember_token.split("|")[0])
        except (ValueError, IndexError):
            self._user_id = 0

    def _get(self, path: str, **params: Any) -> Any:
        url = f"{self.BASE_URL}{path}"
        resp = self._session.get(url, params=params or None, timeout=20)
        if resp.status_code == 401:
            raise PermissionError("Invalid or expired Polarsteps token")
        resp.raise_for_status()
        return resp.json()

    def get_me(self) -> dict[str, Any]:
        """Return current user info — used to validate the token."""
        return self._get(f"/users/{self._user_id}")

    def get_trips(self, user_id: int) -> list[dict[str, Any]]:
        """Return the user's trips (most-recent first) from the user endpoint."""
        data = self._get(f"/users/{user_id}")
        trips: list[dict[str, Any]] = data.get("trips") or []
        return list(reversed(trips))

    def get_trip_steps(
        self, trip_id: int, *, include_drafts: bool = False
    ) -> list[dict[str, Any]]:
        """Return steps for a trip, sorted chronologically.

        Draft (unpublished) steps are excluded by default so the import only
        surfaces published content. A step's ``type`` field marks publication
        state — ``1`` = published, ``0`` = draft (an offline/unpublished step
        still being written). Confirmed against the live API (issue #23).
        Only an explicit ``type == 0`` is dropped; a missing/unknown type is
        treated as published so a future step kind is never silently hidden.
        Pass ``include_drafts=True`` to keep drafts (used by diagnostics).
        """
        data = self._get(f"/trips/{trip_id}")
        raw_steps: list[dict[str, Any]] = data.get("steps", [])
        if not include_drafts:
            raw_steps = [s for s in raw_steps if s.get("type") != _STEP_TYPE_DRAFT]
        raw_steps.sort(key=lambda s: s.get("start_time") or s.get("creation_time") or "")
        return raw_steps


def _iso_date(ts: int | float | str | None) -> str | None:
    """Convert a Unix timestamp or ISO-8601 string to YYYY-MM-DD."""
    if not ts:
        return None
    if isinstance(ts, str):
        return ts[:10]  # "2017-12-07T11:48:45+00:00"[:10] → "2017-12-07"
    try:
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None


def format_trip(raw: dict[str, Any]) -> dict[str, Any]:
    """Slim down a Polarsteps trip dict for the API response."""
    cover = raw.get("cover_photo") or {}
    cover_url = (
        raw.get("cover_photo_path")
        or (cover.get("large_thumbnail_path") if isinstance(cover, dict) else None)
    )
    return {
        "id": raw.get("id"),
        "name": raw.get("display_name") or raw.get("name") or "",
        "start_date": _iso_date(raw.get("start_date")),
        "end_date": _iso_date(raw.get("end_date")),
        "steps_count": len(raw.get("steps") or raw.get("all_steps") or []),
        "cover_photo_url": cover_url,
    }


def format_step(raw: dict[str, Any]) -> dict[str, Any]:
    """Slim down a Polarsteps step dict for the API response."""
    loc = raw.get("location") or {}
    media = raw.get("media") or raw.get("step_photos") or []
    formatted_photos = []
    for p in media:
        # New API: media items with type=0 are images
        # Old API: step_photos with large_thumbnail_path / thumb_path
        if p.get("type", 0) != 0:
            continue
        large = p.get("large_thumbnail_path") or p.get("path") or ""
        thumb = p.get("small_thumbnail_path") or p.get("thumb_path") or large
        if large:
            formatted_photos.append({"url": large, "thumb_url": thumb})
    return {
        "id": raw.get("id"),
        "name": raw.get("display_name") or raw.get("name") or "",
        "description": raw.get("description") or None,
        # start_time = arrival timestamp (what Polarsteps shows as the step date).
        # creation_time = when the user posted the step (can be the next day).
        "date": _iso_date(raw.get("start_time") or raw.get("creation_time")),
        "lat": loc.get("lat"),
        "lon": loc.get("lon"),
        "location_name": loc.get("locality") or loc.get("name") or loc.get("detail") or None,
        "photos": formatted_photos,
    }
