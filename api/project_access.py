"""Central project-access resolver (issue #106 — travel companion).

Single place that turns ``(caller, name, ?owner)`` into a ``DBProject`` row.
Every router that used to inline a ``(user_info_id, name)`` ownership lookup
now calls :func:`resolve_project` instead, then threads ``row.user_info_id``
(the project *owner*, today always identical to the caller) into the repo /
cache / background-task calls that follow. This is U1a of issue #106: a pure
mechanical refactor that keeps behavior identical while giving U1b a single
seam to add companion membership.
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import HTTPException, Query, status
from sqlmodel import select

from models.project_db import DBProject

# Shared ``?owner=`` query-param dependency for project-scoped routes. Absent
# (None) means "my own project" — the only case implemented before U1b.
OwnerParam = Annotated[
    Optional[int],
    Query(
        alias="owner",
        description="Project owner's user id for shared-access routing; "
                    "omit to access your own project.",
    ),
]


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
    caller's own project by ``(caller_id, name)`` — today's behavior,
    unchanged, 404s with "Project not found" if absent.

    ``owner_id`` set to someone other than the caller is the shared-access
    path: membership isn't implemented yet (arrives in issue #106 U1b), so
    this 404s for now rather than leaking whether such a project exists.

    ``require_owner`` is accepted so call sites can already ask for
    owner-only access; it's a no-op today since only the owner can resolve a
    project at all — U1b adds the membership check it will gate.
    """
    if owner_id is not None and owner_id != caller_id:
        # Shared access — membership check arrives in U1b. 404 (not 403) so a
        # stranger can't use this to probe whether a project exists.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    row = sess.exec(
        select(DBProject).where(
            DBProject.user_info_id == caller_id,
            DBProject.name == name,
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return row
