"""Backup management endpoints — list and restore SQLite backups."""
from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_current_user
from models.user import UserInfo
from src.backup.backup_service import list_backups, restore_db

router = APIRouter(prefix="/api/backup", tags=["backup"])


@router.get("/")
async def get_backups(_user: UserInfo = Depends(get_current_user)) -> list[dict]:
    """Return all available backups, newest-first."""
    return list_backups()


@router.post("/{date}/restore")
async def restore_backup(
    date: str, _user: UserInfo = Depends(get_current_user)
) -> dict:
    """Restore the database to the backup taken on *date* (YYYY-MM-DD)."""
    try:
        restore_db(date)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"No backup found for {date}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "restored", "date": date}
