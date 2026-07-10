"""REST group endpoints — CRUD + membership for people groups (issue #50).

Groups are private and owner-only — never exposed in shared views. Each group
belongs to one project; members are DBPerson rows whose group_id points here (a
person belongs to at most one group).

Routes:
    POST   /api/groups                   — create a group
    GET    /api/groups/{id}               — group + its members
    PUT    /api/groups/{id}               — update a group
    DELETE /api/groups/{id}               — delete a group (ungroups members, deletes group-encounters)
    PUT    /api/groups/{id}/members       — set the group's member list
"""
from __future__ import annotations

import json
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from models.db import get_session
from pydantic import BaseModel, Field
from sqlmodel import select

from api.deps import get_current_user
from models.project_db import DBEncounter, DBPerson, DBPersonGroup, DBProject, DBProjectItem

router = APIRouter(prefix="/api/groups", tags=["groups"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class IDOut(BaseModel):
    id: int = Field(description="ID of the newly created group")


class SocialLink(BaseModel):
    network: str = Field(description="e.g. instagram, facebook")
    handle: str = Field(description="Username or profile URL on that network")


class GroupBody(BaseModel):
    project_name: str = Field(description="Project the group belongs to")
    name: Optional[str] = Field(None)
    nationalities: Optional[List[str]] = Field(None, description="ISO 3166-1 alpha-2 codes")
    socials: Optional[List[SocialLink]] = Field(None)


class GroupUpdateBody(BaseModel):
    name: Optional[str] = Field(None)
    nationalities: Optional[List[str]] = Field(None)
    socials: Optional[List[SocialLink]] = Field(None)


class MembersBody(BaseModel):
    person_ids: List[int] = Field(description="The group's full member list (people set to this group; others cleared)")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_project_id(sess, user_info_id: int, project_name: str) -> int:
    row = sess.exec(
        select(DBProject).where(
            DBProject.user_info_id == user_info_id,
            DBProject.name == project_name,
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return row.id


def _get_owned_group(sess, group_id: int, user_info_id: int) -> DBPersonGroup:
    row = sess.get(DBPersonGroup, group_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    project_row = sess.get(DBProject, row.project_id)
    if project_row is None or project_row.user_info_id != user_info_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return row


def _loads_list(raw: str | None) -> list:
    return json.loads(raw) if raw else []


def _group_out(row: DBPersonGroup) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "nationalities": _loads_list(row.nationalities_json),
        "socials": _loads_list(row.socials_json),
    }


def _apply_group_fields(row: DBPersonGroup, body) -> None:
    row.name = body.name
    row.nationalities_json = json.dumps(body.nationalities) if body.nationalities else None
    socials = [s.model_dump() for s in body.socials] if body.socials else []
    row.socials_json = json.dumps(socials) if socials else None


# ── CRUD ─────────────────────────────────────────────────────────────────────

@router.post("/", status_code=status.HTTP_201_CREATED, response_model=IDOut,
             summary="Create a group")
def create_group(
    body: GroupBody,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Create a new (empty) group in the project."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        project_id = _get_project_id(sess, user_info_id, body.project_name)
        row = DBPersonGroup(project_id=project_id)
        _apply_group_fields(row, body)
        sess.add(row)
        sess.commit()
        group_id = row.id
    return {"id": group_id}


@router.get("/{group_id}", summary="Get a group and its members")
def get_group(
    group_id: int,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Return a group plus its member people (id, name, avatar)."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = _get_owned_group(sess, group_id, user_info_id)
        members = sess.exec(
            select(DBPerson).where(DBPerson.group_id == group_id).order_by(DBPerson.id)
        ).all()
        return {
            **_group_out(row),
            "members": [
                {"id": m.id, "name": m.name, "avatar_photo": m.avatar_photo}
                for m in members
            ],
        }


@router.put("/{group_id}", status_code=status.HTTP_204_NO_CONTENT,
            summary="Update a group")
def update_group(
    group_id: int,
    body: GroupUpdateBody,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Update a group's name, nationalities, or socials."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = _get_owned_group(sess, group_id, user_info_id)
        _apply_group_fields(row, body)
        sess.add(row)
        sess.commit()


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Delete a group")
def delete_group(
    group_id: int,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Delete a group; its members are ungrouped (not deleted), but any
    encounters logged directly against the group (issue #56) are deleted too —
    unlike a member, a group-encounter has no other entity to fall back to."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = _get_owned_group(sess, group_id, user_info_id)

        encounters = sess.exec(
            select(DBEncounter).where(DBEncounter.group_id == group_id)
        ).all()
        enc_ids = [e.id for e in encounters]
        if enc_ids:
            for item in sess.exec(
                select(DBProjectItem).where(DBProjectItem.encounter_id.in_(enc_ids))
            ).all():
                sess.delete(item)
        for e in encounters:
            sess.delete(e)

        for m in sess.exec(select(DBPerson).where(DBPerson.group_id == group_id)).all():
            m.group_id = None
            sess.add(m)
        sess.delete(row)
        sess.commit()


@router.put("/{group_id}/members", status_code=status.HTTP_204_NO_CONTENT,
            summary="Set the group's member list")
def set_members(
    group_id: int,
    body: MembersBody,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Set the group's members to exactly [person_ids]: those people are assigned
    to this group (removed from any other), and any current member not listed is
    ungrouped. All person_ids must belong to the group's project."""
    user_info_id = int(current_user["sub"])
    wanted = set(body.person_ids)
    with get_session() as sess:
        group = _get_owned_group(sess, group_id, user_info_id)

        # Validate each requested person exists and is in the same project.
        for pid in wanted:
            person = sess.get(DBPerson, pid)
            if person is None or person.project_id != group.project_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Person {pid} not in project",
                )

        # Clear people currently in this group who are no longer wanted.
        for m in sess.exec(select(DBPerson).where(DBPerson.group_id == group_id)).all():
            if m.id not in wanted:
                m.group_id = None
                sess.add(m)

        # Assign the wanted people to this group (moves them out of any other).
        for pid in wanted:
            person = sess.get(DBPerson, pid)
            person.group_id = group_id
            sess.add(person)

        sess.commit()
