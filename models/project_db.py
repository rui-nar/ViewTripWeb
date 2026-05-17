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
    # UUID token granting read-only public access (with memories); None = not shared
    share_token: Optional[str] = sqlmodel.Field(default=None, index=True)
    # UUID token granting read-only public access WITHOUT memory items; None = not shared
    share_token_no_memories: Optional[str] = sqlmodel.Field(default=None, index=True)
    # User-defined trip start date override ("YYYY-MM-DD"); None = infer from activities
    trip_start: Optional[str] = sqlmodel.Field(default=None)
    # User-defined trip end date ("YYYY-MM-DD"); None = trip still ongoing
    trip_end: Optional[str] = sqlmodel.Field(default=None)
    # Pre-computed project stats JSON; recomputed after any mutation
    stats_json: Optional[str] = sqlmodel.Field(default=None)
    # Pre-computed low-res GeoJSON (straight line per activity); recomputed after any mutation
    low_res_geo_json: Optional[str] = sqlmodel.Field(default=None)
    # Day metadata keyed by "YYYY-MM-DD": difficulty, sleeping, weather, journal
    day_meta_json: Optional[str] = sqlmodel.Field(default="{}")
    # Ordered list of sleeping option strings (project-configurable)
    sleeping_options_json: Optional[str] = sqlmodel.Field(default="[]")
    # Project-defined counters: [{name, start}]
    counters_json: Optional[str] = sqlmodel.Field(default="[]")


# ---------------------------------------------------------------------------
# Schema contract registry for DBProject
# ---------------------------------------------------------------------------
# Every column on DBProject must appear in exactly one of the two sets below.
# _PROJECT_SERIALIZED_FIELDS  — columns that _row_to_project() reads into the
#                               domain Project; must be kept in sync with the
#                               serialiser in src/project/project_repo.py.
# _PROJECT_INFRA_FIELDS       — columns that are infrastructure / audit / cache
#                               and are NOT surfaced in the Project domain model.
#
# Adding a new column without updating these sets causes a RuntimeError at
# startup (via _check_schema_contract) and a failing schema contract test.

_PROJECT_SERIALIZED_FIELDS: frozenset[str] = frozenset({
    "name",
    "version",
    "filter_state_json",
    "trip_start",
    "trip_end",
    "day_meta_json",
    "sleeping_options_json",
    "counters_json",
})

_PROJECT_INFRA_FIELDS: frozenset[str] = frozenset({
    "id",
    "user_info_id",
    "created_at",
    "updated_at",
    "share_token",
    "share_token_no_memories",
    "stats_json",
    "low_res_geo_json",
})


def _check_schema_contract() -> None:
    """Raise RuntimeError if DBProject columns diverge from the registry.

    Called from the FastAPI lifespan so drift is caught at startup, not silently
    at runtime.  Also exercised by tests/test_schema_contract.py.
    """
    actual = {col.name for col in DBProject.__table__.columns}
    known = _PROJECT_SERIALIZED_FIELDS | _PROJECT_INFRA_FIELDS

    unregistered = actual - known
    if unregistered:
        raise RuntimeError(
            f"DBProject column(s) not registered in the schema contract: "
            f"{sorted(unregistered)}. "
            "Add each column to _PROJECT_SERIALIZED_FIELDS or _PROJECT_INFRA_FIELDS "
            "in models/project_db.py and update _row_to_project() accordingly."
        )

    missing = _PROJECT_SERIALIZED_FIELDS - actual
    if missing:
        raise RuntimeError(
            f"_PROJECT_SERIALIZED_FIELDS references column(s) absent from DBProject: "
            f"{sorted(missing)}. "
            "Update the registry to match the current model."
        )


class DBProjectSyncMeta(sqlmodel.SQLModel, table=True):
    """Per-project auto-sync configuration and last-synced timestamps."""

    __tablename__ = "projectsyncmeta"

    project_id: int = sqlmodel.Field(primary_key=True, foreign_key="project.id")
    linked_ps_trip_id: Optional[int] = sqlmodel.Field(default=None)
    auto_sync_enabled: bool = sqlmodel.Field(default=True)
    last_strava_sync_at: Optional[float] = sqlmodel.Field(default=None)
    last_ps_sync_at: Optional[float] = sqlmodel.Field(default=None)


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


class DBMemory(sqlmodel.SQLModel, table=True):
    """A user-authored memory attached to a project and a specific date."""

    __tablename__ = "memory"

    id: Optional[int] = sqlmodel.Field(default=None, primary_key=True)
    project_id: int = sqlmodel.Field(foreign_key="project.id", index=True)
    name: Optional[str] = sqlmodel.Field(default=None)
    date: str = sqlmodel.Field(index=True)      # "YYYY-MM-DD"
    time: Optional[str] = sqlmodel.Field(default=None)   # "HH:MM"
    description: Optional[str] = sqlmodel.Field(default=None)
    photos_json: str = sqlmodel.Field(default="[]")  # JSON array of base UUID strings
    geo_mode: str = sqlmodel.Field(default="start_of_day")
    lat: Optional[float] = sqlmodel.Field(default=None)
    lon: Optional[float] = sqlmodel.Field(default=None)


class DBProjectItem(sqlmodel.SQLModel, table=True):
    """One ordered entry in a project — either an activity ref, segment, or memory."""

    __tablename__ = "projectitem"

    id: Optional[int] = sqlmodel.Field(default=None, primary_key=True)
    project_id: int = sqlmodel.Field(foreign_key="project.id", index=True)
    position: int   # 0-based display order; renumbered on every reorder

    item_type: str  # "activity" | "segment" | "memory"

    # Populated when item_type == "activity"
    activity_id: Optional[int] = sqlmodel.Field(
        default=None, foreign_key="activity.id"
    )

    # Populated when item_type == "segment"; stores the full ConnectingSegment as JSON
    # (avoids a separate table for a simple object with no independent FK needs)
    segment_json: Optional[str] = sqlmodel.Field(default=None)

    # Populated when item_type == "memory"
    memory_id: Optional[int] = sqlmodel.Field(
        default=None, foreign_key="memory.id"
    )


class DBShareVisit(sqlmodel.SQLModel, table=True):
    """One visitor record for a shared-project link.

    Keyed on (project_id, token_type, anonymous_id) for anonymous visitors and
    (project_id, token_type, user_info_id) for registered ones.  Re-visiting
    updates last_seen_at rather than creating a new row.
    """

    __tablename__ = "sharevisit"

    id: Optional[int] = sqlmodel.Field(default=None, primary_key=True)
    project_id: int = sqlmodel.Field(foreign_key="project.id", index=True)
    token_type: str                          # "full" | "no_memories"
    visitor_type: str                        # "anonymous" | "registered"
    # Set for anonymous visitors (localStorage UUID from the client)
    anonymous_id: Optional[str] = sqlmodel.Field(default=None, index=True)
    # Set for registered visitors
    user_info_id: Optional[int] = sqlmodel.Field(
        default=None, foreign_key="userinfo.id"
    )
    first_seen_at: float = sqlmodel.Field(default_factory=time.time)
    last_seen_at: float = sqlmodel.Field(default_factory=time.time)


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
