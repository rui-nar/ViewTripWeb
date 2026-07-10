"""Idempotent bootstrap of the default admin account.

Called from the FastAPI lifespan after migrations run. Creates a ``LocalUser``
named ``admin`` (password ``admin``) plus its ``UserInfo`` (``is_admin=True``)
with ``password_change_required=True`` so the operator is forced to change the
default password on first login. Does nothing if an ``admin`` LocalUser already
exists, so it is safe to run on every startup.
"""
from __future__ import annotations

from sqlmodel import select

from models.db import get_session
from models.user import LocalUser, UserInfo
from src.utils.logging import get_logger

_log = get_logger(__name__)

_ADMIN_USERNAME = "admin"
_ADMIN_INITIAL_PASSWORD = "admin"


def seed_admin() -> None:
    """Create the default admin account if no ``admin`` LocalUser exists."""
    with get_session() as sess:
        existing = sess.exec(
            select(LocalUser).where(LocalUser.username == _ADMIN_USERNAME)
        ).first()
        if existing is not None:
            return

        local_user = LocalUser(
            username=_ADMIN_USERNAME,
            password_hash=LocalUser.hash_password(_ADMIN_INITIAL_PASSWORD),
            enabled=True,
            password_change_required=True,
        )
        sess.add(local_user)
        sess.commit()
        sess.refresh(local_user)

        user_info = UserInfo(
            local_auth_id=local_user.id,
            display_name=_ADMIN_USERNAME,
            email="",
            auth_provider="local",
            is_admin=True,
        )
        sess.add(user_info)
        sess.commit()
        _log.info("Seeded default admin account (password change required)")
