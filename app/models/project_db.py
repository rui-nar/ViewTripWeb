"""SQLModel table models for project, activity, and Strava-cache storage.

These are the *database* representations.  The in-memory domain models live in
``src/models/activity.py`` and ``src/models/project.py``; this module only
handles persistence.

Table names are kept short and lowercase to match SQLite conventions:
  project, activity, projectitem, stravacache
"""
from __future__ import annotations

import time
from typing import Optional

import sqlmodel


class DBProject(sqlmodel.SQLModel, table=True):
    """A named journey project owned by one user."""

    __tablename__ = "project"

    id: Optional[int] = sqlmodel.Field(default=None, primary_key=True)
    user_info_id: int = sqlmodel.Field(foreign_key="userinfo.id", index=True)
    name: str = sqlmodel.Field(index=True)
    version: int = sqlmodel.Field(default=1)
    # JSON-serialised ProjectFilterState: {"start_date": …, "end_date": …, "activity_types": …}
    filter_state_json: str = sqlmodel.Field(default="{}")
    created_at: float = sqlmodel.Field(default_factory=time.time)
    updated_at: float = sqlmodel.Field(default_factory=time.time)


class DBActivity(sqlmodel.SQLModel, table=True):
    """Strava activity row — shared across all projects that reference it.

    Uses the Strava activity ID as the natural primary key (globally unique
    across all Strava accounts).  Datetime fields are stored as ISO-8601 UTC
    strings so they sort lexicographically and require no conversion layer.
    """

    __tablename__ = "activity"

    id: int = sqlmodel.Field(primary_key=True)  # Strava activity ID
    user_info_id: int = sqlmodel.Field(foreign_key="userinfo.id", index=True)

    # Core fields — always populated
    name: str = sqlmodel.Field(default="")
    type: str = sqlmodel.Field(default="", index=True)
    distance: float = sqlmodel.Field(default=0.0)           # metres
    moving_time: int = sqlmodel.Field(default=0)            # seconds
    elapsed_time: int = sqlmodel.Field(default=0)           # seconds
    total_elevation_gain: float = sqlmodel.Field(default=0.0)
    start_date: str = sqlmodel.Field(default="", index=True)  # ISO-8601 UTC
    start_date_local: str = sqlmodel.Field(default="")
    timezone: str = sqlmodel.Field(default="UTC")

    # Social counts
    achievement_count: int = sqlmodel.Field(default=0)
    kudos_count: int = sqlmodel.Field(default=0)
    comment_count: int = sqlmodel.Field(default=0)
    athlete_count: int = sqlmodel.Field(default=0)
    photo_count: int = sqlmodel.Field(default=0)
    pr_count: int = sqlmodel.Field(default=0)
    total_photo_count: int = sqlmodel.Field(default=0)

    # Boolean flags
    trainer: bool = sqlmodel.Field(default=False)
    commute: bool = sqlmodel.Field(default=False)
    manual: bool = sqlmodel.Field(default=False)
    private: bool = sqlmodel.Field(default=False)
    flagged: bool = sqlmodel.Field(default=False)
    has_heartrate: bool = sqlmodel.Field(default=False)
    has_kudoed: bool = sqlmodel.Field(default=False)
    heartrate_opt_out: bool = sqlmodel.Field(default=False)
    display_hide_heartrate_option: bool = sqlmodel.Field(default=False)

    # Speed
    average_speed: float = sqlmodel.Field(default=0.0)
    max_speed: float = sqlmodel.Field(default=0.0)

    # Optional inline fields
    gear_id: Optional[str] = sqlmodel.Field(default=None)
    average_heartrate: Optional[float] = sqlmodel.Field(default=None)
    max_heartrate: Optional[int] = sqlmodel.Field(default=None)
    elev_high: Optional[float] = sqlmodel.Field(default=None)
    elev_low: Optional[float] = sqlmodel.Field(default=None)

    # Coordinates stored as JSON strings: "[lat, lon]"
    start_latlng_json: Optional[str] = sqlmodel.Field(default=None)
    end_latlng_json: Optional[str] = sqlmodel.Field(default=None)

    # GPS and elevation data — may be None until enrichment completes
    summary_polyline: Optional[str] = sqlmodel.Field(default=None)
    # {"distances_km": [...], "elevations_m": [...]}
    elevation_profile_json: Optional[str] = sqlmodel.Field(default=None)

    # Safety valve: unmapped Strava fields that may arrive in the future
    extra_json: str = sqlmodel.Field(default="{}")


class DBProjectItem(sqlmodel.SQLModel, table=True):
    """One ordered entry in a project — either an activity ref or a segment blob."""

    __tablename__ = "projectitem"

    id: Optional[int] = sqlmodel.Field(default=None, primary_key=True)
    project_id: int = sqlmodel.Field(foreign_key="project.id", index=True)
    position: int   # 0-based display order; renumbered on every reorder

    item_type: str  # "activity" | "segment"

    # Populated when item_type == "activity"
    activity_id: Optional[int] = sqlmodel.Field(
        default=None, foreign_key="activity.id"
    )

    # Populated when item_type == "segment"; stores the full ConnectingSegment as JSON
    # (avoids a separate table for a simple object with no independent FK needs)
    segment_json: Optional[str] = sqlmodel.Field(default=None)


class DBStravaCache(sqlmodel.SQLModel, table=True):
    """Per-user cache of the raw Strava activity list.

    One row per user; the entire list is replaced on every refresh.
    """

    __tablename__ = "stravacache"

    user_info_id: int = sqlmodel.Field(
        primary_key=True, foreign_key="userinfo.id"
    )
    fetched_at: float = sqlmodel.Field(default=0.0)   # Unix timestamp
    activities_json: str = sqlmodel.Field(default="[]")  # raw Strava JSON array
