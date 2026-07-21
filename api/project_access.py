"""Central project-access resolver (issue #106 — travel companion).

Single place that turns ``(caller, name, ?owner)`` into a ``DBProject`` row.
Every router that used to inline a ``(user_info_id, name)`` ownership lookup
now calls :func:`resolve_project` instead, then threads ``row.user_info_id``
(the project *owner*) into the repo / cache / background-task calls that
follow.

Access model: the owner has full access; a ``projectmember`` row grants
"editor" access — content mutations, but none of the owner-only operations
(``require_owner=True``: rename, delete, share links, member management).
"""
from __future__ import annotations

from typing import Annotated, List, Optional, Sequence

from fastapi import HTTPException, Query, status
from sqlmodel import select

from models.project_db import DBJournalEntry, DBProject, DBProjectItem, DBProjectMember

# Shared ``?owner=`` query-param dependency for project-scoped routes. Absent
# (None) means "my own project"; a companion passes the owner's user id.
OwnerParam = Annotated[
    Optional[int],
    Query(
        alias="owner",
        description="Project owner's user id for shared-access routing; "
                    "omit to access your own project.",
    ),
]

_OWNER_ONLY_DETAIL = "Only the trip owner can do this"


def _is_member(sess, project_id: int, user_info_id: int) -> bool:
    return sess.exec(
        select(DBProjectMember).where(
            DBProjectMember.project_id == project_id,
            DBProjectMember.user_info_id == user_info_id,
        )
    ).first() is not None


def resolve_project(
    sess,
    caller_id: int,
    name: str,
    owner_id: Optional[int] = None,
    *,
    require_owner: bool = False,
) -> DBProject:
    """Resolve a project by name for *caller_id*, honoring an optional *owner_id*.

    ``owner_id`` absent (``None``) or equal to ``caller_id`` resolves the
    caller's own project by ``(caller_id, name)``; 404s with "Project not
    found" if absent.

    ``owner_id`` set to someone other than the caller is the shared-access
    path: the project is looked up by ``(owner_id, name)`` and the caller must
    hold a ``projectmember`` row. Both a missing project and a missing
    membership 404 (not 403) so a stranger can't probe whether a project
    exists. ``require_owner=True`` additionally 403s members — reserved for
    owner-only operations.
    """
    if owner_id is not None and owner_id != caller_id:
        row = sess.exec(
            select(DBProject).where(
                DBProject.user_info_id == owner_id,
                DBProject.name == name,
            )
        ).first()
        if row is None or not _is_member(sess, row.id, caller_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        if require_owner:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_OWNER_ONLY_DETAIL)
        return row

    row = sess.exec(
        select(DBProject).where(
            DBProject.user_info_id == caller_id,
            DBProject.name == name,
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return row


def assert_project_access(
    sess,
    caller_id: int,
    project_id: int,
    *,
    require_owner: bool = False,
) -> DBProject:
    """Access check for routes keyed on a sub-resource's ``project_id``.

    Counterpart of :func:`resolve_project` for the ``_get_owned_*`` helpers
    (memories, journal, people, groups, encounters) that already know the
    project id from the row being edited. Preserves their historical contract:
    403 "Forbidden" when the project is missing or the caller has no access —
    never 404, since the sub-resource id was already validated by the caller.
    """
    row = sess.get(DBProject, project_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    if row.user_info_id == caller_id:
        return row
    if require_owner or not _is_member(sess, project_id, caller_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return row


# ── Per-user journal visibility (issue #106) ─────────────────────────────────
#
# Journal entries are private to their author, so the item list a client sees
# is a *projection* of the full timeline: everything except other users'
# journal items. Index-based operations (delete-at-index, reorder,
# insert_after_index) therefore arrive as indices into the caller's visible
# list and must be translated to positions in the full list before mutating —
# otherwise one user's edit lands on the wrong item whenever another user has
# journal entries in the project. When nobody else has journal entries the
# mapping is the identity, preserving historical behavior exactly.

def journal_visible_positions(items, caller_id: int, owner_id: int) -> List[int]:
    """Positions (into a domain ``project.items`` list) visible to *caller_id*.

    Keeps every non-journal item plus the caller's own journal entries; a
    journal entry with ``user_info_id`` None is a legacy row owned by the
    project owner.
    """
    positions: List[int] = []
    for pos, item in enumerate(items):
        if item.item_type == "journal" and item.journal is not None:
            author = item.journal.user_info_id
            if (author if author is not None else owner_id) != caller_id:
                continue
        positions.append(pos)
    return positions


def journal_visible_row_positions(
    sess, item_rows: Sequence[DBProjectItem], caller_id: int, owner_id: int
) -> List[int]:
    """Like :func:`journal_visible_positions` but for raw ``DBProjectItem`` rows
    (routes that insert into the item table without loading the domain Project).
    """
    journal_ids = [
        r.journal_id for r in item_rows
        if r.item_type == "journal" and r.journal_id is not None
    ]
    authors = {}
    if journal_ids:
        for jr in sess.exec(
            select(DBJournalEntry).where(DBJournalEntry.id.in_(journal_ids))
        ).all():
            authors[jr.id] = jr.user_info_id if jr.user_info_id is not None else owner_id
    positions: List[int] = []
    for pos, r in enumerate(item_rows):
        if r.item_type == "journal" and r.journal_id is not None:
            if authors.get(r.journal_id, owner_id) != caller_id:
                continue
        positions.append(pos)
    return positions


def translate_insert_after(
    visible_positions: List[int], insert_after_index: Optional[int], total: int
) -> int:
    """Turn a caller-visible ``insert_after_index`` into a full-list position.

    Mirrors the historical clamping (``max(0, min(total, idx + 1))``): None or
    past-the-end append at the very end; negative inserts at the front.
    """
    if insert_after_index is None or insert_after_index >= len(visible_positions):
        return total
    if insert_after_index < 0:
        return 0
    return visible_positions[insert_after_index] + 1
