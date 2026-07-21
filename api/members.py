"""REST travel-companion endpoints — project members and invite links (issue #106).

Routes:
    POST   /api/projects/{name}/members/invite     — create (or return) the invite link token
    DELETE /api/projects/{name}/members/invite     — revoke the invite link
    GET    /api/projects/{name}/members            — list members (owner first)
    DELETE /api/projects/{name}/members/{user_id}  — owner removes a member; a member removes themself
    GET    /api/invites/{token}                    — preview an invite (project + owner name)
    POST   /api/invites/{token}/accept             — join the project as editor

Owner-only: invite create/revoke and removing *other* users. Any member may
leave. Invites are blocked while the owner has E2EE enabled — companions could
neither read nor write content encrypted under the owner's CMK (see plan for
issue #106; key sharing is a follow-up).
"""
from __future__ import annotations

from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from models.db import get_session
from pydantic import BaseModel, Field
from sqlmodel import select

from api.deps import get_current_user
from api.project_access import resolve_project
from models.project_db import DBProject, DBProjectInvite, DBProjectMember
from models.user import UserInfo

router = APIRouter(prefix="/api/projects", tags=["members"])
invites_router = APIRouter(prefix="/api/invites", tags=["members"])


# ── Response schemas ──────────────────────────────────────────────────────────

class InviteTokenOut(BaseModel):
    token: str = Field(description="Invite token; append to /join/{token} to build the link")

class MemberOut(BaseModel):
    user_id: int = Field(description="Member's user id")
    display_name: str = Field(description="Member's display name")
    avatar_url: str = Field(description="Member's avatar URL, may be empty")
    role: str = Field(description='"owner" or "editor"')

class MembersOut(BaseModel):
    members: List[MemberOut] = Field(description="Project members, owner first")

class InvitePreviewOut(BaseModel):
    project_name: str = Field(description="Name of the project the invite joins")
    owner_name: str = Field(description="Display name of the project owner")

class InviteAcceptedOut(BaseModel):
    name: str = Field(description="Name of the joined project")
    owner_id: int = Field(description="User id of the project owner — pass as ?owner= on project routes")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _display_name(user: Optional[UserInfo]) -> str:
    if user is None:
        return ""
    return user.display_name or user.email


def _get_invite(sess, token: str) -> tuple[DBProjectInvite, DBProject]:
    invite = sess.exec(
        select(DBProjectInvite).where(DBProjectInvite.token == token)
    ).first()
    if invite is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")
    project = sess.get(DBProject, invite.project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")
    return invite, project


# ── Member management (owner + members) ───────────────────────────────────────

@router.post("/{name}/members/invite", response_model=InviteTokenOut,
             summary="Create invite link")
def create_invite(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    owner: Optional[int] = None,
):
    """Create the project's invite token (idempotent — returns the existing one)."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = resolve_project(sess, user_info_id, name, owner, require_owner=True)
        owner = sess.get(UserInfo, row.user_info_id)
        if owner is not None and owner.encryption_enabled:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Travel companions are not available on encrypted accounts — "
                       "companions could not read or write encrypted trip content.",
            )
        invite = sess.exec(
            select(DBProjectInvite).where(DBProjectInvite.project_id == row.id)
        ).first()
        if invite is None:
            invite = DBProjectInvite(project_id=row.id, created_by=user_info_id)
            sess.add(invite)
            sess.commit()
            sess.refresh(invite)
        return {"token": invite.token}


@router.delete("/{name}/members/invite", status_code=status.HTTP_204_NO_CONTENT,
               summary="Revoke invite link")
def revoke_invite(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    owner: Optional[int] = None,
):
    """Delete the project's invite token. Existing members are unaffected."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = resolve_project(sess, user_info_id, name, owner, require_owner=True)
        for invite in sess.exec(
            select(DBProjectInvite).where(DBProjectInvite.project_id == row.id)
        ).all():
            sess.delete(invite)
        sess.commit()


@router.get("/{name}/members", response_model=MembersOut, summary="List members")
def list_members(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    owner: Optional[int] = None,
):
    """Return the owner plus all editors. Visible to the owner and any member."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = resolve_project(sess, user_info_id, name, owner)
        owner_user = sess.get(UserInfo, row.user_info_id)
        members: list[dict] = [{
            "user_id": row.user_info_id,
            "display_name": _display_name(owner_user),
            "avatar_url": owner_user.avatar_url if owner_user else "",
            "role": "owner",
        }]
        for m in sess.exec(
            select(DBProjectMember)
            .where(DBProjectMember.project_id == row.id)
            .order_by(DBProjectMember.created_at)
        ).all():
            u = sess.get(UserInfo, m.user_info_id)
            members.append({
                "user_id": m.user_info_id,
                "display_name": _display_name(u),
                "avatar_url": u.avatar_url if u else "",
                "role": m.role,
            })
        return {"members": members}


@router.delete("/{name}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Remove a member")
def remove_member(
    name: str,
    user_id: int,
    current_user: Annotated[dict, Depends(get_current_user)],
    owner: Optional[int] = None,
):
    """Owner removes any member; a member may remove only themself (leave)."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = resolve_project(sess, user_info_id, name, owner,
                              require_owner=user_id != user_info_id)
        member = sess.exec(
            select(DBProjectMember).where(
                DBProjectMember.project_id == row.id,
                DBProjectMember.user_info_id == user_id,
            )
        ).first()
        if member is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
        sess.delete(member)
        sess.commit()


# ── Invite preview / accept (any authenticated user) ──────────────────────────

@invites_router.get("/{token}", response_model=InvitePreviewOut, summary="Preview an invite")
def preview_invite(
    token: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    with get_session() as sess:
        _invite, project = _get_invite(sess, token)
        return {
            "project_name": project.name,
            "owner_name": _display_name(sess.get(UserInfo, project.user_info_id)),
        }


@invites_router.post("/{token}/accept", response_model=InviteAcceptedOut,
                     summary="Accept an invite")
def accept_invite(
    token: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Join the invite's project as editor. Idempotent for existing members."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        invite, project = _get_invite(sess, token)
        if project.user_info_id == user_info_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You already own this trip",
            )
        existing = sess.exec(
            select(DBProjectMember).where(
                DBProjectMember.project_id == project.id,
                DBProjectMember.user_info_id == user_info_id,
            )
        ).first()
        if existing is None:
            sess.add(DBProjectMember(
                project_id=project.id,
                user_info_id=user_info_id,
                invited_by=invite.created_by,
            ))
            sess.commit()
        return {"name": project.name, "owner_id": project.user_info_id}
