"""Project item-list persistence (the timeline order).

Part of the ``ProjectRepo`` mixin split — see ``src/project/project_repo.py``
for the composed class and module docstring.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List

from sqlalchemy import delete, insert, update
from sqlmodel import Session, select

from models.project_db import DBProjectItem
from src.models.project import ProjectItem
from src.project.project_io import ProjectIO
from src.project.repo_core import bump_lock_version

# Sentinel: None is a meaningful value for route_started_at (a terminal
# segment), so it cannot double as "no compare-and-set requested".
_UNSET = object()


def _row_values(item: ProjectItem, position: int) -> Dict[str, Any]:
    """The column values a ``DBProjectItem`` row carries for *item*."""
    segment_json = (
        json.dumps(ProjectIO._serialise_item(item)["segment"])
        if item.item_type == "segment" else None
    )
    return {
        "position": position,
        "item_type": item.item_type,
        "activity_id": item.activity_id if item.item_type == "activity" else None,
        "segment_json": segment_json,
        "segment_id": (
            item.segment.id or None
            if item.item_type == "segment" and item.segment is not None else None
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
        "encounter_id": (
            item.encounter.id
            if item.item_type == "encounter" and item.encounter is not None
            else None
        ),
    }


class ItemOrderingMixin:
    """Persist a project's ``DBProjectItem`` rows by diffing against what is stored."""

    def update_segment_fields(
        self,
        sess: Session,
        project_id: int,
        seg_id: str,
        fields: Dict[str, Any],
        *,
        expect_status: Any = _UNSET,
        expect_started_at: Any = _UNSET,
    ) -> bool:
        """Merge *fields* into one segment's stored JSON. Returns True if written.

        A payload write (issue #173): it touches a single row and does not
        *take* the optimistic lock, so two segments resolving at once no longer
        contend — neither can make the other fail or retry.

        It does, however, *advance* ``lock_version``. That asymmetry is load
        bearing. ``save_project`` rewrites every item's payload from the caller's
        in-memory snapshot, so a structural mutation that loaded before this
        write would otherwise reinstate the pre-write JSON and silently lose it —
        a resolve landing mid-reorder would revert to "pending". Advancing the
        counter makes this write visible to that CAS, which then retries against
        reloaded state. Payload writes stay uncontended; structural writes pay
        one retry.

        Both ``expect_*`` arguments are optional compare-and-set guards; omit
        them to write unconditionally. ``None`` is a meaningful stored value for
        either field, so absence is signalled with a sentinel rather than None.

        ``expect_started_at`` matches on ``route_started_at``: the resolve
        trigger stamps it and the finishing job passes back the value it started
        with, so a job superseded by a newer trigger cannot overwrite the fresh
        attempt's verdict. It guards *re-triggers*, not a segment edited and
        re-resolved into a coincidentally identical timestamp — a real job token
        belongs with the durable job rows in phase D.
        """
        row = self._segment_row(sess, project_id, seg_id)
        if row is None:
            return False
        data = json.loads(row.segment_json or "{}")
        if expect_status is not _UNSET and data.get("route_status") != expect_status:
            return False
        if expect_started_at is not _UNSET and data.get("route_started_at") != expect_started_at:
            return False
        data.update(fields)
        sess.execute(
            update(DBProjectItem)
            .where(DBProjectItem.id == row.id)
            .values(segment_json=json.dumps(data))
        )
        bump_lock_version(sess, project_id)
        return True

    def _segment_row(self, sess: Session, project_id: int, seg_id: str):
        """The item row holding segment *seg_id*, via the indexed column.

        Falls back to scanning the project's segment rows when ``segment_id`` is
        NULL — a row written by a path that predates the column. The scan
        backfills it so the next lookup is indexed.
        """
        row = sess.exec(
            select(DBProjectItem).where(
                DBProjectItem.project_id == project_id,
                DBProjectItem.segment_id == seg_id,
            )
        ).first()
        if row is not None:
            return row

        for candidate in sess.exec(
            select(DBProjectItem).where(
                DBProjectItem.project_id == project_id,
                DBProjectItem.item_type == "segment",
                DBProjectItem.segment_id.is_(None),
            )
        ).all():
            try:
                parsed = json.loads(candidate.segment_json or "{}")
            except ValueError:
                continue
            if parsed.get("id") == seg_id:
                candidate.segment_id = seg_id
                sess.add(candidate)
                return candidate
        return None

    def _replace_items(
        self, sess: Session, project_id: int, items: List[ProjectItem]
    ) -> None:
        """Reconcile the stored item rows with *items*, keyed on ``uid``.

        Previously this deleted every row for the project and bulk-reinserted
        the list. That churned primary keys on every save, which is why item
        rows had no identity a targeted update could address (issue #173).

        Now: insert rows whose uid is new, update the ones that changed, delete
        the ones no longer present. Items arriving without a uid (freshly
        constructed, or loaded before the column existed) are assigned one and
        inserted. The uid is written back onto the in-memory item so a caller
        holding the ``Project`` keeps addressing the same row afterwards.

        Position is not unique-constrained, so the renumber needs no two-phase
        shuffle — transient duplicates during the update pass are fine.
        """
        existing = {
            row.uid: row for row in sess.exec(
                select(DBProjectItem).where(DBProjectItem.project_id == project_id)
            ).all()
            if row.uid is not None
        }

        seen: set[str] = set()
        inserts: List[Dict[str, Any]] = []

        for position, item in enumerate(items):
            if not item.uid or item.uid in seen:
                # No identity yet, or a duplicated uid (a caller cloned an item
                # rather than constructing one) — mint a fresh row either way.
                item.uid = uuid.uuid4().hex
            seen.add(item.uid)

            values = _row_values(item, position)
            row = existing.get(item.uid)
            if row is None:
                inserts.append({"project_id": project_id, "uid": item.uid, **values})
                continue
            changed = {k: v for k, v in values.items() if getattr(row, k) != v}
            if changed:
                sess.execute(
                    update(DBProjectItem)
                    .where(DBProjectItem.id == row.id)
                    .values(**changed)
                )

        stale = [row.id for uid, row in existing.items() if uid not in seen]
        if stale:
            sess.execute(delete(DBProjectItem).where(DBProjectItem.id.in_(stale)))

        # Rows predating the uid column (or written by a path that skipped it)
        # cannot be diffed — they are not in `existing`, so they would survive
        # every save as invisible duplicates. Drop them alongside the diff.
        sess.execute(
            delete(DBProjectItem).where(
                DBProjectItem.project_id == project_id,
                DBProjectItem.uid.is_(None),
            )
        )

        if inserts:
            sess.execute(insert(DBProjectItem).values(inserts))
