"""REST auth endpoints consumed by Flutter (and any non-Reflex client).

Routes:
    POST   /api/auth/token           — email + password → JWT
    POST   /api/auth/register        — create account → JWT
    POST   /api/auth/google          — Google id_token → JWT
    GET    /api/auth/me              — current user profile
    PUT    /api/auth/me              — update display name → refreshed JWT
    POST   /api/auth/change-password — change password (local accounts only)
    DELETE /api/auth/me              — delete account + all associated data
"""
from __future__ import annotations

from typing import Annotated

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from google.auth.transport import requests as google_requests
from google.oauth2.id_token import verify_oauth2_token
from pydantic import BaseModel
from sqlmodel import select

from models.db import get_session
from models.user import LocalUser

from models.user import UserInfo
from api.deps import create_access_token, get_current_user
from src.config.settings import Config

router = APIRouter(prefix="/api/auth", tags=["auth"])

_cfg = Config("config/config.json")
_google_client_id = _cfg.get("google.client_id") or ""


# ── Request / response schemas ────────────────────────────────────────────────

class TokenRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""

class GoogleTokenRequest(BaseModel):
    id_token: str  # JWT credential from Google (One Tap or GIS)

class UpdateProfileRequest(BaseModel):
    display_name: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


# ── Helpers ───────────────────────────────────────────────────────────────────

def _user_info_for_local_id(sess, local_auth_id: int) -> UserInfo | None:
    return sess.exec(
        select(UserInfo).where(UserInfo.local_auth_id == local_auth_id)
    ).first()


def _token_response(user_info: UserInfo) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user_info),
        user={
            "id": user_info.id,
            "email": user_info.email,
            "display_name": user_info.display_name,
            "avatar_url": user_info.avatar_url,
            "auth_provider": user_info.auth_provider,
        },
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/token", response_model=TokenResponse)
def login(body: TokenRequest):
    """Email + password login — returns a JWT."""
    with get_session() as sess:
        user = sess.exec(
            select(LocalUser).where(LocalUser.username == body.username)
        ).first()
        if not user or not user.enabled or not user.verify(body.password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )
        user_info = _user_info_for_local_id(sess, user.id)
        if user_info is None:
            # Auto-create UserInfo for legacy local-auth users
            user_info = UserInfo(
                local_auth_id=user.id,
                display_name=user.username,
                email="",
                auth_provider="local",
            )
            sess.add(user_info)
            sess.commit()
            sess.refresh(user_info)
        return _token_response(user_info)


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest):
    """Create a new local account — returns a JWT."""
    with get_session() as sess:
        existing = sess.exec(
            select(LocalUser).where(LocalUser.username == body.username)
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username already taken",
            )
        local_user = LocalUser()  # type: ignore
        local_user.username = body.username
        local_user.password_hash = LocalUser.hash_password(body.password)
        local_user.enabled = True
        sess.add(local_user)
        sess.commit()
        sess.refresh(local_user)

        user_info = UserInfo(
            local_auth_id=local_user.id,
            display_name=body.display_name or body.username,
            email="",
            auth_provider="local",
        )
        sess.add(user_info)
        sess.commit()
        sess.refresh(user_info)
        return _token_response(user_info)


@router.post("/google", response_model=TokenResponse)
def google_login(body: GoogleTokenRequest):
    """Verify a Google id_token and return a JWT (for Flutter / native clients)."""
    if not _google_client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google auth not configured",
        )
    try:
        id_info = verify_oauth2_token(
            body.id_token, google_requests.Request(), _google_client_id
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google id_token",
        )

    google_sub = id_info["sub"]
    email = id_info.get("email", "")
    name = id_info.get("name", "") or email.split("@")[0]
    picture = id_info.get("picture", "")

    with get_session() as sess:
        user_info = sess.exec(
            select(UserInfo).where(UserInfo.google_sub == google_sub)
        ).first()

        if user_info is None:
            shadow = LocalUser()  # type: ignore
            shadow.username = f"google_{google_sub[:16]}"
            shadow.password_hash = b""
            shadow.enabled = True
            sess.add(shadow)
            sess.commit()
            sess.refresh(shadow)

            user_info = UserInfo(
                local_auth_id=shadow.id,
                google_sub=google_sub,
                display_name=name,
                email=email,
                avatar_url=picture,
                auth_provider="google",
            )
            sess.add(user_info)
            sess.commit()
            sess.refresh(user_info)

        return _token_response(user_info)


@router.get("/me")
def me(current_user: Annotated[dict, Depends(get_current_user)]):
    """Return the current user's profile from the JWT payload."""
    return current_user


@router.put("/me", response_model=TokenResponse)
def update_me(
    body: UpdateProfileRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Update display name and return a refreshed JWT."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        user_info = sess.get(UserInfo, user_info_id)
        if user_info is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        user_info.display_name = body.display_name.strip()
        sess.add(user_info)
        sess.commit()
        sess.refresh(user_info)
        return _token_response(user_info)


@router.post("/change-password")
def change_password(
    body: ChangePasswordRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Change password — local (email) accounts only."""
    if current_user.get("auth_provider") != "local":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password change is only available for email accounts",
        )
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        user_info = sess.get(UserInfo, user_info_id)
        if user_info is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        local_user = sess.get(LocalUser, user_info.local_auth_id)
        if local_user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Local user not found")
        if not local_user.verify(body.current_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Current password is incorrect",
            )
        local_user.password_hash = LocalUser.hash_password(body.new_password)
        sess.add(local_user)
        sess.commit()
    return {"ok": True}


@router.delete("/me")
def delete_account(current_user: Annotated[dict, Depends(get_current_user)]):
    """Delete the current user's account and all associated data."""
    from models.project_db import DBActivity, DBProject, DBProjectItem, DBStravaCache
    from models.user import StravaToken

    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        user_info = sess.get(UserInfo, user_info_id)
        if user_info is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        # Delete project items and projects
        project_rows = sess.exec(
            select(DBProject).where(DBProject.user_info_id == user_info_id)
        ).all()
        for proj in project_rows:
            items = sess.exec(
                select(DBProjectItem).where(DBProjectItem.project_id == proj.id)
            ).all()
            for item in items:
                sess.delete(item)
        for proj in project_rows:
            sess.delete(proj)

        # Delete activities
        for act in sess.exec(
            select(DBActivity).where(DBActivity.user_info_id == user_info_id)
        ).all():
            sess.delete(act)

        # Delete Strava cache
        cache = sess.get(DBStravaCache, user_info_id)
        if cache:
            sess.delete(cache)

        # Delete Strava token
        token = sess.exec(
            select(StravaToken).where(StravaToken.user_info_id == user_info_id)
        ).first()
        if token:
            sess.delete(token)

        # Delete UserInfo then LocalUser
        local_auth_id = user_info.local_auth_id
        sess.delete(user_info)
        sess.flush()

        if local_auth_id:
            local_user = sess.get(LocalUser, local_auth_id)
            if local_user:
                sess.delete(local_user)

        sess.commit()
    return {"ok": True}
