"""Full account deletion — every row and file owned by a user.

Shared by the self-service ``DELETE /api/auth/me`` and the admin-triggered
``DELETE /api/admin/users/{id}``. A single implementation avoids the two paths
drifting out of sync (or one of them leaking data the other cleans up).

DB rows are deleted first (children before parents, matching FK direction even
though SQLite enforcement is off in this project — Postgres deployments do
enforce it). On-disk files live under ``data/users/{id}/`` and must be purged
*outside* the DB session, mirroring the storage-walk pattern in
``src.admin.storage``.
"""
from __future__ import annotations

import shutil

from sqlmodel import Session, select

from models.project_db import (
    DBEncounter,
    DBMemory,
    DBMemoryComment,
    DBMemoryLike,
    DBMemoryTranslation,
    DBPerson,
    DBPersonGroup,
    DBProject,
    DBProjectInvite,
    DBProjectItem,
    DBProjectMember,
    DBProjectSyncMeta,
    DBActivity,
    DBShareMemoryContent,
    DBShareVisit,
    DBStravaCache,
    DBDeviceKey,
    DBJournalEntry,
    DBRecoveryWrap,
)
from models.user import LocalUser, PolarstepsToken, StravaToken, UserInfo
from src.admin import storage as _storage_mod


def delete_user_and_data(sess: Session, user_info_id: int) -> None:
    """Delete a ``UserInfo`` and every row it owns, directly or via a project.

    Commits internally. Does not touch the filesystem — call
    :func:`purge_user_files` afterwards, outside any DB session.
    """
    project_ids = sess.exec(
        select(DBProject.id).where(DBProject.user_info_id == user_info_id)
    ).all()
    memory_ids = sess.exec(
        select(DBMemory.id).where(DBMemory.project_id.in_(project_ids))
    ).all() if project_ids else []

    def _delete_all(model, *conditions) -> None:
        for row in sess.exec(select(model).where(*conditions)).all():
            sess.delete(row)

    if memory_ids:
        _delete_all(DBMemoryComment, DBMemoryComment.memory_id.in_(memory_ids))
        _delete_all(DBMemoryLike, DBMemoryLike.memory_id.in_(memory_ids))
        _delete_all(DBMemoryTranslation, DBMemoryTranslation.memory_id.in_(memory_ids))
        _delete_all(DBShareMemoryContent, DBShareMemoryContent.memory_id.in_(memory_ids))
    # Comments/likes/visits this user made on other people's shared projects.
    _delete_all(DBMemoryComment, DBMemoryComment.user_info_id == user_info_id)
    _delete_all(DBMemoryLike, DBMemoryLike.user_info_id == user_info_id)
    _delete_all(DBShareVisit, DBShareVisit.user_info_id == user_info_id)

    # Travel-companion footprint (issue #106): rows this user left in OTHER
    # users' projects, and membership/invite rows in both directions. Items
    # first (they reference the journal entries / activities being removed);
    # own-project rows are covered again by the project block below, which is
    # harmless. The user's journal photo files live under
    # ``data/users/{id}/journal/`` and are removed by purge_user_files.
    authored_journal_ids = sess.exec(
        select(DBJournalEntry.id).where(DBJournalEntry.user_info_id == user_info_id)
    ).all()
    if authored_journal_ids:
        _delete_all(DBProjectItem, DBProjectItem.journal_id.in_(authored_journal_ids))
        _delete_all(DBJournalEntry, DBJournalEntry.id.in_(authored_journal_ids))
    activity_ids = sess.exec(
        select(DBActivity.id).where(DBActivity.user_info_id == user_info_id)
    ).all()
    if activity_ids:
        _delete_all(DBProjectItem, DBProjectItem.activity_id.in_(activity_ids))
    _delete_all(DBProjectMember, DBProjectMember.user_info_id == user_info_id)
    _delete_all(DBProjectInvite, DBProjectInvite.created_by == user_info_id)
    if project_ids:
        _delete_all(DBProjectMember, DBProjectMember.project_id.in_(project_ids))
        _delete_all(DBProjectInvite, DBProjectInvite.project_id.in_(project_ids))

    if project_ids:
        _delete_all(DBMemory, DBMemory.project_id.in_(project_ids))
        _delete_all(DBJournalEntry, DBJournalEntry.project_id.in_(project_ids))
        _delete_all(DBEncounter, DBEncounter.project_id.in_(project_ids))
        _delete_all(DBPerson, DBPerson.project_id.in_(project_ids))
        _delete_all(DBPersonGroup, DBPersonGroup.project_id.in_(project_ids))
        _delete_all(DBShareVisit, DBShareVisit.project_id.in_(project_ids))
        _delete_all(DBProjectSyncMeta, DBProjectSyncMeta.project_id.in_(project_ids))
        _delete_all(DBProjectItem, DBProjectItem.project_id.in_(project_ids))
        _delete_all(DBProject, DBProject.id.in_(project_ids))

    _delete_all(DBActivity, DBActivity.user_info_id == user_info_id)
    _delete_all(DBStravaCache, DBStravaCache.user_info_id == user_info_id)
    _delete_all(StravaToken, StravaToken.user_info_id == user_info_id)
    _delete_all(PolarstepsToken, PolarstepsToken.user_info_id == user_info_id)
    _delete_all(DBDeviceKey, DBDeviceKey.user_info_id == user_info_id)
    _delete_all(DBRecoveryWrap, DBRecoveryWrap.user_info_id == user_info_id)

    user_info = sess.get(UserInfo, user_info_id)
    local_auth_id = user_info.local_auth_id if user_info else None
    if user_info is not None:
        sess.delete(user_info)
    sess.flush()

    if local_auth_id is not None:
        local_user = sess.get(LocalUser, local_auth_id)
        if local_user is not None:
            sess.delete(local_user)

    sess.commit()


def purge_user_files(user_id: int) -> None:
    """Remove ``data/users/{id}/`` (photos, avatars, …). No-op if absent."""
    shutil.rmtree(_storage_mod._user_dir(user_id), ignore_errors=True)
