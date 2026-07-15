"""SQLModel table models for project, activity, and Strava-cache storage.

These are the *database* representations.  The in-memory domain models live in
``src/models/activity.py`` and ``src/models/project.py``; this module only
handles persistence.

Table names are kept short and lowercase to match SQLite conventions:
  project, activity, projectitem, stravacache
"""
from __future__ import annotations

import time
import uuid
from typing import Optional

import sqlmodel
from sqlalchemy import Index, UniqueConstraint, text


class DBProject(sqlmodel.SQLModel, table=True):
    """A named journey project owned by one user."""

    __tablename__ = "project"

    id: Optional[int] = sqlmodel.Field(default=None, primary_key=True)
    user_info_id: int = sqlmodel.Field(foreign_key="userinfo.id", index=True)
    name: str = sqlmodel.Field(index=True)
    version: int = sqlmodel.Field(default=1)
    # Optimistic-lock counter, bumped on every save_project; distinct from the
    # user-facing `version` (project schema version). Detects concurrent writes.
    lock_version: int = sqlmodel.Field(default=0)
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
    # Track display style
    track_color: str = sqlmodel.Field(default="#F97316")
    track_secondary_color: Optional[str] = sqlmodel.Field(default=None)  # "#RRGGBB" or None = auto-derive
    track_width: float = sqlmodel.Field(default=2.5)
    alternating_track_colors: bool = sqlmodel.Field(default=False)
    # Elevation chart style
    elevation_chart_color: Optional[str] = sqlmodel.Field(default=None)  # "#RRGGBB" or None = use black
    elevation_chart_show_line: bool = sqlmodel.Field(default=True)
    # Per-activity/segment-type colour+style overrides (issue #95). Off by
    # default so existing projects keep today's flat track_color rendering.
    color_by_type: bool = sqlmodel.Field(default=False)
    # JSON dict: {"ride": {"color": "#RRGGBB", "style": "solid"|"dashed"|"dotted"}, ...}
    type_styles_json: str = sqlmodel.Field(default="{}")
    # JSON array of ISO 639-1 language codes for memory translations, e.g. '["fr","de"]'
    languages_json: Optional[str] = sqlmodel.Field(default=None)


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
    "track_color",
    "track_secondary_color",
    "track_width",
    "alternating_track_colors",
    "elevation_chart_color",
    "elevation_chart_show_line",
    "languages_json",
    "color_by_type",
    "type_styles_json",
})

