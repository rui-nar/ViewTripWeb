"""Extended user model stored alongside reflex-local-auth's LocalUser."""
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
