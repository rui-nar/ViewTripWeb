"""User-related database models."""
from __future__ import annotations

import time
from typing import Optional

import bcrypt
import sqlmodel


class LocalUser(sqlmodel.SQLModel, table=True):
    """Stores credentials for local (username + password) accounts."""

    __tablename__ = "localuser"

    id: int | None = sqlmodel.Field(default=None, primary_key=True)
    username: str = sqlmodel.Field(default="", unique=True, index=True)
    password_hash: bytes = sqlmodel.Field(default=b"")
    enabled: bool = sqlmodel.Field(default=True)
    # Forces a password change on next login (seeded admin, admin-reset accounts).
    password_change_required: bool = sqlmodel.Field(default=False)

    @staticmethod
    def hash_password(password: str) -> bytes:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt())

    def verify(self, password: str) -> bool:
        if not self.password_hash:
            return False
        return bcrypt.checkpw(password.encode(), self.password_hash)


class UserInfo(sqlmodel.SQLModel, table=True):
    """Stores profile data for each registered user."""

    id: int | None = sqlmodel.Field(default=None, primary_key=True)
    local_auth_id: int | None = sqlmodel.Field(
        default=None, foreign_key="localuser.id"
    )
    google_sub: str = sqlmodel.Field(default="")
    display_name: str = sqlmodel.Field(default="")
    email: str = sqlmodel.Field(default="", index=True)
    avatar_url: str = sqlmodel.Field(default="")
    auth_provider: str = sqlmodel.Field(default="local")  # "local" | "google"
    is_admin: bool = sqlmodel.Field(default=False)
    created_at: float = sqlmodel.Field(default_factory=time.time)
    # E2EE (issue #26): True once the user has enabled client-side encryption.
    # The server still holds no keys; this only signals clients to expect
    # ciphertext for in-scope fields. Backed by device_key / recovery_wrap rows.
    encryption_enabled: bool = sqlmodel.Field(default=False)


class StravaToken(sqlmodel.SQLModel, table=True):
    """Stores per-user Strava OAuth tokens."""

    id: Optional[int] = sqlmodel.Field(default=None, primary_key=True)
    user_info_id: int = sqlmodel.Field(
        foreign_key="userinfo.id", unique=True, index=True
    )
    access_token: str = sqlmodel.Field(default="")
    refresh_token: str = sqlmodel.Field(default="")
    expires_at: float = sqlmodel.Field(default=0.0)


class PolarstepsToken(sqlmodel.SQLModel, table=True):
    """Stores per-user Polarsteps remember_token (unofficial API cookie)."""

    id: Optional[int] = sqlmodel.Field(default=None, primary_key=True)
    user_info_id: int = sqlmodel.Field(
        foreign_key="userinfo.id", unique=True, index=True
    )
    remember_token: str = sqlmodel.Field(default="")
    polarsteps_user_id: int = sqlmodel.Field(default=0)
    polarsteps_username: str = sqlmodel.Field(default="")