_PROJECT_INFRA_FIELDS: frozenset[str] = frozenset({
    "id",
    "user_info_id",
    "lock_version",
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
    # Downsampled copy of elevation_profile_json (~300 pts) for the low-res-first
    # chart. Lightweight (never deferred) so meta/low-res loads stay fast without
    # reading the multi-MB full profile. Derived; see elevation_downsample.py.
    elevation_profile_low_res_json: Optional[str] = sqlmodel.Field(default=None)

    # Geometry-edit state (issue #31). When True the track was edited locally
    # (trim/add/remove/split) and Strava sync/enrichment must SKIP this row so
    # the edit is not overwritten. The original_* columns snapshot the pre-edit
    # geometry once, enabling a reversible "Reset to Strava". DB-only — the
    # snapshots are never surfaced in the domain model or the .viewtrip file.
    is_edited: bool = sqlmodel.Field(default=False)
    original_polyline: Optional[str] = sqlmodel.Field(default=None)
    original_elevation_profile_json: Optional[str] = sqlmodel.Field(default=None)

    # Safety valve: unmapped Strava fields that may arrive in the future
    extra_json: str = sqlmodel.Field(default="{}")


class DBMemory(sqlmodel.SQLModel, table=True):
    """A user-authored memory attached to a project and a specific date."""

    __tablename__ = "memory"
    # A Polarsteps step may be imported at most once per project. Partial so the
    # many NULL ids (non-Polarsteps memories) stay exempt. Mirrors migration
    # c9d0e1f2a3b4. Kept here so the constraint travels with the model metadata.
    __table_args__ = (
        Index(
            "uq_memory_project_polarsteps_step_id",
            "project_id",
            "polarsteps_step_id",
            unique=True,
            sqlite_where=text("polarsteps_step_id IS NOT NULL"),
            postgresql_where=text("polarsteps_step_id IS NOT NULL"),
        ),
    )

    id: Optional[int] = sqlmodel.Field(default=None, primary_key=True)
    # Stable public identifier used in durable share URLs. Generated once at
    # creation and never changed — decoupled from the reassignable primary key
    # so a delete+recreate or full re-import never breaks an existing link.
    public_id: str = sqlmodel.Field(
        default_factory=lambda: uuid.uuid4().hex, index=True, unique=True)
    project_id: int = sqlmodel.Field(foreign_key="project.id", index=True)
    name: Optional[str] = sqlmodel.Field(default=None)
    date: str = sqlmodel.Field(index=True)      # "YYYY-MM-DD"
    time: Optional[str] = sqlmodel.Field(default=None)   # "HH:MM"
    description: Optional[str] = sqlmodel.Field(default=None)
    photos_json: str = sqlmodel.Field(default="[]")  # JSON array of base UUID strings
    geo_mode: str = sqlmodel.Field(default="start_of_day")
    lat: Optional[float] = sqlmodel.Field(default=None)
    lon: Optional[float] = sqlmodel.Field(default=None)
    polarsteps_step_id: Optional[int] = sqlmodel.Field(default=None, index=True)
    # E2EE marker (issue #26): 0 = plaintext; >=1 = `name`/`description` hold
    # self-describing ciphertext blobs encrypted client-side under the user's CMK.
    enc_version: int = sqlmodel.Field(default=0)


class DBJournalEntry(sqlmodel.SQLModel, table=True):
    """A private, owner-only journal entry attached to a project and a specific date."""

    __tablename__ = "journalentry"

    id: Optional[int] = sqlmodel.Field(default=None, primary_key=True)
    project_id: int = sqlmodel.Field(foreign_key="project.id", index=True)
    date: str = sqlmodel.Field(index=True)      # "YYYY-MM-DD"
    time: Optional[str] = sqlmodel.Field(default=None)
    description: Optional[str] = sqlmodel.Field(default=None)
    photos_json: str = sqlmodel.Field(default="[]")
    geo_mode: str = sqlmodel.Field(default="start_of_day")
    lat: Optional[float] = sqlmodel.Field(default=None)
    lon: Optional[float] = sqlmodel.Field(default=None)
    # E2EE marker (issue #26): 0 = plaintext `description`; >=1 = ciphertext blob.
    enc_version: int = sqlmodel.Field(default=0)


class DBPerson(sqlmodel.SQLModel, table=True):
    """A person met on a trip (issue #40) — owner-only, per-project.

    All identity fields are optional: a person may be just a first name or even
    "Unknown". Referenced by DBEncounter rows; never exposed in shared views.
    """

    __tablename__ = "person"

    id: Optional[int] = sqlmodel.Field(default=None, primary_key=True)
    project_id: int = sqlmodel.Field(foreign_key="project.id", index=True)
    name: Optional[str] = sqlmodel.Field(default=None)
    email: Optional[str] = sqlmodel.Field(default=None)
    phone: Optional[str] = sqlmodel.Field(default=None)
    polarsteps: Optional[str] = sqlmodel.Field(default=None)  # username or profile URL
    notes: Optional[str] = sqlmodel.Field(default=None)
    avatar_photo: Optional[str] = sqlmodel.Field(default=None)  # base UUID filename
    # JSON list of {"network", "handle"} social links; the polarsteps column above
    # is kept and mirrored from the "polarsteps" entry so the shared-trip view works.
    socials_json: Optional[str] = sqlmodel.Field(default=None)
    nationalities_json: Optional[str] = sqlmodel.Field(default=None)  # JSON list of ISO 3166-1 alpha-2 codes
    residence: Optional[str] = sqlmodel.Field(default=None)  # "city, country" where they live
    # Membership in at most one group (issue #50); null = ungrouped.
    group_id: Optional[int] = sqlmodel.Field(default=None, foreign_key="person_group.id", index=True)
    created_at: float = sqlmodel.Field(default_factory=time.time)


class DBPersonGroup(sqlmodel.SQLModel, table=True):
    """A named group of people met on a trip (issue #50) — owner-only, per-project.

    Members are DBPerson rows whose group_id points here. Own fields: name,
    nationalities, socials. Never exposed in shared views.
    """

    __tablename__ = "person_group"

    id: Optional[int] = sqlmodel.Field(default=None, primary_key=True)
    project_id: int = sqlmodel.Field(foreign_key="project.id", index=True)
    name: Optional[str] = sqlmodel.Field(default=None)
    nationalities_json: Optional[str] = sqlmodel.Field(default=None)  # JSON list of ISO alpha-2 codes
    socials_json: Optional[str] = sqlmodel.Field(default=None)        # JSON list of {"network","handle"}
    created_at: float = sqlmodel.Field(default_factory=time.time)


class DBEncounter(sqlmodel.SQLModel, table=True):
    """Meeting a person or group on a given day/place (issue #40, #56) — owner-only, per-project.

    Exactly one of person_id/group_id is set (enforced at the API layer).
    """

    __tablename__ = "encounter"

    id: Optional[int] = sqlmodel.Field(default=None, primary_key=True)
    project_id: int = sqlmodel.Field(foreign_key="project.id", index=True)
    person_id: Optional[int] = sqlmodel.Field(default=None, foreign_key="person.id", index=True)
    group_id: Optional[int] = sqlmodel.Field(default=None, foreign_key="person_group.id", index=True)
    date: str = sqlmodel.Field(index=True)      # "YYYY-MM-DD"
    time: Optional[str] = sqlmodel.Field(default=None)   # "HH:MM"
    description: Optional[str] = sqlmodel.Field(default=None)
    geo_mode: str = sqlmodel.Field(default="start_of_day")
    lat: Optional[float] = sqlmodel.Field(default=None)
    lon: Optional[float] = sqlmodel.Field(default=None)


class DBProjectItem(sqlmodel.SQLModel, table=True):
    """One ordered entry in a project — an activity ref, segment, memory, journal, or encounter."""

    __tablename__ = "projectitem"

    id: Optional[int] = sqlmodel.Field(default=None, primary_key=True)
    project_id: int = sqlmodel.Field(foreign_key="project.id", index=True)
    position: int   # 0-based display order; renumbered on every reorder

    item_type: str  # "activity" | "segment" | "memory" | "journal" | "encounter"

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

    # Populated when item_type == "journal"
    journal_id: Optional[int] = sqlmodel.Field(
        default=None, foreign_key="journalentry.id"
    )

    # Populated when item_type == "encounter"
    encounter_id: Optional[int] = sqlmodel.Field(
        default=None, foreign_key="encounter.id"
    )


class DBPosterJob(sqlmodel.SQLModel, table=True):
    """An async server-side A0 poster-generation job for a project (issue #14).

    Created with status="pending" by POST /api/projects/{name}/poster and
    advanced by the background runner (src/poster/poster_job_runner.py) through
    "running" to a terminal "done"/"failed" state. ``request_json`` is the
    original request body (bounds/orientation/config/memories) so the runner —
    and later units that replace what it renders — can read the parameters back
    out from the job id alone.
    """

    __tablename__ = "posterjob"

    id: Optional[int] = sqlmodel.Field(default=None, primary_key=True)
    project_id: int = sqlmodel.Field(foreign_key="project.id", index=True)
    user_info_id: int = sqlmodel.Field(foreign_key="userinfo.id", index=True)
    status: str = sqlmodel.Field(default="pending")  # pending | running | done | failed
    stage: Optional[str] = sqlmodel.Field(default=None)  # human-readable progress label
    error_message: Optional[str] = sqlmodel.Field(default=None)
    request_json: str = sqlmodel.Field(default="{}")  # bounds/orientation/config/memories
    created_at: float = sqlmodel.Field(default_factory=time.time)
    completed_at: Optional[float] = sqlmodel.Field(default=None)
    result_png_path: Optional[str] = sqlmodel.Field(default=None)
    result_pdf_path: Optional[str] = sqlmodel.Field(default=None)


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


class DBMemoryComment(sqlmodel.SQLModel, table=True):
    """A comment on a memory — posted by an authenticated user."""

    __tablename__ = "memory_comment"

    id: Optional[int] = sqlmodel.Field(default=None, primary_key=True)
    memory_id: int = sqlmodel.Field(foreign_key="memory.id", index=True)
    parent_comment_id: Optional[int] = sqlmodel.Field(
        default=None, foreign_key="memory_comment.id"
    )
    user_info_id: int = sqlmodel.Field(foreign_key="userinfo.id")
    commenter_name: str = sqlmodel.Field(default="")  # snapshot of display_name at post time
    text: str = sqlmodel.Field(default="")
    created_at: str = sqlmodel.Field(default="")  # ISO-8601 UTC


class DBMemoryLike(sqlmodel.SQLModel, table=True):
    """A like on a memory — posted by an authenticated user."""

    __tablename__ = "memory_like"

    id: Optional[int] = sqlmodel.Field(default=None, primary_key=True)
    memory_id: int = sqlmodel.Field(foreign_key="memory.id", index=True)
    user_info_id: int = sqlmodel.Field(foreign_key="userinfo.id")
    liker_name: str = sqlmodel.Field(default="")  # snapshot of display_name at like time
    created_at: str = sqlmodel.Field(default="")  # ISO-8601 UTC


class DBMemoryTranslation(sqlmodel.SQLModel, table=True):
    """A cached translation of a memory's name and description."""

    __tablename__ = "memory_translation"
    __table_args__ = (UniqueConstraint("memory_id", "lang_code"),)

    id: Optional[int] = sqlmodel.Field(default=None, primary_key=True)
    memory_id: int = sqlmodel.Field(foreign_key="memory.id", index=True)
    lang_code: str  # ISO 639-1, e.g. "fr", "de", "pt"
    name: Optional[str] = sqlmodel.Field(default=None)
    description: Optional[str] = sqlmodel.Field(default=None)
    created_at: str = sqlmodel.Field(default="")  # ISO-8601 UTC


class DBShareMemoryContent(sqlmodel.SQLModel, table=True):
    """A memory's name/description re-encrypted under a per-share content key
    (issue #28), so an anonymous share-link holder can decrypt it client-side
    without the owner's CMK. The share key itself is never sent to or stored
    by the server — it lives only in the share URL fragment (`#key=...`).

    1:1 lifecycle with the project's "full" share token: rows are upserted by
    the owner-triggered share-content generation flow and deleted wholesale
    when that token is revoked (see revoke_share_link in api/project_shares.py).
    """

    __tablename__ = "share_memory_content"
    __table_args__ = (UniqueConstraint("memory_id", "token_type"),)

    id: Optional[int] = sqlmodel.Field(default=None, primary_key=True)
    memory_id: int = sqlmodel.Field(foreign_key="memory.id", index=True)
    # "full" — the no-memories share variant never carries memory content by
    # definition, so it has no use for this table.
    token_type: str = sqlmodel.Field(default="full")
    name_ciphertext: Optional[str] = sqlmodel.Field(default=None)
    description_ciphertext: Optional[str] = sqlmodel.Field(default=None)
    created_at: str = sqlmodel.Field(default="")  # ISO-8601 UTC


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


# ---------------------------------------------------------------------------
# E2EE key material (issue #26)
# ---------------------------------------------------------------------------
# The server stores only opaque ciphertext and wrapped keys; it never holds the
# Content Master Key (CMK) in the clear and performs no crypto. See spike/.


class DBDeviceKey(sqlmodel.SQLModel, table=True):
    """A user's per-device X25519 public key and the CMK wrapped to it.

    A new device registers its public key with approved=False; an already-trusted
    device "approves" it by wrapping the CMK to this public key (filling
    wrapped_cmk + ephemeral_public_key and setting approved=True). Basis for the
    passwordless cross-device approval flow.
    """

    __tablename__ = "device_key"

    id: Optional[int] = sqlmodel.Field(default=None, primary_key=True)
    user_info_id: int = sqlmodel.Field(foreign_key="userinfo.id", index=True)
    public_key: str = sqlmodel.Field()           # base64 X25519 device public key
    label: str = sqlmodel.Field(default="")      # e.g. "Chrome on Windows"
    approved: bool = sqlmodel.Field(default=False)
    # CMK wrapped to this device's public key; NULL until approved.
    wrapped_cmk: Optional[str] = sqlmodel.Field(default=None)      # base64 AEAD blob
    ephemeral_public_key: Optional[str] = sqlmodel.Field(default=None)  # base64 X25519
    created_at: float = sqlmodel.Field(default_factory=time.time)


class DBRecoveryWrap(sqlmodel.SQLModel, table=True):
    """The CMK wrapped under a user-chosen recovery method (issue #26).

    method="recovery_key" → wrapped under a high-entropy CSPRNG key (Option A).
    method="qna"          → wrapped under an Argon2id key derived from normalized
                            security-question answers (Option B, weaker).
    """

    __tablename__ = "recovery_wrap"

    id: Optional[int] = sqlmodel.Field(default=None, primary_key=True)
    user_info_id: int = sqlmodel.Field(foreign_key="userinfo.id", index=True)
    method: str = sqlmodel.Field()               # "recovery_key" | "qna"
    wrapped_cmk: str = sqlmodel.Field()          # base64 AEAD blob
    salt: str = sqlmodel.Field()                 # base64 KDF/HKDF salt
    # Argon2id params (memory/iterations/parallelism) for method="qna"; NULL otherwise.
    kdf_params_json: Optional[str] = sqlmodel.Field(default=None)
    version: int = sqlmodel.Field(default=1)
    created_at: float = sqlmodel.Field(default_factory=time.time)
