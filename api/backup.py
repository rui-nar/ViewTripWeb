"""Backup management endpoints — list and restore SQLite backups."""
from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_current_user
from models.user import UserInfo
from src.backup.backup_service import list_backups, restore_db

router = APIRouter(prefix="/api/backup", tags=["backup"])


@router.get("/", summary="List database backups")
async def get_backups(_user: UserInfo = Depends(get_current_user)) -> list[dict]:
    """Return all available daily SQLite backups, newest-first.

    Each entry is ``{date: "YYYY-MM-DD", size_bytes: int}``. Backups are taken
    automatically every day at 02:00 UTC and retained for 30 days.
    """
    return list_backups()


@router.post("/{date}/restore", summary="Restore a database backup")
async def restore_backup(
    date: str, _user: UserInfo = Depends(get_current_user)
) -> dict:
    """Restore the database to the backup taken on *date* (YYYY-MM-DD).

    Overwrites the live database with the chosen backup and disposes the
    connection pool so new requests use the restored data. Returns 404 if no
    backup exists for that date.
    """
    try:
        restore_db(date)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"No backup found for {date}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "restored", "date": date}
