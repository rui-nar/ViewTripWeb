"""Project item-list persistence (bulk replace of the timeline order).

Part of the ``ProjectRepo`` mixin split — see ``src/project/project_repo.py``
for the composed class and module docstring.
"""
from __future__ import annotations

import json
from typing import List

from sqlalchemy import delete, insert
from sqlmodel import Session

from models.project_db import DBProjectItem
from src.models.project import ProjectItem
from src.project.project_io import ProjectIO


class ItemOrderingMixin:
    """Bulk replace of a project's ``DBProjectItem`` rows."""

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
                "encounter_id": (
                    item.encounter.id
                    if item.item_type == "encounter" and item.encounter is not None
                    else None
                ),
            })

        sess.execute(insert(DBProjectItem).values(rows))
