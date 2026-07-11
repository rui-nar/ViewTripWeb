"""REST project sharing endpoints — share-link create/revoke, share info, visitors.

Routes:
    POST   /api/projects/{name}/share                    — create share link
    DELETE /api/projects/{name}/share                     — revoke share link
    GET    /api/projects/{name}/share-info                — get share tokens
    POST   /api/projects/{name}/share/no-memories         — create no-memories share link
    DELETE /api/projects/{name}/share/no-memories         — revoke no-memories share link
    GET    /api/projects/{name}/share/visitors            — get share link visitor stats
"""
from __future__ import annotations

import uuid
from typing import Annotated, Any, Dict, List, Optional

from models.db import get_session
from sqlmodel import select

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.deps import get_current_user
from models.project_db import DBProject, DBShareVisit
from models.user import UserInfo

router = APIRouter(prefix="/api/projects", tags=["projects"])


# ── Response schemas ──────────────────────────────────────────────────────────

class ShareTokenOut(BaseModel):
    share_token: str = Field(description="Public share token for full-project access")

class ShareTokenNoMemoriesOut(BaseModel):
    share_token_no_memories: str = Field(description="Public share token with memories stripped")

class ShareInfoOut(BaseModel):
    share_token: Optional[str] = Field(None, description="Full-access share token, or null if not created")
    share_token_no_memories: Optional[str] = Field(None, description="No-memories share token, or null if not created")


# ── Project sharing ────────────────────────────────────────────────────────────

@router.post("/{name}/share", response_model=ShareTokenOut, summary="Create share link")
def create_share_link(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Generate (or return existing) share token for public read-only access."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = sess.exec(
            select(DBProject).where(
                DBProject.user_info_id == user_info_id,
                DBProject.name == name,
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        if not row.share_token:
            row.share_token = str(uuid.uuid4())
            sess.add(row)
            sess.commit()
        token = row.share_token
    return {"share_token": token}


@router.delete("/{name}/share", status_code=status.HTTP_204_NO_CONTENT)
def revoke_share_link(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Revoke the share token — the project becomes private again."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = sess.exec(
            select(DBProject).where(
                DBProject.user_info_id == user_info_id,
                DBProject.name == name,
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        if row.share_token:
            from src.tile_renderer import invalidate_tile_cache
            from api.share import invalidate_share_cache
            invalidate_tile_cache(row.share_token)
            invalidate_share_cache(row.share_token)
        row.share_token = None
        sess.add(row)
        sess.commit()


@router.get("/{name}/share-info", response_model=ShareInfoOut, summary="Get share tokens")
def get_share_info(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Return both share tokens for the project (null when not yet created)."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = sess.exec(
            select(DBProject).where(
                DBProject.user_info_id == user_info_id,
                DBProject.name == name,
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        return {
            "share_token": row.share_token,
            "share_token_no_memories": row.share_token_no_memories,
        }


@router.post("/{name}/share/no-memories", response_model=ShareTokenNoMemoriesOut,
             summary="Create no-memories share link")
def create_share_link_no_memories(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Create (idempotent) a share token that strips memory items."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = sess.exec(
            select(DBProject).where(
                DBProject.user_info_id == user_info_id,
                DBProject.name == name,
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        if not row.share_token_no_memories:
            row.share_token_no_memories = str(uuid.uuid4())
            sess.add(row)
            sess.commit()
        return {"share_token_no_memories": row.share_token_no_memories}


@router.delete("/{name}/share/no-memories", status_code=status.HTTP_204_NO_CONTENT,
               summary="Revoke no-memories share link")
def revoke_share_link_no_memories(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Revoke the no-memories share token."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = sess.exec(
            select(DBProject).where(
                DBProject.user_info_id == user_info_id,
                DBProject.name == name,
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        if row.share_token_no_memories:
            from src.tile_renderer import invalidate_tile_cache
            from api.share import invalidate_share_cache
            invalidate_tile_cache(row.share_token_no_memories)
            invalidate_share_cache(row.share_token_no_memories)
        row.share_token_no_memories = None
        sess.add(row)
        sess.commit()


@router.get("/{name}/share/visitors", summary="Get share link visitor stats")
def get_share_visitors(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Return visitor stats for both share link types.

    Response shape:
      {
        full: { anonymous_count: N, registered: [{display_name, email, last_seen_at}] },
        no_memories: { anonymous_count: N, registered: [...] }
      }
    """
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = sess.exec(
            select(DBProject).where(
                DBProject.user_info_id == user_info_id,
                DBProject.name == name,
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        project_id = row.id

        visits = sess.exec(
            select(DBShareVisit).where(DBShareVisit.project_id == project_id)
        ).all()

    result: Dict[str, Any] = {
        "full": {"anonymous_count": 0, "registered": []},
        "no_memories": {"anonymous_count": 0, "registered": []},
    }

    registered_ids: Dict[str, List[int]] = {"full": [], "no_memories": []}
    last_seen: Dict[str, Dict[int, float]] = {"full": {}, "no_memories": {}}

    for v in visits:
        bucket = v.token_type if v.token_type in result else "full"
        if v.visitor_type == "anonymous":
            result[bucket]["anonymous_count"] += 1
        else:
            if v.user_info_id is not None:
                registered_ids[bucket].append(v.user_info_id)
                last_seen[bucket][v.user_info_id] = v.last_seen_at

    with get_session() as sess:
        for bucket in ("full", "no_memories"):
            ids = registered_ids[bucket]
            if not ids:
                continue
            users = sess.exec(
                select(UserInfo).where(UserInfo.id.in_(ids))
            ).all()
            result[bucket]["registered"] = [
                {
                    "display_name": u.display_name,
                    "email": u.email,
                    "last_seen_at": last_seen[bucket].get(u.id, 0.0),
                }
                for u in users
            ]

    return result
