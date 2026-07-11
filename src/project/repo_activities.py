"""Activity persistence, enrichment writes, and geometry editing (issue #31).

Part of the ``ProjectRepo`` mixin split — see ``src/project/project_repo.py``
for the composed class and module docstring.
"""
from __future__ import annotations

import json
from typing import List, Optional

from sqlalchemy import delete, func
from sqlmodel import Session, select

from models.db import get_session
from models.project_db import DBActivity, DBProjectItem
from src.models.activity import Activity
from src.project.elevation_downsample import downsample_elevation
from src.utils.encryption_check import is_encrypted_envelope


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


class ActivityMixin:
    """Activity CRUD, enrichment writes, and track-geometry editing."""

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
        """Update only the enrichment columns of an activity row.

        Skips a field whose EXISTING value is already a client-side E2EE
        ciphertext envelope (issue #29) — once a field is encrypted, a
        background Strava enrichment pass (which only ever has fresh plaintext
        streams) must not silently overwrite it back to plaintext.
        """
        row = sess.get(DBActivity, activity_id)
        if row is None:
            return
        if summary_polyline is not None and not is_encrypted_envelope(row.summary_polyline):
            row.summary_polyline = summary_polyline
        if elevation_profile_json is not None and not is_encrypted_envelope(row.elevation_profile_json):
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

    def split_activity(
        self,
        sess: Session,
        user_info_id: int,
        project_id: int,
        activity_id: int,
        split_index: int,
    ) -> Optional[int]:
        """Split an activity into a head (keeps id) and a local tail (negative id).

        The boundary point at *split_index* is shared: the head keeps
        ``points[:split_index+1]`` and the tail gets ``points[split_index:]`` so
        the two pieces stay contiguous. The tail is a new LOCAL activity
        (``manual=True``, synthetic negative id, name ``"<name> (2)"``) inserted
        into the project items directly after the head. Both pieces are marked
        is_edited with their own geometry snapshot.

        Returns the new tail activity id, or None if the activity is missing.
        Raises ValueError if *split_index* does not yield two non-trivial pieces.
        """
        from src.models.track_edit import align_points, points_to_polyline

        head = sess.get(DBActivity, activity_id)
        if head is None:
            return None

        points = align_points(head.summary_polyline, _parse_ep(head.elevation_profile_json))
        # Need at least 2 points on each side of the boundary.
        if split_index < 1 or split_index > len(points) - 2:
            raise ValueError(
                f"split_index {split_index} out of range for a {len(points)}-point track")

        head_points = points[: split_index + 1]
        tail_points = points[split_index:]

        # Allocate the next free negative id. activity.id is a GLOBAL primary key,
        # and split tails are LOCAL rows keyed by negative id. Scanning only this
        # project's timeline items is unsafe: a previously-split tail whose item
        # was removed from the timeline leaves the activity row orphaned (see
        # delete_item / remove_item — they unlink the item but do not delete the
        # row), so this project's items no longer reference it and the id gets
        # reused → INSERT collides (UNIQUE constraint failed: activity.id). Derive
        # the next id from the activity table itself, which sees orphans too.
        global_min = sess.exec(select(func.min(DBActivity.id))).one()
        tail_id = min(0, global_min or 0) - 1

        # Create the tail row copying the head's metadata.
        tail = DBActivity(
            id=tail_id,
            user_info_id=user_info_id,
            name=f"{head.name} (2)",
            type=head.type,
            moving_time=head.moving_time,
            elapsed_time=head.elapsed_time,
            start_date=head.start_date,
            start_date_local=head.start_date_local,
            timezone=head.timezone,
            trainer=head.trainer,
            commute=head.commute,
            manual=True,
            private=head.private,
            gear_id=head.gear_id,
        )
        # Seed the tail with the FULL pre-split geometry + the original scalar
        # times so _write_track_geometry apportions the tail's time to its own
        # retained fraction (tail_length / full_length), mirroring the head.
        tail.summary_polyline = head.summary_polyline
        tail.elevation_profile_json = head.elevation_profile_json
        sess.add(tail)

        # Write head then tail geometry (each snapshots its own original + recomputes).
        self._write_track_geometry(head, head_points)
        # The tail begins at the split boundary — i.e. where the head ends. Tracks
        # carry no per-point timestamps, so derive the boundary time as the head's
        # start plus its (now apportioned) elapsed duration. Without this the tail
        # inherits the head's start_date and sorts out of order (often *before* the
        # head, since its negative id wins date ties). start_date columns are stored
        # as ISO-8601 strings, so parse → shift → re-serialise in the same format.
        from datetime import datetime, timedelta

        def _shift(iso: str) -> str:
            if not iso:
                return iso
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            return (dt + timedelta(seconds=head.elapsed_time or 0)) \
                .isoformat().replace("+00:00", "Z")

        tail.start_date = _shift(head.start_date)
        tail.start_date_local = _shift(head.start_date_local)
        self._write_track_geometry(tail, tail_points)

        # Insert the tail item directly after the head item, renumbering positions.
        item_rows = sess.exec(
            select(DBProjectItem)
            .where(DBProjectItem.project_id == project_id)
            .order_by(DBProjectItem.position)
        ).all()
        new_order: List[DBProjectItem] = []
        for it in item_rows:
            new_order.append(it)
            if it.item_type == "activity" and it.activity_id == activity_id:
                new_order.append(DBProjectItem(
                    project_id=project_id, position=0,
                    item_type="activity", activity_id=tail_id,
                ))
        for pos, it in enumerate(new_order):
            it.position = pos
            sess.add(it)

        sess.commit()
        return tail_id

    def delete_local_activity(
        self, sess: Session, project_id: int, activity_id: int
    ) -> bool:
        """Delete a LOCAL (negative-id) activity row and unlink it from items.

        Only local activities (split tails, id < 0) may be deleted — Strava
        activities are shared across projects and must never be row-deleted here.
        Returns False if the id is not local or the row is absent.
        """
        if activity_id >= 0:
            return False
        row = sess.get(DBActivity, activity_id)
        if row is None:
            return False
        sess.execute(
            delete(DBProjectItem).where(
                DBProjectItem.project_id == project_id,
                DBProjectItem.item_type == "activity",
                DBProjectItem.activity_id == activity_id,
            )
        )
        sess.delete(row)
        # Renumber remaining item positions to stay contiguous.
        remaining = sess.exec(
            select(DBProjectItem)
            .where(DBProjectItem.project_id == project_id)
            .order_by(DBProjectItem.position)
        ).all()
        for pos, it in enumerate(remaining):
            it.position = pos
            sess.add(it)
        sess.commit()
        return True

    def force_update_activity(
        self, sess: Session, user_info_id: int, act: Activity
    ) -> None:
        """Overwrite ALL columns of an existing activity row (used for re-fetch).

        If no row exists, inserts a new one.  Unlike ``_upsert_activity``,
        this always overwrites enrichment columns (polyline, elevation) —
        EXCEPT any of the six E2EE-in-scope fields (issue #29) whose EXISTING
        value is already an encrypted envelope: a "force refresh from Strava"
        still refreshes plaintext stats (distance, counts, ...) normally, but
        must not clobber ciphertext back to plaintext geometry/name.
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
        if not is_encrypted_envelope(existing.name):
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
        if not is_encrypted_envelope(existing.start_latlng_json):
            existing.start_latlng_json = json.dumps(act.start_latlng) if act.start_latlng else None
        if not is_encrypted_envelope(existing.end_latlng_json):
            existing.end_latlng_json = json.dumps(act.end_latlng) if act.end_latlng else None
        if not is_encrypted_envelope(existing.summary_polyline):
            existing.summary_polyline = act.summary_polyline
        if not is_encrypted_envelope(existing.elevation_profile_json):
            existing.elevation_profile_json = ep_json
            existing.elevation_profile_low_res_json = _low_res_ep_json(ep_json)
        sess.commit()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

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
            # Update mutable user-visible fields always — except name, once it's
            # already a client-side E2EE ciphertext envelope (issue #29): a
            # plain re-sync must not silently overwrite it back to plaintext.
            if not is_encrypted_envelope(existing.name):
                existing.name = act.name
            existing.kudos_count = act.kudos_count
            existing.achievement_count = act.achievement_count
            # If the stored polyline is null but the incoming one is not, take
            # the incoming value — the user may have fixed their Strava map
            # privacy and re-synced, or the first sync happened to return null.
            # Already safe against clobbering ciphertext without an explicit
            # guard: an encrypted summary_polyline is never None (it's a
            # non-empty "v1.…" envelope), so this branch can't fire once the
            # field is encrypted.
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

        # start_latlng_json / end_latlng_json / elevation_profile*_json may hold a
        # client-side E2EE ciphertext envelope (issue #29) instead of parseable
        # JSON once the user has encryption enabled. json.loads() on that string
        # would raise — every project load goes through here, not just geo
        # endpoints — so treat an encrypted field as absent for the parsed form
        # (every consumer of start_latlng/end_latlng/elevation_profile already
        # has a "no geometry" fallback) and surface the raw ciphertext via the
        # *_enc fields instead, so the client can decrypt + reconstruct it.
        start_latlng = None
        start_latlng_enc = None
        if row.start_latlng_json:
            if is_encrypted_envelope(row.start_latlng_json):
                start_latlng_enc = row.start_latlng_json
            else:
                start_latlng = json.loads(row.start_latlng_json)

        end_latlng = None
        end_latlng_enc = None
        if row.end_latlng_json:
            if is_encrypted_envelope(row.end_latlng_json):
                end_latlng_enc = row.end_latlng_json
            else:
                end_latlng = json.loads(row.end_latlng_json)

        elevation_profile = None
        elevation_profile_enc = None
        if include_heavy and include_elevation and row.elevation_profile_json:
            if is_encrypted_envelope(row.elevation_profile_json):
                elevation_profile_enc = row.elevation_profile_json
            else:
                ep = json.loads(row.elevation_profile_json)
                elevation_profile = (ep["distances_km"], ep["elevations_m"])

        elevation_profile_low_res = None
        elevation_profile_low_res_enc = None
        if row.elevation_profile_low_res_json:
            if is_encrypted_envelope(row.elevation_profile_low_res_json):
                elevation_profile_low_res_enc = row.elevation_profile_low_res_json
            else:
                lr = json.loads(row.elevation_profile_low_res_json)
                elevation_profile_low_res = (lr["distances_km"], lr["elevations_m"])

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
            start_latlng=start_latlng,
            end_latlng=end_latlng,
            summary_polyline=row.summary_polyline if include_heavy else None,
            elevation_profile=elevation_profile,
            # Always loaded — lightweight, never deferred — so meta/low-res
            # responses can render the chart before the full profile arrives.
            elevation_profile_low_res=elevation_profile_low_res,
            is_edited=bool(getattr(row, "is_edited", False)),
            start_latlng_enc=start_latlng_enc,
            end_latlng_enc=end_latlng_enc,
            # Prefer the full profile's ciphertext; fall back to the low-res
            # ciphertext when the full profile is deferred/unavailable — mirrors
            # ProjectIO.to_dict()'s _ep_pairs() fallback for the plaintext case.
            elevation_profile_enc=elevation_profile_enc or elevation_profile_low_res_enc,
        )
