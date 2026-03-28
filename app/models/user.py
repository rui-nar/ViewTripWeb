"""Extended user model stored alongside reflex-local-auth's LocalUser."""
from typing import Optional

import sqlmodel


class UserInfo(sqlmodel.SQLModel, table=True):
    """Stores profile data for each registered user.

    Linked to LocalUser (reflex-local-auth) via local_auth_id.
    For Google-only users, local_auth_id still exists (we create a shadow
    LocalUser) so the session/auth_token mechanism works uniformly.
    """

    id: int | None = sqlmodel.Field(default=None, primary_key=True)
    local_auth_id: int | None = sqlmodel.Field(
        default=None, foreign_key="localuser.id"
    )
    google_sub: str = sqlmodel.Field(default="")  # Google subject identifier
    display_name: str = sqlmodel.Field(default="")
    email: str = sqlmodel.Field(default="", index=True)
    avatar_url: str = sqlmodel.Field(default="")
    auth_provider: str = sqlmodel.Field(default="local")  # "local" | "google"

    # TODO: Apple Sign-In — add apple_sub field when implemented
    # TODO: Facebook Login — add facebook_id field when implemented


class StravaToken(sqlmodel.SQLModel, table=True):
    """Stores per-user Strava OAuth tokens."""

    id: Optional[int] = sqlmodel.Field(default=None, primary_key=True)
    user_info_id: int = sqlmodel.Field(
        foreign_key="userinfo.id", unique=True, index=True
    )
    access_token: str = sqlmodel.Field(default="")
    refresh_token: str = sqlmodel.Field(default="")
    expires_at: float = sqlmodel.Field(default=0.0)  # Unix timestamp
