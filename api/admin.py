"""Admin dashboard REST endpoints (issue #25).

All routes require an admin caller (``require_admin`` re-reads ``is_admin`` from
the DB). Nothing here ever returns memory/journal *content* — only counts,
sizes, and profile fields — so the dashboard cannot leak private data.

Aggregates are computed with GROUP BY (no N+1). Storage is read from the TTL
cache in ``src.admin.storage`` and the filesystem walk happens OUTSIDE the DB
session so a slow walk never pins a pooled connection.
"""
from __future__ import annotations

import secrets
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import select

from api.deps import require_admin
from models.db import get_session
from models.project_db import DBActivity, DBMemory, DBProject
from models.user import LocalUser, UserInfo
from src.admin.storage import cached_user_storage, refresh_storage_cache
from src.admin.tiers import user_encryption_tier
from src.utils.logging import get_logger

_log = get_logger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Window for the "recent sign-ups" headline metric.
_RECENT_SIGNUP_WINDOW_SECONDS = 7 * 24 * 3600

# Length (bytes) of the random reset password; hex-encoded → 32 chars.
_RESET_PASSWORD_BYTES = 16

# Tiers for which an admin password reset is permitted. Medium/High are
# zero-knowledge enough that a server-side reset would silently destroy the
# user's encrypted data, so they are hard-blocked.
_RESETTABLE_TIERS = frozenset({"none", "low"})


# ── Response schemas ──────────────────────────────────────────────────────────

class UserRow(BaseModel):
    id: int
    email: str
    display_name: str
    auth_provider: str
    created_at: float
    project_count: int
    activity_count: int
    memory_count: int
    storage_bytes: int
    encryption_tier: str
    is_admin: bool


class Totals(BaseModel):
    users: int
    projects: int
    activities: int
    memories: int
    storage_bytes: int
    recent_signups_7d: int


class StatsResponse(BaseModel):
    totals: Totals
    users: list[UserRow]


class SearchResult(BaseModel):
    id: int
    email: str
    username: str
    display_name: str
    auth_provider: str
    encryption_tier: str
    is_admin: bool


class ResetPasswordResponse(BaseModel):
    temp_password: str = Field(description="Shown once; not recoverable afterwards")


class SetAdminRequest(BaseModel):
    is_admin: bool = Field(description="True to grant admin access, False to revoke it")


class OkResponse(BaseModel):
    ok: bool = True


# ── Helpers ───────────────────────────────────────────────────────────────────

