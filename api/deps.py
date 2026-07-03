"""FastAPI dependencies — JWT Bearer authentication for the REST API.

Flutter (and any non-Reflex client) authenticates via:
    Authorization: Bearer <jwt>

The JWT is obtained from POST /api/auth/token (password flow)
or POST /api/auth/google (Google id_token flow).
"""
from __future__ import annotations

import os
import datetime
from typing import Annotated, Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import select

from models.db import get_session
from models.user import UserInfo

# Secret key — set JWT_SECRET in your environment or config.
# For local dev a fallback is used; in production always set the env var.
_JWT_SECRET = os.environ.get("JWT_SECRET", "change-me-in-production")
_JWT_ALGORITHM = "HS256"
_JWT_EXPIRY_HOURS = 24 * 7  # 7 days


def create_access_token(
    user_info: UserInfo, password_change_required: bool = False
) -> str:
    """Create a signed JWT for the given UserInfo.

    ``password_change_required`` is carried from the LocalUser row (it lives on
    the credential, not the profile) so the client can force a password change
    before granting access to the app.
    """
    payload = {
        "sub": str(user_info.id),
        "local_auth_id": user_info.local_auth_id,
        "email": user_info.email,
        "display_name": user_info.display_name,
        "avatar_url": user_info.avatar_url,
        "auth_provider": user_info.auth_provider,
        "is_admin": bool(user_info.is_admin),
        "password_change_required": bool(password_change_required),
        "exp": datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(hours=_JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and verify a JWT. Raises HTTPException on failure."""
    try:
        return jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )


_bearer = HTTPBearer()
_optional_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> dict:
    """FastAPI dependency — validates JWT and returns the decoded payload."""
    return decode_token(credentials.credentials)


def get_optional_current_user(
    credentials: Annotated[
        Optional[HTTPAuthorizationCredentials], Depends(_optional_bearer)
    ],
) -> Optional[dict]:
    """FastAPI dependency — returns the decoded JWT payload if a valid Bearer
    token is present, or None if no token was supplied.  Never raises 401.
    Used on public endpoints that want to behave differently for logged-in users.
    """
    if credentials is None:
        return None
    try:
        return decode_token(credentials.credentials)
    except HTTPException:
        return None


def require_admin(
    current_user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """FastAPI dependency — 403 unless the caller is an admin.

    Re-reads ``is_admin`` from the DB rather than trusting the (possibly stale)
    token claim, so revoking admin takes effect immediately. Unauthenticated
    callers already get a 401 from ``get_current_user``.
    """
    try:
        user_info_id = int(current_user["sub"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )
    with get_session() as sess:
        user_info = sess.get(UserInfo, user_info_id)
        if user_info is None or not user_info.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required",
            )
    return current_user
