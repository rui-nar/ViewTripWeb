"""Unofficial Polarsteps API client using remember_token cookie auth."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import requests


class PolarstepsClient:
    BASE_URL = "https://api.polarsteps.com"
    _HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }

    def __init__(self, remember_token: str) -> None:
        self._session = requests.Session()
        self._session.cookies.set("remember_token", remember_token, domain=".polarsteps.com")
        self._session.headers.update(self._HEADERS)

    def _get(self, path: str, **params: Any) -> Any:
        url = f"{self.BASE_URL}{path}"
        resp = self._session.get(url, params=params or None, timeout=20)
        if resp.status_code == 401:
            raise PermissionError("Invalid or expired Polarsteps token")
        resp.raise_for_status()
        return resp.json()

    def get_me(self) -> dict[str, Any]:
        """Return current user info — used to validate the token."""
        return self._get("/api/3/users/me")

    def get_trips(self, user_id: int) -> list[dict[str, Any]]:
        """Return the user's published trips (most-recent first)."""
        data = self._get(f"/api/3/users/{user_id}/trips")
        trips: list[dict[str, Any]] = data if isinstance(data, list) else data.get("trips", [])
        return trips

    def get_trip_steps(self, trip_id: int) -> list[dict[str, Any]]:
        """Return published steps for a trip, sorted chronologically."""
        data = self._get(f"/api/3/trips/{trip_id}")
        raw_steps: list[dict[str, Any]] = data.get("all_steps", [])
        # Keep only published/visible steps
        steps = [s for s in raw_steps if s.get("is_visible", True)]
        steps.sort(key=lambda s: s.get("creation_time", 0))
        return steps


def _iso_date(unix_ts: int | float | None) -> str | None:
    """Convert a Unix timestamp to an ISO-8601 date string (YYYY-MM-DD)."""
    if not unix_ts:
        return None
    try:
        dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None


def format_trip(raw: dict[str, Any]) -> dict[str, Any]:
    """Slim down a raw Polarsteps trip dict for the API response."""
    start_ts = raw.get("start_date") or raw.get("planned_start_date")
    end_ts = raw.get("end_date") or raw.get("planned_end_date")
    all_steps = raw.get("all_steps") or []
    visible_steps = [s for s in all_steps if s.get("is_visible", True)]
    return {
        "id": raw.get("id"),
        "name": raw.get("name") or raw.get("summary") or "",
        "start_date": _iso_date(start_ts),
        "end_date": _iso_date(end_ts),
        "steps_count": len(visible_steps),
        "cover_photo_url": raw.get("header_photo", {}).get("large_thumbnail_path")
            if isinstance(raw.get("header_photo"), dict) else None,
    }


def format_step(raw: dict[str, Any]) -> dict[str, Any]:
    """Slim down a raw Polarsteps step dict for the API response."""
    loc = raw.get("location") or {}
    photos = raw.get("step_photos") or []
    formatted_photos = []
    for p in photos:
        large = p.get("large_thumbnail_path") or p.get("thumb_path") or ""
        thumb = p.get("thumb_path") or p.get("large_thumbnail_path") or ""
        if large:
            formatted_photos.append({"url": large, "thumb_url": thumb})
    return {
        "id": raw.get("id"),
        "name": raw.get("name") or "",
        "description": raw.get("description") or None,
        "date": _iso_date(raw.get("creation_time")),
        "lat": loc.get("lat"),
        "lon": loc.get("lon"),
        "location_name": loc.get("name") or loc.get("detail") or None,
        "photos": formatted_photos,
    }
