"""Database repository for projects, activities, and the Strava cache.

Replaces ``ProjectIO`` for the FastAPI endpoints.

Public interface mirrors what the endpoints need:

    repo = ProjectRepo()
    with get_session() as sess:
        project = repo.get_project(sess, user_info_id, name)   # lazy-migrates if needed
        repo.save_project(sess, user_info_id, project)

All methods that write data call ``sess.commit()`` before returning.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from collections import defaultdict
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, func, insert, update

from models.db import get_session
from sqlalchemy.orm import defer as _sa_defer
from sqlmodel import Session, select

# Ensure all SQLModel table classes are registered with SQLAlchemy's metadata
# before any FK resolution happens at query time.
from models.user import UserInfo, StravaToken  # noqa: F401
from models.project_db import DBActivity, DBJournalEntry, DBMemory, DBMemoryComment, DBMemoryLike, DBMemoryTranslation, DBProject, DBProjectItem
from src.models.activity import Activity
from src.models.journal import JournalEntry
from src.models.memory import Memory
from src.models.project import (
    ConnectingSegment,
    Counter,
    DayMeta,
    day_counters_from_json,
    day_counters_to_json,
    DEFAULT_SLEEPING_GROUPS,
    DEFAULT_SLEEPING_OPTIONS,
    Project,
    ProjectFilterState,
    ProjectItem,
    SegmentEndpoint,
)
from src.project.project_io import ProjectIO
from src.project.elevation_downsample import downsample_elevation


def _low_res_ep_json(ep_json: Optional[str]) -> Optional[str]:
    """Downsample a full ``elevation_profile_json`` blob to the low-res form
    stored in ``elevation_profile_low_res_json`` (~300 pts). Returns None when
    the input is missing or unparseable."""
    if not ep_json:
        return None
    try:
        ep = json.loads(ep_json)
        d = ep.get("distances_km") or []
        e = ep.get("elevations_m") or []
        if not d or not e:
            return None
        dd, ee = downsample_elevation(d, e)
        return json.dumps({"distances_km": dd, "elevations_m": ee})
    except Exception:
        return None


def _parse_ep(ep_json: Optional[str]):
    """Parse a stored elevation_profile JSON blob to ``(distances_km, elevations_m)``.

    Returns None when the blob is missing or unparseable.
    """
    if not ep_json:
        return None
    try:
        ep = json.loads(ep_json)
        return (ep.get("distances_km") or [], ep.get("elevations_m") or [])
    except Exception:
        return None


class StaleWriteError(Exception):
    """Raised by save_project when another writer committed since this project
    was loaded (optimistic-lock conflict). Callers should reload and retry, or
    surface a 409 to the client."""


class ProjectRepo:
    """All DB operations for projects and activities."""

    # ------------------------------------------------------------------
    # Project CRUD
    # ------------------------------------------------------------------

    def list_projects(self, sess: Session, user_info_id: int) -> list[dict]:
        """Return [{"name": …, "filename": …}] for all projects owned by user."""
        rows = sess.exec(
            select(DBProject)
            .where(DBProject.user_info_id == user_info_id)
            .order_by(DBProject.name)
        ).all()
        return [{"name": r.name, "filename": r.name + ProjectIO.EXTENSION} for r in rows]

    def project_exists(self, sess: Session, user_info_id: int, name: str) -> bool:
        row = sess.exec(
            select(DBProject).where(
                DBProject.user_info_id == user_info_id,
                DBProject.name == name,
            )
        ).first()
        return row is not None

    def get_project(
        self,
        sess: Session,
        user_info_id: int,
        name: str,
        legacy_path: Optional[str] = None,
        include_heavy: bool = True,
        include_elevation: bool = True,
    ) -> Optional[Project]:
        """Load a project from DB.

        If no DB row exists and *legacy_path* points to a ``.viewtrip`` or ``.gettracks`` file,
        the file is ingested into the DB first (lazy migration).
        Returns ``None`` if neither DB row nor legacy file exists.

        include_heavy=False defers summary_polyline and elevation_profile_json (see
        _row_to_project for details).  The legacy-ingest path always uses full loading.

        include_elevation=False (with include_heavy=True) keeps summary_polyline but
        defers the large elevation_profile_json column — used by the full-res geo
        endpoint, which needs track geometry but never the elevation series. On
        spinning-disk NAS storage this avoids the overflow-page reads that made a
        cold geo load time out.
        """
        row = sess.exec(
            select(DBProject).where(
                DBProject.user_info_id == user_info_id,
                DBProject.name == name,
            )
        ).first()

        if row is None:
            if legacy_path and os.path.isfile(legacy_path):
                self.ingest_project(sess, user_info_id, legacy_path)
                # Re-fetch after ingest
                row = sess.exec(
                    select(DBProject).where(
                        DBProject.user_info_id == user_info_id,
                        DBProject.name == name,
                    )
                ).first()
            if row is None:
                return None

        return self._row_to_project(
            sess, row, include_heavy=include_heavy, include_elevation=include_elevation)

    def get_project_by_id(self, sess: Session, project_id: int) -> Optional[Project]:
        """Load a project directly by its primary key (used for shared-link access)."""
        row = sess.get(DBProject, project_id)
        if row is None:
            return None
        return self._row_to_project(sess, row)

    def get_project_by_id_meta(self, sess: Session, project_id: int) -> Optional[Project]:
        """Like get_project_by_id but defers summary_polyline and elevation_profile_json.

        SQLite must read overflow pages for large TEXT columns even when the value
        is not used in Python.  Deferring those two columns keeps the SELECT result
        small and avoids hundreds of random disk reads on a NAS — cold meta load
        drops from ~19 s to under 1 s on spinning-disk NAS storage.
        Activities returned have summary_polyline=None and elevation_profile=None.
        """
        row = sess.get(DBProject, project_id)
        if row is None:
            return None
        return self._row_to_project(sess, row, include_heavy=False)

    def create_project(self, sess: Session, user_info_id: int, name: str) -> Project:
        """Create an empty project in the DB and return it."""
        empty_project = Project(name=name)
        row = DBProject(
            user_info_id=user_info_id,
            name=name,
            sleeping_options_json=json.dumps([
                {"name": n, "group": DEFAULT_SLEEPING_GROUPS.get(n, 'Other')}
                for n in DEFAULT_SLEEPING_OPTIONS
            ]),
            low_res_geo_json=_compute_low_res_geo(empty_project),
        )
        sess.add(row)
        sess.commit()
        return empty_project

    def save_project(
        self,
        sess: Session,
        user_info_id: int,
        project: Project,
        *,
        check_version: bool = False,
    ) -> None:
        """Persist all changes to an in-memory Project back to the DB.

        This is a full replace of the project's item list and activity upserts.

        Pass ``check_version=True`` for load-then-mutate-then-save flows that
        must not clobber a concurrent write (e.g. the segment endpoints and the
        background route-resolve job): the row's ``lock_version`` is bumped only
        if it still matches the value captured at load time, otherwise a
        ``StaleWriteError`` is raised. The default (``False``) is a blind
        overwrite that simply advances the counter — used by importers and other
        callers that intentionally replace the whole project.
        """
        row = sess.exec(
            select(DBProject).where(
                DBProject.user_info_id == user_info_id,
                DBProject.name == project.name,
            )
        ).first()
        if row is None:
            row = DBProject(user_info_id=user_info_id, name=project.name)
            sess.add(row)
            sess.flush()

        if check_version:
            # Atomic compare-and-swap on lock_version. rowcount 0 → another
            # writer committed since this project was loaded → conflict.
            expected = project.lock_version
            # Use sess.execute (SQLAlchemy native), NOT sess.exec: the latter is
            # SQLModel's SELECT-oriented wrapper and, depending on the installed
            # SQLModel version, may not return a CursorResult with a usable
            # .rowcount for a Core UPDATE — which surfaced as a 500 in production
            # (where the unpinned dependency resolved to a different version).
            result = sess.execute(
                update(DBProject)
                .where(DBProject.id == row.id, DBProject.lock_version == expected)
                .values(lock_version=expected + 1)
            )
            if result.rowcount == 0:
                sess.rollback()
                raise StaleWriteError(
                    f"Project '{project.name}' was modified concurrently "
                    f"(expected lock_version {expected})"
                )
            sess.refresh(row)          # sync the ORM identity map to the new value
            project.lock_version = expected + 1
        else:
            # Blind overwrite — advance the counter so concurrent version-checked
            # savers can still detect that a write happened.
            row.lock_version = (getattr(row, "lock_version", 0) or 0) + 1
            project.lock_version = row.lock_version

        row.version = project.version
        row.trip_start = project.trip_start
        row.trip_end = project.trip_end
        row.filter_state_json = json.dumps({
            "start_date": project.filter_state.start_date,
            "end_date": project.filter_state.end_date,
            "activity_types": project.filter_state.activity_types,
        })
        row.day_meta_json = json.dumps({
            dk: {"difficulty": dm.difficulty, "sleeping": dm.sleeping,
                 "weather": dm.weather, "journal": dm.journal,
                 "tags": dm.tags, "counters": day_counters_to_json(dm.counters)}
            for dk, dm in project.day_meta.items()
        })
        opts = project.sleeping_options if project.sleeping_options else DEFAULT_SLEEPING_OPTIONS
        row.sleeping_options_json = json.dumps([
            {"name": n, "group": project.sleeping_option_groups.get(n, DEFAULT_SLEEPING_GROUPS.get(n, 'Other'))}
            for n in opts
        ])
        row.counters_json = json.dumps([
            {"name": c.name, "start": c.start} for c in project.counters
        ])
        row.track_color = project.track_color
        row.track_secondary_color = project.track_secondary_color
        row.track_width = project.track_width
        row.alternating_track_colors = project.alternating_track_colors
        row.elevation_chart_color = project.elevation_chart_color
        row.elevation_chart_show_line = project.elevation_chart_show_line
        row.languages_json = json.dumps(project.languages)
        row.low_res_geo_json = _compute_low_res_geo(project)
        row.updated_at = time.time()

        # Upsert all activities in the project's activity pool
        for act in project.activities:
            self._upsert_activity(sess, user_info_id, act)

        # Replace the full item list
        sess.flush()  # ensure row.id is available
        self._replace_items(sess, row.id, project.items)

        sess.commit()

    def delete_project(self, sess: Session, user_info_id: int, name: str) -> bool:
        """Delete a project and its items. Activities are NOT deleted (shared).

        Returns True if a project was found and deleted, False if not found.
        """
        row = sess.exec(
            select(DBProject).where(
                DBProject.user_info_id == user_info_id,
                DBProject.name == name,
            )
        ).first()
        if row is None:
            return False

        items = sess.exec(
            select(DBProjectItem).where(DBProjectItem.project_id == row.id)
        ).all()
        for item in items:
            sess.delete(item)

        # Delete memories (photos on disk are left — no user_id available here)
        memories = sess.exec(
            select(DBMemory).where(DBMemory.project_id == row.id)
        ).all()
        for mem in memories:
            sess.delete(mem)

        # Delete journal entries (photos on disk are left — no user_id available here)
        journals = sess.exec(
            select(DBJournalEntry).where(DBJournalEntry.project_id == row.id)
        ).all()
        for jentry in journals:
            sess.delete(jentry)

        sess.delete(row)
        sess.commit()
        return True

    # ------------------------------------------------------------------
    # Activity enrichment (background task writes)
    # ------------------------------------------------------------------

    def update_activity_enrichment(
        self,
        sess: Session,
        activity_id: int,
        summary_polyline: Optional[str],
        elevation_profile_json: Optional[str],
    ) -> None:
        """Update only the enrichment columns of an activity row."""
        row = sess.get(DBActivity, activity_id)
        if row is None:
            return
        if summary_polyline is not None:
            row.summary_polyline = summary_polyline
        if elevation_profile_json is not None:
            row.elevation_profile_json = elevation_profile_json
            row.elevation_profile_low_res_json = _low_res_ep_json(elevation_profile_json)
        sess.commit()

    # ------------------------------------------------------------------
    # Geometry editing (issue #31)
    # ------------------------------------------------------------------

    def activity_is_edited(self, activity_id: int) -> bool:
        """Return True if the activity has a locally edited track.

        Opens its own session so background enrichment tasks (which hold no
        session) can cheaply check before overwriting geometry.
        """
        with get_session() as sess:
            row = sess.get(DBActivity, activity_id)
            return bool(row is not None and row.is_edited)

    @staticmethod
    def _write_track_geometry(row: DBActivity, points: "list") -> None:
        """Re-derive geometry + scalar metrics from *points* onto *row* (no commit).

        Snapshots the pre-edit polyline/elevation into the original_* columns on
        the FIRST edit only, so a later "Reset to Strava" can restore them.
        """
        from src.models.track_edit import (
            align_points,
            points_to_elevation_profile,
            points_to_polyline,
            recompute_track_metrics,
        )

        if not row.is_edited:
            row.original_polyline = row.summary_polyline
            row.original_elevation_profile_json = row.elevation_profile_json

        # Apportion times against the CURRENT geometry's haversine length (not
        # the stored scalar distance, which Strava derives differently). This
        # keeps edit→reset time recovery exact, since reset re-apportions with
        # the same geometry-derived basis.
        prev_metrics = recompute_track_metrics(align_points(
            row.summary_polyline,
            _parse_ep(row.elevation_profile_json),
        ))

        metrics = recompute_track_metrics(
            points,
            original_distance_m=prev_metrics.distance,
            original_moving_time=row.moving_time or 0,
            original_elapsed_time=row.elapsed_time or 0,
        )

        row.summary_polyline = points_to_polyline(points)
        ep = points_to_elevation_profile(points)
        ep_json = (
            json.dumps({"distances_km": ep[0], "elevations_m": ep[1]}) if ep else None
        )
        row.elevation_profile_json = ep_json
        row.elevation_profile_low_res_json = _low_res_ep_json(ep_json)

        row.distance = metrics.distance
        row.total_elevation_gain = metrics.total_elevation_gain
        row.elev_high = metrics.elev_high
        row.elev_low = metrics.elev_low
        row.start_latlng_json = json.dumps(metrics.start_latlng) if metrics.start_latlng else None
        row.end_latlng_json = json.dumps(metrics.end_latlng) if metrics.end_latlng else None
        row.average_speed = metrics.average_speed
        row.moving_time = metrics.moving_time
        row.elapsed_time = metrics.elapsed_time
        row.is_edited = True

    def edit_activity_track(
        self, sess: Session, activity_id: int, points: "list"
    ) -> bool:
        """Apply an edited point list to an activity, recomputing all metrics.

        Snapshots the original geometry on the first edit and sets is_edited.
        Returns False if the activity row does not exist.
        """
        row = sess.get(DBActivity, activity_id)
        if row is None:
            return False
        self._write_track_geometry(row, points)
        sess.commit()
        return True

    def reset_activity_track(self, sess: Session, activity_id: int) -> bool:
        """Restore an edited activity's geometry from its original snapshot.

        Recomputes scalar metrics from the restored geometry and clears
        is_edited + the snapshot columns.  Returns False if the row does not
        exist or was never edited (nothing to reset).
        """
        row = sess.get(DBActivity, activity_id)
        if row is None or not row.is_edited:
            return False

        from src.models.track_edit import align_points, recompute_track_metrics

        orig_poly = row.original_polyline
        orig_ep_json = row.original_elevation_profile_json
        orig_ep = None
        if orig_ep_json:
            ep = json.loads(orig_ep_json)
            orig_ep = (ep.get("distances_km") or [], ep.get("elevations_m") or [])
        points = align_points(orig_poly, orig_ep)

        row.summary_polyline = orig_poly
        row.elevation_profile_json = orig_ep_json
        row.elevation_profile_low_res_json = _low_res_ep_json(orig_ep_json)

        if points:
            # Geometry-derived metrics (distance, elevation, latlng) restore
            # exactly from the snapshot. Scalar times were apportioned DOWN to
            # the retained-distance fraction on edit; scale them back UP by the
            # inverse ratio (restored ÷ edited distance) so a trim→reset round
            # trip recovers the original times too.
            edited_distance = row.distance or 0.0
            metrics = recompute_track_metrics(points)
            row.distance = metrics.distance
            row.total_elevation_gain = metrics.total_elevation_gain
            row.elev_high = metrics.elev_high
            row.elev_low = metrics.elev_low
            row.start_latlng_json = json.dumps(metrics.start_latlng) if metrics.start_latlng else None
            row.end_latlng_json = json.dumps(metrics.end_latlng) if metrics.end_latlng else None
            if edited_distance > 0 and metrics.distance > 0:
                ratio = metrics.distance / edited_distance
                row.moving_time = int(round((row.moving_time or 0) * ratio))
                row.elapsed_time = int(round((row.elapsed_time or 0) * ratio))
                row.average_speed = (
                    metrics.distance / row.moving_time if row.moving_time > 0 else 0.0
                )

        row.is_edited = False
        row.original_polyline = None
        row.original_elevation_profile_json = None
        sess.commit()
        return True

    def force_update_activity(
        self, sess: Session, user_info_id: int, act: Activity
    ) -> None:
        """Overwrite ALL columns of an existing activity row (used for re-fetch).

        If no row exists, inserts a new one.  Unlike ``_upsert_activity``,
        this always overwrites enrichment columns (polyline, elevation).
        """
        if act.id is None:
            return

        def _iso(dt) -> str:
            if dt is None:
                return ""
            return dt.isoformat().replace("+00:00", "Z")

        ep_json: Optional[str] = None
        if act.elevation_profile:
            ep_json = json.dumps({
                "distances_km": act.elevation_profile[0],
                "elevations_m": act.elevation_profile[1],
            })

        existing = sess.get(DBActivity, act.id)
        if existing is None:
            self._upsert_activity(sess, user_info_id, act)
            return

        existing.user_info_id = user_info_id
        existing.name = act.name
        existing.type = act.type
        existing.distance = act.distance
        existing.moving_time = act.moving_time
        existing.elapsed_time = act.elapsed_time
        existing.total_elevation_gain = act.total_elevation_gain
        existing.start_date = _iso(act.start_date)
        existing.start_date_local = _iso(act.start_date_local)
        existing.timezone = act.timezone
        existing.achievement_count = act.achievement_count
        existing.kudos_count = act.kudos_count
        existing.comment_count = act.comment_count
        existing.athlete_count = act.athlete_count
        existing.photo_count = act.photo_count
        existing.pr_count = act.pr_count
        existing.total_photo_count = act.total_photo_count
        existing.trainer = act.trainer
        existing.commute = act.commute
        existing.manual = act.manual
        existing.private = act.private
        existing.flagged = act.flagged
        existing.has_heartrate = act.has_heartrate
        existing.has_kudoed = act.has_kudoed
        existing.heartrate_opt_out = act.heartrate_opt_out
        existing.display_hide_heartrate_option = act.display_hide_heartrate_option
        existing.average_speed = act.average_speed
        existing.max_speed = act.max_speed
        existing.gear_id = act.gear_id
        existing.average_heartrate = act.average_heartrate
        existing.max_heartrate = act.max_heartrate
        existing.elev_high = act.elev_high
        existing.elev_low = act.elev_low
        existing.start_latlng_json = json.dumps(act.start_latlng) if act.start_latlng else None
        existing.end_latlng_json = json.dumps(act.end_latlng) if act.end_latlng else None
        existing.summary_polyline = act.summary_polyline
        existing.elevation_profile_json = ep_json
        existing.elevation_profile_low_res_json = _low_res_ep_json(ep_json)
        sess.commit()

    # ------------------------------------------------------------------
    # Stats computation + caching
    # ------------------------------------------------------------------

    def compute_and_cache_stats(
        self, sess: Session, user_info_id: int, name: str
    ) -> None:
        """Compute project statistics and persist them to DBProject.stats_json."""
        row = sess.exec(
            select(DBProject).where(
                DBProject.user_info_id == user_info_id,
                DBProject.name == name,
            )
        ).first()
        if row is None:
            return
        project = self._row_to_project(sess, row)
        row.stats_json = json.dumps(_compute_stats(project))
        row.updated_at = time.time()
        sess.add(row)
        sess.commit()

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self, project: Project) -> dict:
        """Return the project as a REST-API-ready dict (same contract as ProjectIO.to_dict)."""
        return ProjectIO.to_dict(project)

    # ------------------------------------------------------------------
    # Legacy migration
    # ------------------------------------------------------------------

    def ingest_project(
        self, sess: Session, user_info_id: int, path: str
    ) -> None:
        """Parse a ``.viewtrip`` (or legacy ``.gettracks``) file and write it into the DB.

        The DB project name is derived from the **filename** (minus extension)
        so it stays consistent with the URL slug the API has always used.

        Idempotent: if the project already exists in the DB, the call is a
        no-op.  Activity rows are upserted so enriched data is never overwritten.

        After a successful ingest the file is renamed to ``*.migrated``
        so repeated calls are O(1) rather than re-reading the file each time.
        """
        # Use the filename-derived name as the DB key (matches the legacy URL slug)
        basename = os.path.basename(path)
        ext = ProjectIO.EXTENSION if basename.endswith(ProjectIO.EXTENSION) else ProjectIO.LEGACY_EXTENSION
        db_name = basename[: -len(ext)] if basename.endswith((ProjectIO.EXTENSION, ProjectIO.LEGACY_EXTENSION)) else basename

        project = ProjectIO.load(path)

        # Check for existing project before inserting
        row = sess.exec(
            select(DBProject).where(
                DBProject.user_info_id == user_info_id,
                DBProject.name == db_name,
            )
        ).first()
        if row is not None:
            # Already migrated — just rename the file and return
            self._mark_migrated(path)
            return

        # 1. Upsert activities (do NOT overwrite enriched data if row exists)
        for act in project.activities:
            self._upsert_activity(sess, user_info_id, act)

        # 2. Create project row (name = filename slug, version from JSON)
        row = DBProject(
            user_info_id=user_info_id,
            name=db_name,
            version=project.version,
            filter_state_json=json.dumps({
                "start_date": project.filter_state.start_date,
                "end_date": project.filter_state.end_date,
                "activity_types": project.filter_state.activity_types,
            }),
            day_meta_json=json.dumps({
                dk: {"difficulty": dm.difficulty, "sleeping": dm.sleeping,
                     "weather": dm.weather, "journal": dm.journal,
                     "tags": dm.tags}
                for dk, dm in project.day_meta.items()
            }),
            sleeping_options_json=json.dumps(project.sleeping_options),
            low_res_geo_json=_compute_low_res_geo(project),
        )
        sess.add(row)
        sess.flush()  # populate row.id

        # 3. Create project_item rows
        for pos, item in enumerate(project.items):
            memory_id: Optional[int] = None
            if item.item_type == "memory" and item.memory is not None:
                # Persist the memory row so we get its DB id
                mem = item.memory
                mem_row = DBMemory(
                    project_id=row.id,
                    public_id=mem.public_id or uuid.uuid4().hex,
                    name=mem.name,
                    date=mem.date,
                    time=mem.time,
                    description=mem.description,
                    photos_json=json.dumps(mem.photos),
                    geo_mode=mem.geo_mode,
                    lat=mem.lat,
                    lon=mem.lon,
                )
                sess.add(mem_row)
                sess.flush()
                memory_id = mem_row.id

            db_item = DBProjectItem(
                project_id=row.id,
                position=pos,
                item_type=item.item_type,
                activity_id=item.activity_id if item.item_type == "activity" else None,
                segment_json=(
                    json.dumps(ProjectIO._serialise_item(item)["segment"])
                    if item.item_type == "segment" else None
                ),
                memory_id=memory_id,
            )
            sess.add(db_item)

        sess.commit()
        self._mark_migrated(path)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _row_to_project(self, sess: Session, row: DBProject, include_heavy: bool = True,
                        include_elevation: bool = True) -> Project:
        """Reconstruct an in-memory Project from DB rows.

        include_heavy=False defers summary_polyline and elevation_profile_json from
        the SQL query, avoiding overflow-page reads on large activities.  Activities
        will have summary_polyline=None and elevation_profile=None.

        include_elevation=False (with include_heavy=True) defers only
        elevation_profile_json: summary_polyline is loaded, elevation_profile is None.
        """
        fs_raw = json.loads(row.filter_state_json or "{}")
        filter_state = ProjectFilterState(
            start_date=fs_raw.get("start_date"),
            end_date=fs_raw.get("end_date"),
            activity_types=fs_raw.get("activity_types"),
        )

        item_rows = sess.exec(
            select(DBProjectItem)
            .where(DBProjectItem.project_id == row.id)
            .order_by(DBProjectItem.position)
        ).all()

        # Collect activity IDs needed for this project
        activity_ids = [
            r.activity_id for r in item_rows
            if r.item_type == "activity" and r.activity_id is not None
        ]
        _act_query = select(DBActivity).where(DBActivity.id.in_(activity_ids))
        if not include_heavy:
            _act_query = _act_query.options(
                _sa_defer(DBActivity.summary_polyline),
                _sa_defer(DBActivity.elevation_profile_json),
            )
        elif not include_elevation:
            _act_query = _act_query.options(
                _sa_defer(DBActivity.elevation_profile_json),
            )
        act_rows = sess.exec(_act_query).all() if activity_ids else []
        act_by_id = {
            r.id: self._row_to_activity(
                r, include_heavy=include_heavy, include_elevation=include_elevation)
            for r in act_rows
        }

        # Load memory rows for this project
        memory_rows = sess.exec(
            select(DBMemory).where(DBMemory.project_id == row.id)
        ).all()

        # Batch-load comment and like counts for all memories in one query each
        memory_ids = [mr.id for mr in memory_rows if mr.id is not None]
        comment_counts: Dict[int, int] = {}
        like_counts: Dict[int, int] = {}
        if memory_ids:
            for mid, cnt in sess.exec(
                select(DBMemoryComment.memory_id, func.count(DBMemoryComment.id).label("cnt"))
                .where(DBMemoryComment.memory_id.in_(memory_ids))
                .group_by(DBMemoryComment.memory_id)
            ).all():
                comment_counts[mid] = cnt
            for mid, cnt in sess.exec(
                select(DBMemoryLike.memory_id, func.count(DBMemoryLike.id).label("cnt"))
                .where(DBMemoryLike.memory_id.in_(memory_ids))
                .group_by(DBMemoryLike.memory_id)
            ).all():
                like_counts[mid] = cnt

        memory_by_id: Dict[int, Memory] = {}
        for mr in memory_rows:
            mem = self._row_to_memory(mr)
            mem.comment_count = comment_counts.get(mr.id, 0)
            mem.like_count = like_counts.get(mr.id, 0)
            memory_by_id[mr.id] = mem

        # Load journal entry rows for this project
        journal_rows = sess.exec(
            select(DBJournalEntry).where(DBJournalEntry.project_id == row.id)
        ).all()
        journal_by_id = {jr.id: self._row_to_journal(jr) for jr in journal_rows}

        items: List[ProjectItem] = []
        activities: List[Activity] = []
        memories: List[Memory] = []
        journal_entries: List[JournalEntry] = []
        seen_ids: set[int] = set()
        seen_memory_ids: set[int] = set()
        seen_journal_ids: set[int] = set()

        for ir in item_rows:
            if ir.item_type == "activity" and ir.activity_id is not None:
                items.append(ProjectItem(item_type="activity", activity_id=ir.activity_id))
                if ir.activity_id not in seen_ids:
                    act = act_by_id.get(ir.activity_id)
                    if act:
                        activities.append(act)
                        seen_ids.add(ir.activity_id)
            elif ir.item_type == "memory" and ir.memory_id is not None:
                if ir.memory_id in seen_memory_ids:
                    continue  # deduplicate stale duplicate rows
                mem = memory_by_id.get(ir.memory_id)
                if mem:
                    items.append(ProjectItem(item_type="memory", memory=mem))
                    memories.append(mem)
                    seen_memory_ids.add(ir.memory_id)
            elif ir.item_type == "journal" and ir.journal_id is not None:
                if ir.journal_id in seen_journal_ids:
                    continue  # deduplicate stale duplicate rows
                jentry = journal_by_id.get(ir.journal_id)
                if jentry:
                    items.append(ProjectItem(item_type="journal", journal=jentry))
                    journal_entries.append(jentry)
                    seen_journal_ids.add(ir.journal_id)
            else:
                seg = self._json_to_segment(ir.segment_json or "{}")
                items.append(ProjectItem(item_type="segment", segment=seg))

        raw_dm = json.loads(getattr(row, 'day_meta_json', None) or "{}")
        day_meta = {
            dk: DayMeta(
                difficulty=v.get("difficulty"),
                sleeping=v.get("sleeping"),
                weather=v.get("weather"),
                journal=v.get("journal"),
                tags=v.get("tags") or [],
                counters=day_counters_from_json(v.get("counters")),
            )
            for dk, v in raw_dm.items()
        }
        raw_opts = json.loads(getattr(row, 'sleeping_options_json', None) or "[]")
        sleeping_options: list = []
        sleeping_option_groups: dict = {}
        for item in (raw_opts if isinstance(raw_opts, list) and raw_opts else DEFAULT_SLEEPING_OPTIONS):
            if isinstance(item, str):
                sleeping_options.append(item)
                sleeping_option_groups[item] = DEFAULT_SLEEPING_GROUPS.get(item, 'Other')
            else:
                name = item['name']
                sleeping_options.append(name)
                sleeping_option_groups[name] = item.get('group', DEFAULT_SLEEPING_GROUPS.get(name, 'Other'))

        raw_counters = json.loads(getattr(row, 'counters_json', None) or "[]")
        counters = [
            Counter(name=c['name'], start=float(c.get('start', 0)))
            for c in raw_counters if isinstance(c, dict)
        ]

        project = Project(
            name=row.name,
            version=row.version,
            lock_version=getattr(row, 'lock_version', 0) or 0,
            trip_start=getattr(row, 'trip_start', None),
            trip_end=getattr(row, 'trip_end', None),
            items=items,
            filter_state=filter_state,
            activities=activities,
            memories=memories,
            journal_entries=journal_entries,
            day_meta=day_meta,
            sleeping_options=sleeping_options,
            sleeping_option_groups=sleeping_option_groups,
            counters=counters,
            track_color=getattr(row, 'track_color', None) or "#F97316",
            track_secondary_color=getattr(row, 'track_secondary_color', None) or None,
            track_width=float(getattr(row, 'track_width', None) or 2.5),
            alternating_track_colors=bool(getattr(row, 'alternating_track_colors', False)),
            elevation_chart_color=getattr(row, 'elevation_chart_color', None),
            elevation_chart_show_line=bool(getattr(row, 'elevation_chart_show_line', True)),
            languages=json.loads(getattr(row, 'languages_json', None) or "[]"),
        )
        project.rebuild_map()
        return project

    def _replace_items(
        self, sess: Session, project_id: int, items: List[ProjectItem]
    ) -> None:
        """Delete all existing project_item rows and insert fresh ones.

        Uses a single bulk DELETE and a single bulk INSERT instead of O(N)
        individual ORM calls — reduces 400 SQL statements to 2 for a 200-item
        project.
        """
        sess.execute(delete(DBProjectItem).where(DBProjectItem.project_id == project_id))

        if not items:
            return

        rows = []
        for pos, item in enumerate(items):
            rows.append({
                "project_id": project_id,
                "position": pos,
                "item_type": item.item_type,
                "activity_id": item.activity_id if item.item_type == "activity" else None,
                "segment_json": (
                    json.dumps(ProjectIO._serialise_item(item)["segment"])
                    if item.item_type == "segment" else None
                ),
                "memory_id": (
                    item.memory.id
                    if item.item_type == "memory" and item.memory is not None
                    else None
                ),
                "journal_id": (
                    item.journal.id
                    if item.item_type == "journal" and item.journal is not None
                    else None
                ),
            })

        sess.execute(insert(DBProjectItem).values(rows))

    def _upsert_activity(
        self, sess: Session, user_info_id: int, act: Activity
    ) -> None:
        """Insert the activity row if it doesn't exist; skip if it does.

        Enriched data (summary_polyline, elevation_profile) is only written
        for new rows — existing rows may already have richer data from a
        previous enrichment pass.
        """
        if act.id is None:
            return
        existing = sess.get(DBActivity, act.id)
        if existing is not None:
            # Update mutable user-visible fields always.
            existing.name = act.name
            existing.kudos_count = act.kudos_count
            existing.achievement_count = act.achievement_count
            # If the stored polyline is null but the incoming one is not, take
            # the incoming value — the user may have fixed their Strava map
            # privacy and re-synced, or the first sync happened to return null.
            if existing.summary_polyline is None and act.summary_polyline:
                existing.summary_polyline = act.summary_polyline
            return

        def _iso(dt) -> str:
            if dt is None:
                return ""
            return dt.isoformat().replace("+00:00", "Z")

        _ep_json = (
            json.dumps({
                "distances_km": act.elevation_profile[0],
                "elevations_m": act.elevation_profile[1],
            })
            if act.elevation_profile else None
        )

        row = DBActivity(
            id=act.id,
            user_info_id=user_info_id,
            name=act.name,
            type=act.type,
            distance=act.distance,
            moving_time=act.moving_time,
            elapsed_time=act.elapsed_time,
            total_elevation_gain=act.total_elevation_gain,
            start_date=_iso(act.start_date),
            start_date_local=_iso(act.start_date_local),
            timezone=act.timezone,
            achievement_count=act.achievement_count,
            kudos_count=act.kudos_count,
            comment_count=act.comment_count,
            athlete_count=act.athlete_count,
            photo_count=act.photo_count,
            pr_count=act.pr_count,
            total_photo_count=act.total_photo_count,
            trainer=act.trainer,
            commute=act.commute,
            manual=act.manual,
            private=act.private,
            flagged=act.flagged,
            has_heartrate=act.has_heartrate,
            has_kudoed=act.has_kudoed,
            heartrate_opt_out=act.heartrate_opt_out,
            display_hide_heartrate_option=act.display_hide_heartrate_option,
            average_speed=act.average_speed,
            max_speed=act.max_speed,
            gear_id=act.gear_id,
            average_heartrate=act.average_heartrate,
            max_heartrate=act.max_heartrate,
            elev_high=act.elev_high,
            elev_low=act.elev_low,
            start_latlng_json=json.dumps(act.start_latlng) if act.start_latlng else None,
            end_latlng_json=json.dumps(act.end_latlng) if act.end_latlng else None,
            summary_polyline=act.summary_polyline,
            elevation_profile_json=_ep_json,
            elevation_profile_low_res_json=_low_res_ep_json(_ep_json),
        )
        sess.add(row)

    @staticmethod
    def _row_to_journal(row: DBJournalEntry) -> JournalEntry:
        return JournalEntry(
            id=row.id,
            project_id=row.project_id,
            date=row.date,
            time=row.time,
            description=row.description,
            photos=json.loads(row.photos_json or "[]"),
            geo_mode=row.geo_mode,
            lat=row.lat,
            lon=row.lon,
        )

    @staticmethod
    def _row_to_memory(row: DBMemory) -> Memory:
        return Memory(
            id=row.id,
            public_id=row.public_id,
            project_id=row.project_id,
            name=row.name,
            date=row.date,
            time=row.time,
            description=row.description,
            photos=json.loads(row.photos_json or "[]"),
            geo_mode=row.geo_mode,
            lat=row.lat,
            lon=row.lon,
        )

    @staticmethod
    def _row_to_activity(row: DBActivity, include_heavy: bool = True,
                         include_elevation: bool = True) -> Activity:
        """Reconstruct the domain Activity dataclass from a DB row.

        include_heavy=False skips accessing deferred columns summary_polyline and
        elevation_profile_json (both returned as None).  The caller must have queried
        with those columns deferred so that no lazy-load round-trip is triggered.

        include_elevation=False skips only elevation_profile_json (summary_polyline
        is still read); the caller must have deferred that column.
        """
        from datetime import datetime

        def _dt(s: str) -> datetime:
            if not s:
                return datetime.now()
            return datetime.fromisoformat(s.replace("Z", "+00:00"))

        return Activity(
            id=row.id,
            name=row.name,
            type=row.type,
            distance=row.distance,
            moving_time=row.moving_time,
            elapsed_time=row.elapsed_time,
            total_elevation_gain=row.total_elevation_gain,
            start_date=_dt(row.start_date),
            start_date_local=_dt(row.start_date_local),
            timezone=row.timezone,
            achievement_count=row.achievement_count,
            kudos_count=row.kudos_count,
            comment_count=row.comment_count,
            athlete_count=row.athlete_count,
            photo_count=row.photo_count,
            trainer=row.trainer,
            commute=row.commute,
            manual=row.manual,
            private=row.private,
            flagged=row.flagged,
            average_speed=row.average_speed,
            max_speed=row.max_speed,
            has_heartrate=row.has_heartrate,
            pr_count=row.pr_count,
            total_photo_count=row.total_photo_count,
            has_kudoed=row.has_kudoed,
            gear_id=row.gear_id,
            average_heartrate=row.average_heartrate,
            max_heartrate=row.max_heartrate,
            heartrate_opt_out=row.heartrate_opt_out,
            display_hide_heartrate_option=row.display_hide_heartrate_option,
            elev_high=row.elev_high,
            elev_low=row.elev_low,
            start_latlng=json.loads(row.start_latlng_json) if row.start_latlng_json else None,
            end_latlng=json.loads(row.end_latlng_json) if row.end_latlng_json else None,
            summary_polyline=row.summary_polyline if include_heavy else None,
            elevation_profile=(
                (
                    ep["distances_km"],
                    ep["elevations_m"],
                )
                if include_heavy and include_elevation and (ep := (json.loads(row.elevation_profile_json) if row.elevation_profile_json else None))
                else None
            ),
            # Always loaded — lightweight, never deferred — so meta/low-res
            # responses can render the chart before the full profile arrives.
            elevation_profile_low_res=(
                (lr["distances_km"], lr["elevations_m"])
                if (lr := (json.loads(row.elevation_profile_low_res_json)
                           if row.elevation_profile_low_res_json else None))
                else None
            ),
            is_edited=bool(getattr(row, "is_edited", False)),
        )

    @staticmethod
    def _json_to_segment(segment_json: str) -> ConnectingSegment:
        """Deserialise a segment JSON blob back to a ConnectingSegment."""
        sd = json.loads(segment_json) if segment_json else {}
        return ConnectingSegment(
            id=sd.get("id", ""),
            segment_type=sd.get("segment_type", "flight"),
            label=sd.get("label", ""),
            date=sd.get("date"),
            start=SegmentEndpoint(
                lat=sd.get("start", {}).get("lat", 0.0),
                lon=sd.get("start", {}).get("lon", 0.0),
                source=sd.get("start", {}).get("source", "auto"),
            ),
            end=SegmentEndpoint(
                lat=sd.get("end", {}).get("lat", 0.0),
                lon=sd.get("end", {}).get("lon", 0.0),
                source=sd.get("end", {}).get("source", "auto"),
            ),
            route_mode=sd.get("route_mode", "great_circle"),
            train_number=sd.get("train_number"),
            hafas_provider=sd.get("hafas_provider"),
            route_polyline=sd.get("route_polyline"),
            route_status=sd.get("route_status", "idle"),
            route_error=sd.get("route_error"),
            route_started_at=sd.get("route_started_at"),
            route_degraded=sd.get("route_degraded", False),
        )

    @staticmethod
    def _mark_migrated(path: str) -> None:
        """Rename a project file to *.migrated to prevent re-ingestion."""
        try:
            os.rename(path, path + ".migrated")
        except OSError:
            pass  # not critical — ingest is idempotent anyway


# ---------------------------------------------------------------------------
# Module-level low-res geo helper
# ---------------------------------------------------------------------------

def _compute_low_res_geo(project: Project) -> str:
    """Build a low-res GeoJSON FeatureCollection for *project*.

    Each activity is represented as a 2-point straight line from
    ``start_latlng`` to ``end_latlng`` — no polyline decoding required.
    Connecting segments use the same 50-point great-circle arcs as the
    full-res endpoint (they're already cheap to compute).
    """
    from src.models.great_circle import great_circle_points

    features = []
    for item in project.items:
        if item.item_type == "activity":
            act = project.activity_by_id(item.activity_id)
            if act is None or not act.start_latlng or not act.end_latlng:
                continue
            coords = [
                [act.start_latlng[1], act.start_latlng[0]],
                [act.end_latlng[1],   act.end_latlng[0]],
            ]
            features.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "type": "activity",
                    "activity_id": act.id,
                    "name": act.name,
                    "sport_type": act.type,
                },
            })
        elif item.item_type == "segment" and item.segment is not None:
            seg = item.segment
            if seg.route_mode in ("rail", "ferry", "bus") and seg.route_polyline:
                coords = json.loads(seg.route_polyline)
            else:
                pts = great_circle_points(
                    seg.start.lat, seg.start.lon,
                    seg.end.lat,   seg.end.lon,
                    n_points=50,
                )
                coords = [[lon, lat] for lat, lon in pts]
            if len(coords) < 2:
                continue
            features.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "type": "segment",
                    "segment_id": seg.id,
                    "segment_type": seg.segment_type,
                    "label": seg.label,
                    "route_mode": seg.route_mode,
                    "route_degraded": seg.route_degraded,
                },
            })

    return json.dumps({"type": "FeatureCollection", "features": features})


# ---------------------------------------------------------------------------
# Module-level stats helpers (outside the class so they can be tested standalone)
# ---------------------------------------------------------------------------

def _compute_counter_stats(
    project: Project, allowed_dates: Optional[set] = None
) -> List[Dict[str, Any]]:
    result = []
    for ctr in project.counters:
        deltas = {}
        for dk, dm in project.day_meta.items():
            day_total = sum(e.value for e in dm.counters if e.name == ctr.name)
            if any(e.name == ctr.name for e in dm.counters):
                deltas[dk] = day_total
        if allowed_dates is not None:
            deltas = {dk: v for dk, v in deltas.items() if dk in allowed_dates}
        cumulative = ctr.start
        series = []
        for dk in sorted(deltas):
            cumulative += deltas[dk]
            series.append({"date": dk, "value": cumulative})
        result.append({"name": ctr.name, "start": ctr.start, "total": cumulative, "series": series})
    return result


def _compute_stats(project: Project, tag_filter: Optional[List[str]] = None) -> Dict[str, Any]:
    """Compute all project statistics from an in-memory Project.

    Returns a dict that is stored as ``DBProject.stats_json``.
    When *tag_filter* is non-empty, only activities whose date falls on a day
    tagged with at least one of the filter tags are included.
    """
    from src.models.great_circle import haversine_km

    # ── Derive tag_options (all tags defined on any day) ────────────────────
    tag_options: List[str] = sorted({
        t
        for meta in project.day_meta.values()
        for t in (meta.tags or [])
    })

    # ── Build allowed-dates set when tag filter is active ───────────────────
    allowed_dates: Optional[set] = None
    if tag_filter:
        tag_set = set(tag_filter)
        allowed_dates = {
            date_key
            for date_key, meta in project.day_meta.items()
            if tag_set & set(meta.tags or [])
        }

    # ── Aggregate totals over activities (filtered if needed) ────────────────
    total_dist_m = 0.0
    total_moving_s = 0
    total_elev_m = 0.0

    activity_counts: Dict[str, int] = defaultdict(int)     # type → count
    ride_day_dist: Dict[str, float] = defaultdict(float)   # date → metres
    ride_day_elev: Dict[str, float] = defaultdict(float)   # date → metres
    ride_day_time_s: Dict[str, int] = defaultdict(int)     # date → moving seconds
    ride_total_elev_m = 0.0

    for a in project.activities:
        # Apply tag filter: skip activities not on an allowed date
        if allowed_dates is not None:
            act_date: Optional[str] = None
            if a.start_date_local is not None:
                try:
                    act_date = a.start_date_local.date().isoformat()
                except AttributeError:
                    act_date = str(a.start_date_local)[:10]
            if act_date not in allowed_dates:
                continue
        total_dist_m   += a.distance or 0.0
        total_moving_s += a.moving_time or 0
        total_elev_m   += a.total_elevation_gain or 0.0

        atype = (a.type or "other").lower()
        activity_counts[atype] += 1

        if atype == "ride":
            ride_total_elev_m += a.total_elevation_gain or 0.0
            date_key: Optional[str] = None
            if a.start_date_local is not None:
                # start_date_local may be a datetime or an ISO string
                try:
                    date_key = a.start_date_local.date().isoformat()  # datetime
                except AttributeError:
                    date_key = str(a.start_date_local)[:10]           # string fallback
            if date_key:
                ride_day_dist[date_key] += a.distance or 0.0
                ride_day_elev[date_key] += a.total_elevation_gain or 0.0
                ride_day_time_s[date_key] += a.moving_time or 0

    ride_days = len(ride_day_dist)
    ride_dist_m = sum(ride_day_dist.values())
    ride_avg_dist_per_day_m = ride_dist_m / ride_days if ride_days else 0.0

    if ride_day_dist:
        best_dist_day = max(ride_day_dist, key=lambda k: ride_day_dist[k])
        best_dist_m   = ride_day_dist[best_dist_day]
        best_elev_day = max(ride_day_elev, key=lambda k: ride_day_elev[k])
        best_elev_m   = ride_day_elev[best_elev_day]
    else:
        best_dist_day = best_elev_day = None
        best_dist_m   = best_elev_m   = 0.0

    # ── Sleeping counts ──────────────────────────────────────────────────────
    sleeping_counts: Dict[str, int] = defaultdict(int)
    for date_key, meta in project.day_meta.items():
        if allowed_dates is not None and date_key not in allowed_dates:
            continue
        label = meta.sleeping if meta.sleeping else "No data"
        sleeping_counts[label] += 1

    # ── Ride distance per tag (always over all activities, ignores tag_filter) ─
    dist_per_tag: Dict[str, float] = {}
    if tag_options:
        date_tags: Dict[str, list] = {
            dk: list(meta.tags or [])
            for dk, meta in project.day_meta.items()
        }
        for a in project.activities:
            if (a.type or "other").lower() != "ride":
                continue
            if a.start_date_local is None:
                continue
            try:
                act_date = a.start_date_local.date().isoformat()
            except AttributeError:
                act_date = str(a.start_date_local)[:10]
            for tag in date_tags.get(act_date, []):
                dist_per_tag[tag] = dist_per_tag.get(tag, 0.0) + (a.distance or 0.0)

    # ── Distance + counts by segment type ───────────────────────────────────
    seg_dist: Dict[str, float] = {"train": 0.0, "flight": 0.0, "boat": 0.0, "bus": 0.0}
    seg_counts: Dict[str, int] = defaultdict(int)
    for item in project.items:
        if item.item_type == "segment" and item.segment is not None:
            seg = item.segment
            km = haversine_km(seg.start.lat, seg.start.lon, seg.end.lat, seg.end.lon)
            if seg.segment_type in seg_dist:
                seg_dist[seg.segment_type] += km * 1000.0
            seg_counts[seg.segment_type] += 1

    return {
        "total_distance_m":      total_dist_m,
        "total_moving_s":        total_moving_s,
        "total_elevation_m":     total_elev_m,
        "activity_counts":       dict(activity_counts),
        "segment_counts":        dict(seg_counts),
        "ride_days":             ride_days,
        "ride_avg_dist_per_day_m": ride_avg_dist_per_day_m,
        "ride_total_elev_m":     ride_total_elev_m,
        "best_ride_dist_m":      best_dist_m,
        "best_ride_dist_day":    best_dist_day,
        "best_ride_elev_m":      best_elev_m,
        "best_ride_elev_day":    best_elev_day,
        "distance_by_mode": {
            "ride":   ride_dist_m,
            "train":  seg_dist["train"],
            "flight": seg_dist["flight"],
            "boat":   seg_dist["boat"],
            "bus":    seg_dist["bus"],
        },
        "sleeping_counts": dict(sleeping_counts),
        "sleeping_option_groups": {
            n: project.sleeping_option_groups.get(n, DEFAULT_SLEEPING_GROUPS.get(n, 'Other'))
            for n in project.sleeping_options
        },
        "tag_options": tag_options,
        "distance_per_tag": dist_per_tag,
        "counters": _compute_counter_stats(project, allowed_dates),
        "ride_time_series": [
            {
                "date": d,
                "distance_m": ride_day_dist[d],
                "moving_time_s": ride_day_time_s[d],
                "avg_speed_ms": ride_day_dist[d] / ride_day_time_s[d] if ride_day_time_s[d] else 0.0,
                "elevation_m": ride_day_elev[d],
            }
            for d in sorted(ride_day_dist)
        ],
    }
