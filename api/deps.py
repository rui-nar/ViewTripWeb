"""FastAPI dependencies — JWT Bearer authentication for the REST API.

Flutter (and any non-Reflex client) authenticates via:
    Authorization: Bearer <jwt>

The JWT is obtained from POST /api/auth/token (password flow)
or POST /api/auth/google (Google id_token flow).
"""
from __future__ import annotations

import os
import datetime
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import select

import reflex as rx
from reflex_local_auth.user import LocalUser
from app.models.user import UserInfo

# Secret key — set JWT_SECRET in your environment or config.
# For local dev a fallback is used; in production always set the env var.
_JWT_SECRET = os.environ.get("JWT_SECRET", "change-me-in-production")
_JWT_ALGORITHM = "HS256"
_JWT_EXPIRY_HOURS = 24 * 7  # 7 days


def create_access_token(user_info: UserInfo) -> str:
    """Create a signed JWT for the given UserInfo."""
    payload = {
        "sub": str(user_info.id),
        "local_auth_id": user_info.local_auth_id,
        "email": user_info.email,
        "display_name": user_info.display_name,
        "avatar_url": user_info.avatar_url,
        "auth_provider": user_info.auth_provider,
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


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> dict:
    """FastAPI dependency — validates JWT and returns the decoded payload."""
    return decode_token(credentials.credentials)
