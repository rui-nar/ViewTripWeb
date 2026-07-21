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

from typing import Annotated, Optional

from fastapi import HTTPException, Query, status
from sqlmodel import select

from models.project_db import DBProject, DBProjectMember

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
