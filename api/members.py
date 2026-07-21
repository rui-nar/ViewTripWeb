"""REST travel-companion endpoints — project members and invite links
(issue #106; roles: issue #109; invite emails: issue #113).

Routes:
    POST   /api/projects/{name}/members/invite     — create (or return) the invite link token,
                                                       optionally emailing it
    DELETE /api/projects/{name}/members/invite     — revoke the invite link
    GET    /api/projects/{name}/members            — list members (owner first)
    DELETE /api/projects/{name}/members/{user_id}  — remove a member; a member removes themself
    GET    /api/invites/{token}                    — preview an invite (project + owner name + role)
    POST   /api/invites/{token}/accept             — join the project with the invite's role

Member management (invite create/revoke, removing editors/viewers) is
co-owner+. Only the strict owner may create a "co-owner" invite or remove a
co-owner (so co-owners can't lock each other out). Any member may leave.
Invites are blocked while the owner has E2EE enabled — companions could
neither read nor write content encrypted under the owner's CMK (see plan for
issue #106; key sharing is a follow-up).
"""
from __future__ import annotations

import logging
import os
import re
from typing import Annotated, List, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from models.db import get_session
from pydantic import BaseModel, Field
from sqlmodel import select

from api.deps import get_current_user
from api.project_access import require_role, resolve_project
from models.project_db import DBProject, DBProjectInvite, DBProjectMember
from models.user import UserInfo
from src.email.service import EmailMessage, get_email_service
from src.email.templates import render_invite_email

# Loose sanity check only — not full RFC 5322 validation. A malformed address
# just fails at SMTP-send time inside the background task (logged, never
# surfaces to the caller); this only catches obviously-not-an-email input
# before bothering to queue a send.
_logger = logging.getLogger(__name__)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Same var/default as api/strava.py's OAuth-callback redirects — the base URL
# for links the server hands back to the browser.
_FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5500")

router = APIRouter(prefix="/api/projects", tags=["members"])
invites_router = APIRouter(prefix="/api/invites", tags=["members"])

InviteRole = Literal["viewer", "editor", "co-owner"]


# ── Request / response schemas ──────────────────────────────────────────────

class InviteCreateBody(BaseModel):
    role: InviteRole = Field(
        default="editor",
        description='Role granted on accept. Only the trip owner (not a '
                    'co-owner) may create a "co-owner" invite.',
    )
    email: Optional[str] = Field(
        default=None,
        description="If set, email the join link to this address (issue #113). "
                    "Sending happens in the background — this doesn't block or "
                    "fail the request, and doesn't change the response.",
    )

class InviteTokenOut(BaseModel):
    token: str = Field(description="Invite token; append to /join/{token} to build the link")
    role: str = Field(description="Role this invite grants on accept")

class MemberOut(BaseModel):
    user_id: int = Field(description="Member's user id")
    display_name: str = Field(description="Member's display name")
    avatar_url: str = Field(description="Member's avatar URL, may be empty")
    role: str = Field(description='"owner", "co-owner", "editor", or "viewer"')

class MembersOut(BaseModel):
    members: List[MemberOut] = Field(description="Project members, owner first")

class InvitePreviewOut(BaseModel):
    project_name: str = Field(description="Name of the project the invite joins")
    owner_name: str = Field(description="Display name of the project owner")
    role: str = Field(description="Role this invite grants on accept")

class InviteAcceptedOut(BaseModel):
    name: str = Field(description="Name of the joined project")
    owner_id: int = Field(description="User id of the project owner — pass as ?owner= on project routes")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _display_name(user: Optional[UserInfo]) -> str:
    if user is None:
        return ""
    return user.display_name or user.email


