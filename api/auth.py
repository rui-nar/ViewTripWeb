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
from pydantic import BaseModel, Field
from sqlmodel import select

from models.db import get_session
from models.user import LocalUser

from models.user import UserInfo
from api.deps import create_access_token, get_current_user
import os

from src.config.settings import Config
from src.utils.logging import get_logger

_log = get_logger(__name__)

# Google mints id_tokens against its own clock. Without a tolerance, a server
# whose clock lags by even a second rejects fresh tokens as "used too early".
# A small skew window absorbs normal NTP drift on any host (dev or deployed)
# without meaningfully weakening verification. Google's libraries support this
# exact knob for this exact reason.
_GOOGLE_CLOCK_SKEW_SECONDS = 10

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Env var takes priority; fall back to config file for local dev.
_google_client_id = (
    os.environ.get("GOOGLE_CLIENT_ID")
    or Config("config/config.json").get("google.client_id")
    or ""
)


def _admin_emails() -> set[str]:
    """Case-insensitive set of emails promoted to admin via ADMIN_EMAILS.

    Comma-separated; whitespace and empty entries ignored. Read at call time so
    tests (and ops) can set it without reimporting the module.
    """
    raw = os.environ.get("ADMIN_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def _is_admin_email(email: str) -> bool:
    return bool(email) and email.lower() in _admin_emails()


# ── Request / response schemas ────────────────────────────────────────────────

class TokenRequest(BaseModel):
    username: str = Field(description="Email address or username")
    password: str = Field(description="Account password")

class RegisterRequest(BaseModel):
    username: str = Field(description="Email address or username")
    password: str = Field(description="Account password")
    display_name: str = Field("", description="Public display name (defaults to username)")

class GoogleTokenRequest(BaseModel):
    id_token: str = Field(description="JWT credential from Google One Tap or GIS")

class UpdateProfileRequest(BaseModel):
    display_name: str = Field(description="New public display name")

class ChangePasswordRequest(BaseModel):
    current_password: str = Field(description="Current password for verification")
    new_password: str = Field(description="New password to set")

class TokenResponse(BaseModel):
    access_token: str = Field(description="JWT bearer token")
    token_type: str = Field("bearer", description="Always 'bearer'")
    user: dict = Field(description="User profile (id, email, display_name, avatar_url, auth_provider)")

class OkOut(BaseModel):
    ok: bool = Field(True, description="Always true on success")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _user_info_for_local_id(sess, local_auth_id: int) -> UserInfo | None:
    return sess.exec(
        select(UserInfo).where(UserInfo.local_auth_id == local_auth_id)
    ).first()


def _token_response(
    user_info: UserInfo, password_change_required: bool = False
) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user_info, password_change_required),
        user={
            "id": user_info.id,
            "email": user_info.email,
            "display_name": user_info.display_name,
            "avatar_url": user_info.avatar_url,
            "auth_provider": user_info.auth_provider,
            "is_admin": bool(user_info.is_admin),
            "password_change_required": bool(password_change_required),
        },
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/token", response_model=TokenResponse, summary="Login with email + password")
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
        # Promote to admin if this account's email/username is in ADMIN_EMAILS.
        promote = _is_admin_email(user_info.email) or _is_admin_email(user.username)
        if promote and not user_info.is_admin:
            user_info.is_admin = True
            sess.add(user_info)
            sess.commit()
            sess.refresh(user_info)
        return _token_response(user_info, user.password_change_required)


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED,
             summary="Register a new account")
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
            is_admin=_is_admin_email(body.username),
        )
        sess.add(user_info)
        sess.commit()
        sess.refresh(user_info)
        return _token_response(user_info)


@router.post("/google", response_model=TokenResponse, summary="Login with Google")
def google_login(body: GoogleTokenRequest):
    """Verify a Google id_token and return a JWT (for Flutter / native clients)."""
    if not _google_client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google auth not configured",
        )
    try:
        id_info = verify_oauth2_token(
            body.id_token,
            google_requests.Request(),
            _google_client_id,
            clock_skew_in_seconds=_GOOGLE_CLOCK_SKEW_SECONDS,
        )
    except Exception as exc:
        # google-auth raises ValueError with a specific reason (expired token,
        # clock skew "used too early", wrong issuer/audience, bad signature).
        # The client only ever sees a generic 401, so log the real reason here —
        # without it every Google auth failure is undiagnosable.
        _log.warning("Google id_token verification failed: %s", exc)
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
                is_admin=_is_admin_email(email),
            )
            sess.add(user_info)
            sess.commit()
            sess.refresh(user_info)
        elif _is_admin_email(user_info.email) and not user_info.is_admin:
            user_info.is_admin = True
            sess.add(user_info)
            sess.commit()
            sess.refresh(user_info)

        return _token_response(user_info)


@router.get("/me", summary="Get current user profile")
def me(current_user: Annotated[dict, Depends(get_current_user)]):
    """Return the current user's profile decoded from the JWT."""
    return current_user


@router.put("/me", response_model=TokenResponse, summary="Update display name")
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


@router.post("/change-password", response_model=TokenResponse, summary="Change password")
def change_password(
    body: ChangePasswordRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Change password — local (email) accounts only. Returns 403 for Google accounts.

    Returns a fresh JWT (like PUT /me) rather than just {"ok": true}: the old
    token still carries password_change_required=True as a baked-in claim, so
    without a new token the client has no way to learn the flag cleared.
    """
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
        # A successful change satisfies any forced-change requirement.
        local_user.password_change_required = False
        sess.add(local_user)
        sess.commit()
        sess.refresh(user_info)
        return _token_response(user_info, local_user.password_change_required)


@router.delete("/me", response_model=OkOut, summary="Delete account")
def delete_account(current_user: Annotated[dict, Depends(get_current_user)]):
    """Permanently delete the current user's account and all associated data."""
    from src.auth.account_deletion import delete_user_and_data, purge_user_files

    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        if sess.get(UserInfo, user_info_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        delete_user_and_data(sess, user_info_id)
    purge_user_files(user_info_id)
    return {"ok": True}
