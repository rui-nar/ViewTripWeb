"""REST memories endpoints — CRUD and photo management for project memories.

Routes:
    POST   /api/memories                            — create a memory
    PUT    /api/memories/{id}                       — update a memory
    DELETE /api/memories/{id}                       — delete a memory + its photos
    POST   /api/memories/{id}/photos                — upload a photo
    DELETE /api/memories/{id}/photos/{uuid}         — delete a specific photo
    GET    /api/memories/{id}/photos/{uuid}         — serve full-res photo
    GET    /api/memories/{id}/photos/{uuid}/thumb   — serve thumbnail
"""
from __future__ import annotations

import io
import json
import os
import uuid as uuid_lib
from pathlib import Path
from typing import Annotated, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from models.db import get_session
from PIL import Image
from pydantic import BaseModel
from sqlmodel import select

from api.deps import get_current_user
from models.project_db import DBMemory, DBProject, DBProjectItem
from src.models.memory import Memory

router = APIRouter(prefix="/api/memories", tags=["memories"])

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_THUMB_SIZE = (400, 400)


def _photo_dir(user_id: str, memory_id: int) -> Path:
    p = Path(_DATA_DIR) / "users" / user_id / "memories" / str(memory_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _resolve_geo(
    sess, project_id: int, date: str, geo_mode: str
) -> tuple[Optional[float], Optional[float]]:
    """Resolve (lat, lon) from activities on *date* according to *geo_mode*."""
    if geo_mode == "custom":
        return None, None  # caller supplies lat/lon directly

    # Find all activities in the project that fall on the given date
    items = sess.exec(
        select(DBProjectItem).where(
            DBProjectItem.project_id == project_id,
            DBProjectItem.item_type == "activity",
        )
    ).all()
    if not items:
        return None, None

    from models.project_db import DBActivity
    activity_ids = [i.activity_id for i in items if i.activity_id is not None]
    if not activity_ids:
        return None, None

    act_rows = sess.exec(
        select(DBActivity).where(DBActivity.id.in_(activity_ids))
    ).all()

    # Filter to activities whose local date matches
    def _date_of(row) -> str:
        return (row.start_date_local or "")[:10]

    day_acts = [r for r in act_rows if _date_of(r) == date]
    if not day_acts:
        return None, None

    # Sort by start time
    day_acts.sort(key=lambda r: r.start_date_local or "")

    if geo_mode == "start_of_day":
        row = day_acts[0]
        latlng = json.loads(row.start_latlng_json) if row.start_latlng_json else None
        if latlng and len(latlng) >= 2:
            return float(latlng[0]), float(latlng[1])
    elif geo_mode == "end_of_day":
        row = day_acts[-1]
        latlng = json.loads(row.end_latlng_json) if row.end_latlng_json else None
        if latlng and len(latlng) >= 2:
            return float(latlng[0]), float(latlng[1])

    return None, None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _row_to_memory(row: DBMemory) -> Memory:
    return Memory(
        id=row.id,
        project_id=row.project_id,
        name=row.name,
        date=row.date,
        time=row.time,
        description=row.description,
        photos=json.loads(row.photos_json or "[]"),
        geo_mode=row.geo_mode,
        lat=row.lat,
        lon=row.lon,
    )


def _get_project_id(sess, user_info_id: int, project_name: str) -> int:
    row = sess.exec(
        select(DBProject).where(
            DBProject.user_info_id == user_info_id,
            DBProject.name == project_name,
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return row.id


def _get_owned_memory(sess, memory_id: int, user_info_id: int) -> DBMemory:
    """Return the DBMemory row, verifying the caller owns the parent project."""
    mem_row = sess.get(DBMemory, memory_id)
    if mem_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
    project_row = sess.get(DBProject, mem_row.project_id)
    if project_row is None or project_row.user_info_id != user_info_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return mem_row


# ── CRUD ─────────────────────────────────────────────────────────────────────

class MemoryBody(BaseModel):
    project_name: str
    date: str
    geo_mode: str = "start_of_day"  # "start_of_day" | "end_of_day" | "custom"
    name: Optional[str] = None
    time: Optional[str] = None
    description: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    insert_after_index: Optional[int] = None  # POST only
    polarsteps_step_id: Optional[int] = None


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_memory(
    body: MemoryBody,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        project_id = _get_project_id(sess, user_info_id, body.project_name)

        lat, lon = body.lat, body.lon
        if body.geo_mode != "custom":
            lat, lon = _resolve_geo(sess, project_id, body.date, body.geo_mode)

        mem_row = DBMemory(
            project_id=project_id,
            name=body.name,
            date=body.date,
            time=body.time,
            description=body.description,
            photos_json="[]",
            geo_mode=body.geo_mode,
            lat=lat,
            lon=lon,
            polarsteps_step_id=body.polarsteps_step_id,
        )
        sess.add(mem_row)
        sess.flush()  # populate mem_row.id

        # Insert a DBProjectItem at the requested position
        existing_items = sess.exec(
            select(DBProjectItem)
            .where(DBProjectItem.project_id == project_id)
            .order_by(DBProjectItem.position)
        ).all()
        insert_at = len(existing_items)
        if body.insert_after_index is not None:
            insert_at = max(0, min(len(existing_items), body.insert_after_index + 1))

        # Shift later items
        for item in existing_items:
            if item.position >= insert_at:
                item.position += 1
                sess.add(item)

        db_item = DBProjectItem(
            project_id=project_id,
            position=insert_at,
            item_type="memory",
            memory_id=mem_row.id,
        )
        sess.add(db_item)
        sess.commit()
        memory_id = mem_row.id

    return {"id": memory_id}


class MemoryUpdateBody(BaseModel):
    date: str
    geo_mode: str = "start_of_day"
    name: Optional[str] = None
    time: Optional[str] = None
    description: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None


@router.put("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def update_memory(
    memory_id: int,
    body: MemoryUpdateBody,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        mem_row = _get_owned_memory(sess, memory_id, user_info_id)

        lat, lon = body.lat, body.lon
        if body.geo_mode != "custom":
            lat, lon = _resolve_geo(sess, mem_row.project_id, body.date, body.geo_mode)

        mem_row.name = body.name
        mem_row.date = body.date
        mem_row.time = body.time
        mem_row.description = body.description
        mem_row.geo_mode = body.geo_mode
        mem_row.lat = lat
        mem_row.lon = lon
        sess.add(mem_row)
        sess.commit()


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memory(
    memory_id: int,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        mem_row = _get_owned_memory(sess, memory_id, user_info_id)

        # Delete photo files from disk
        photos: List[str] = json.loads(mem_row.photos_json or "[]")
        photo_path = Path(_DATA_DIR) / "users" / current_user["sub"] / "memories" / str(memory_id)
        for photo_uuid in photos:
            for suffix in ["", "_thumb"]:
                f = photo_path / f"{photo_uuid}{suffix}.jpg"
                f.unlink(missing_ok=True)
        if photo_path.exists():
            try:
                photo_path.rmdir()
            except OSError:
                pass

        # Remove all DBProjectItem rows for this memory (guards against stale duplicates)
        item_rows = sess.exec(
            select(DBProjectItem).where(
                DBProjectItem.memory_id == memory_id
            )
        ).all()
        for item_row in item_rows:
            sess.delete(item_row)

        sess.delete(mem_row)
        sess.commit()


# ── Photos ────────────────────────────────────────────────────────────────────

def _save_photo_files(user_id: str, memory_id: int, uuid_str: str, raw: bytes) -> None:
    photo_path = _photo_dir(user_id, memory_id)
    (photo_path / f"{uuid_str}.jpg").write_bytes(raw)
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    img.thumbnail(_THUMB_SIZE, Image.LANCZOS)
    img.save(str(photo_path / f"{uuid_str}_thumb.jpg"), "JPEG", quality=85)


def _append_photo_to_memory(memory_id: int, uuid_str: str) -> None:
    with get_session() as sess:
        mem_row = sess.get(DBMemory, memory_id)
        if mem_row is None:
            return
        photos: List[str] = json.loads(mem_row.photos_json or "[]")
        photos.append(uuid_str)
        mem_row.photos_json = json.dumps(photos)
        sess.add(mem_row)
        sess.commit()


def _download_photo_from_url(memory_id: int, url: str, user_id: str) -> None:
    import requests as _req
    try:
        resp = _req.get(url, timeout=30)
        resp.raise_for_status()
    except Exception:
        return
    uuid_str = str(uuid_lib.uuid4())
    _save_photo_files(user_id, memory_id, uuid_str, resp.content)
    _append_photo_to_memory(memory_id, uuid_str)


class PhotoFromUrlIn(BaseModel):
    url: str


@router.post("/{memory_id}/photos", status_code=status.HTTP_201_CREATED)
async def upload_photo(
    memory_id: int,
    file: Annotated[UploadFile, File()],
    current_user: Annotated[dict, Depends(get_current_user)],
):
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        _get_owned_memory(sess, memory_id, user_info_id)
    raw = await file.read()
    photo_uuid = str(uuid_lib.uuid4())
    _save_photo_files(current_user["sub"], memory_id, photo_uuid, raw)
    _append_photo_to_memory(memory_id, photo_uuid)
    return {"uuid": photo_uuid}


@router.post("/{memory_id}/photos/from-url", status_code=202)
async def queue_photo_from_url(
    memory_id: int,
    body: PhotoFromUrlIn,
    background_tasks: BackgroundTasks,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        _get_owned_memory(sess, memory_id, user_info_id)
    background_tasks.add_task(_download_photo_from_url, memory_id, body.url, current_user["sub"])
    return {"queued": True}


@router.delete("/{memory_id}/photos/{photo_uuid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_photo(
    memory_id: int,
    photo_uuid: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        mem_row = _get_owned_memory(sess, memory_id, user_info_id)
        photos: List[str] = json.loads(mem_row.photos_json or "[]")
        if photo_uuid not in photos:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Photo not found")

        photo_path = _photo_dir(current_user["sub"], memory_id)
        for suffix in ["", "_thumb"]:
            f = photo_path / f"{photo_uuid}{suffix}.jpg"
            f.unlink(missing_ok=True)

        photos.remove(photo_uuid)
        mem_row.photos_json = json.dumps(photos)
        sess.add(mem_row)
        sess.commit()


@router.get("/{memory_id}/photos/{photo_uuid}")
def serve_photo(
    memory_id: int,
    photo_uuid: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        mem_row = _get_owned_memory(sess, memory_id, user_info_id)
        photos: List[str] = json.loads(mem_row.photos_json or "[]")
        if photo_uuid not in photos:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Photo not found")

    photo_path = Path(_DATA_DIR) / "users" / current_user["sub"] / "memories" / str(memory_id)
    full_path = photo_path / f"{photo_uuid}.jpg"
    if not full_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return FileResponse(str(full_path), media_type="image/jpeg")


@router.get("/{memory_id}/photos/{photo_uuid}/thumb")
def serve_photo_thumb(
    memory_id: int,
    photo_uuid: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        mem_row = _get_owned_memory(sess, memory_id, user_info_id)
        photos: List[str] = json.loads(mem_row.photos_json or "[]")
        if photo_uuid not in photos:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Photo not found")

    photo_path = Path(_DATA_DIR) / "users" / current_user["sub"] / "memories" / str(memory_id)
    thumb_path = photo_path / f"{photo_uuid}_thumb.jpg"
    if not thumb_path.exists():
        # Fall back to full-res if thumb is missing
        full_path = photo_path / f"{photo_uuid}.jpg"
        if full_path.exists():
            return FileResponse(str(full_path), media_type="image/jpeg")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return FileResponse(str(thumb_path), media_type="image/jpeg")