def _counts_by_user(sess, col, model) -> dict[int, int]:
    """GROUP BY aggregate: {user_info_id: row_count} for a per-user table."""
    return {
        uid: cnt
        for uid, cnt in sess.exec(
            select(col, func.count()).group_by(col)
        ).all()
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/stats", response_model=StatsResponse, summary="Dashboard metrics")
def stats(_admin: Annotated[dict, Depends(require_admin)]):
    """Totals + per-user breakdown. No memory/journal content is returned."""
    now = time.time()
    with get_session() as sess:
        users = sess.exec(select(UserInfo)).all()

        project_counts = _counts_by_user(sess, DBProject.user_info_id, DBProject)
        activity_counts = _counts_by_user(sess, DBActivity.user_info_id, DBActivity)

        # Memories belong to a project which belongs to a user: join + group by owner.
        memory_counts = {
            uid: cnt
            for uid, cnt in sess.exec(
                select(DBProject.user_info_id, func.count(DBMemory.id))
                .join(DBMemory, DBMemory.project_id == DBProject.id)
                .group_by(DBProject.user_info_id)
            ).all()
        }

        tiers = {u.id: user_encryption_tier(sess, u.id) for u in users}
        # Snapshot the plain profile fields before leaving the session so the
        # (potentially slow) storage walk below holds no DB connection.
        profiles = [
            (u.id, u.email, u.display_name, u.auth_provider, u.created_at, bool(u.is_admin))
            for u in users
        ]

    # Storage walk happens OUTSIDE the session (see src.admin.storage).
    rows: list[UserRow] = []
    total_storage = 0
    for uid, email, display_name, auth_provider, created_at, is_admin in profiles:
        storage = cached_user_storage(str(uid), now=now)
        total_storage += storage
        rows.append(UserRow(
            id=uid,
            email=email,
            display_name=display_name,
            auth_provider=auth_provider,
            created_at=created_at,
            project_count=project_counts.get(uid, 0),
            activity_count=activity_counts.get(uid, 0),
            memory_count=memory_counts.get(uid, 0),
            storage_bytes=storage,
            encryption_tier=tiers.get(uid, "none"),
            is_admin=is_admin,
        ))

    recent = sum(
        1 for _, _, _, _, created_at, _ in profiles
        if created_at and (now - created_at) < _RECENT_SIGNUP_WINDOW_SECONDS
    )

    return StatsResponse(
        totals=Totals(
            users=len(rows),
            projects=sum(project_counts.values()),
            activities=sum(activity_counts.values()),
            memories=sum(memory_counts.values()),
            storage_bytes=total_storage,
            recent_signups_7d=recent,
        ),
        users=rows,
    )


@router.get("/storage/refresh", summary="Force-recompute storage cache")
def storage_refresh(_admin: Annotated[dict, Depends(require_admin)]):
    """Bust the storage TTL cache so the next /stats re-walks the filesystem."""
    refresh_storage_cache()
    return {"ok": True}


@router.get("/users/search", response_model=list[SearchResult],
            summary="Search users by email / username / display name")
def search_users(
    _admin: Annotated[dict, Depends(require_admin)],
    q: str = "",
    limit: int = 50,
):
    """Case-insensitive LIKE across email, username, display_name."""
    q = q.strip()
    if not q:
        return []
    like = f"%{q.lower()}%"
    with get_session() as sess:
        rows = sess.exec(
            select(UserInfo, LocalUser)
            .join(LocalUser, LocalUser.id == UserInfo.local_auth_id, isouter=True)
            .where(
                func.lower(UserInfo.email).like(like)
                | func.lower(UserInfo.display_name).like(like)
                | func.lower(func.coalesce(LocalUser.username, "")).like(like)
            )
            .limit(limit)
        ).all()
        return [
            SearchResult(
                id=ui.id,
                email=ui.email,
                username=lu.username if lu else "",
                display_name=ui.display_name,
                auth_provider=ui.auth_provider,
                encryption_tier=user_encryption_tier(sess, ui.id),
                is_admin=bool(ui.is_admin),
            )
            for ui, lu in rows
        ]


@router.post("/users/{user_info_id}/set-admin", response_model=OkResponse,
             summary="Grant or revoke admin access for a user")
def set_admin(
    user_info_id: int,
    body: SetAdminRequest,
    admin: Annotated[dict, Depends(require_admin)],
):
    """Toggle ``is_admin`` for a user. An admin cannot revoke their own access,
    so there's always at least one admin left who can undo a mistake."""
    if not body.is_admin and str(user_info_id) == str(admin.get("sub")):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You cannot remove your own admin access.",
        )
    with get_session() as sess:
        user_info = sess.get(UserInfo, user_info_id)
        if user_info is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )
        user_info.is_admin = body.is_admin
        sess.add(user_info)
        sess.commit()

    _log.info(
        "Admin set is_admin=%s for user_info_id=%s", body.is_admin, user_info_id
    )
    return {"ok": True}


@router.post("/users/{user_info_id}/reset-password",
             response_model=ResetPasswordResponse,
             summary="Reset a user's password (None/Low tiers only)")
def reset_password(
    user_info_id: int,
    _admin: Annotated[dict, Depends(require_admin)],
):
    """Set a random temp password + force change. Blocked for Medium/High tiers.

    Medium/High encryption is zero-knowledge enough that overwriting the server
    password would orphan the user's encrypted data, so those are refused (409).
    Google accounts have no server password → 409.
    """
    with get_session() as sess:
        user_info = sess.get(UserInfo, user_info_id)
        if user_info is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        tier = user_encryption_tier(sess, user_info_id)
        if tier not in _RESETTABLE_TIERS:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Password reset is unavailable for this account: its "
                    f"encryption tier ({tier}) is zero-knowledge, so the server "
                    "cannot reset the password without destroying encrypted data."
                ),
            )

        local_user = sess.get(LocalUser, user_info.local_auth_id)
        if local_user is None or not local_user.password_hash:
            # Google (or otherwise passwordless) account — no server password.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This account has no server-managed password to reset.",
            )

        temp_password = secrets.token_hex(_RESET_PASSWORD_BYTES)
        local_user.password_hash = LocalUser.hash_password(temp_password)
        local_user.password_change_required = True
        sess.add(local_user)
        sess.commit()

    _log.info(
        "Admin reset password for user_info_id=%s (tier=%s)", user_info_id, tier
    )
    return ResetPasswordResponse(temp_password=temp_password)


@router.delete("/users/{user_info_id}", response_model=OkResponse,
               summary="Permanently delete a user and all their data")
def delete_user(
    user_info_id: int,
    admin: Annotated[dict, Depends(require_admin)],
):
    """Irreversibly delete a user's account, projects, and every row/file they
    own. An admin cannot delete their own account this way — use account
    settings for that, so there's always an admin left to act."""
    if str(user_info_id) == str(admin.get("sub")):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You cannot delete your own account here.",
        )
    from src.auth.account_deletion import delete_user_and_data, purge_user_files

    with get_session() as sess:
        if sess.get(UserInfo, user_info_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )
        delete_user_and_data(sess, user_info_id)
    purge_user_files(user_info_id)

    _log.info("Admin deleted user_info_id=%s", user_info_id)
    return {"ok": True}