async def send_invite_email(to_email: str, project_name: str, owner_name: str,
                             role: str, token: str) -> None:
    """Background task (issue #113): render and send the invite email.

    Runs after the response has gone out (queued via BackgroundTasks), so a
    slow or misconfigured relay never delays or fails the invite-create
    request. There's no request left to report to, so a send failure (bad
    credentials, relay down, ...) is logged here rather than raised — an
    unhandled exception in a background task would otherwise just become a
    stray traceback in the server log with no other effect.
    """
    join_url = f"{_FRONTEND_ORIGIN}/join/{token}"
    text_body, html_body = render_invite_email(
        project_name=project_name, owner_name=owner_name, role=role, join_url=join_url)
    try:
        await get_email_service().send(EmailMessage(
            to=to_email,
            subject=f"{owner_name} invited you to {project_name} on ViewTrip",
            text_body=text_body,
            html_body=html_body,
        ))
    except Exception:
        _logger.exception("Failed to send invite email to %s", to_email)


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
    background_tasks: BackgroundTasks,
    body: Optional[InviteCreateBody] = None,
    owner: Optional[int] = None,
):
    """Create the project's invite token (idempotent — returns the existing
    one, unchanged, if one already exists; the requested role is ignored on
    that path). If ``body.email`` is set, also queues the join link to be
    emailed to that address (issue #113) — this happens regardless of
    whether the invite was just created or already existed, so "email the
    link to someone new" is just calling this again with their address."""
    user_info_id = int(current_user["sub"])
    invite_body = body or InviteCreateBody()
    role = invite_body.role
    email = invite_body.email
    if email is not None and not _EMAIL_RE.match(email):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Not a valid email address",
        )
    with get_session() as sess:
        row = resolve_project(sess, user_info_id, name, owner, min_role="co-owner")
        if role == "co-owner":
            require_role(sess, row, user_info_id, "owner")
        owner_user = sess.get(UserInfo, row.user_info_id)
        if owner_user is not None and owner_user.encryption_enabled:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Travel companions are not available on encrypted accounts — "
                       "companions could not read or write encrypted trip content.",
            )
        invite = sess.exec(
            select(DBProjectInvite).where(DBProjectInvite.project_id == row.id)
        ).first()
        if invite is None:
            invite = DBProjectInvite(project_id=row.id, created_by=user_info_id, role=role)
            sess.add(invite)
            sess.commit()
            sess.refresh(invite)
        if email is not None:
            background_tasks.add_task(
                send_invite_email, email, row.name, _display_name(owner_user),
                invite.role, invite.token)
        return {"token": invite.token, "role": invite.role}


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
        row = resolve_project(sess, user_info_id, name, owner, min_role="co-owner")
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
    """Return the owner plus all members (any role). Visible to any member,
    including viewers."""
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
    """Co-owner+ removes an editor/viewer; a member may remove only themself
    (leave), at any role. Removing a co-owner is strict-owner-only, so
    co-owners can't lock each other out."""
    user_info_id = int(current_user["sub"])
    is_self = user_id == user_info_id
    with get_session() as sess:
        row = resolve_project(sess, user_info_id, name, owner,
                              min_role="viewer" if is_self else "co-owner")
        member = sess.exec(
            select(DBProjectMember).where(
                DBProjectMember.project_id == row.id,
                DBProjectMember.user_info_id == user_id,
            )
        ).first()
        if member is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
        if not is_self and member.role == "co-owner":
            require_role(sess, row, user_info_id, "owner")
        sess.delete(member)
        sess.commit()


# ── Invite preview / accept (any authenticated user) ──────────────────────────

@invites_router.get("/{token}", response_model=InvitePreviewOut, summary="Preview an invite")
def preview_invite(
    token: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    with get_session() as sess:
        invite, project = _get_invite(sess, token)
        return {
            "project_name": project.name,
            "owner_name": _display_name(sess.get(UserInfo, project.user_info_id)),
            "role": invite.role,
        }


@invites_router.post("/{token}/accept", response_model=InviteAcceptedOut,
                     summary="Accept an invite")
def accept_invite(
    token: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Join the invite's project with its role. Idempotent for existing
    members (role is not changed by re-accepting)."""
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
                role=invite.role,
                invited_by=invite.created_by,
            ))
            sess.commit()
        return {"name": project.name, "owner_id": project.user_info_id}
