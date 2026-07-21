"""REST journal endpoints — CRUD and photo management for project journal entries.

Journal entries are private and per-user (issue #106): every project editor —
owner or travel companion — keeps their own entries, visible and editable only
by their author. They are never exposed in shared views.

Routes:
    POST   /api/journal                            — create a journal entry
    PUT    /api/journal/{id}                       — update a journal entry
    DELETE /api/journal/{id}                       — delete a journal entry + its photos
    POST   /api/journal/{id}/photos                — upload a photo
    POST   /api/journal/{id}/photos/from-url       — queue a photo download from URL
    DELETE /api/journal/{id}/photos/{uuid}         — delete a specific photo
    PUT    /api/journal/{id}/photos/{uuid}/replace — replace a photo's bytes in place
    GET    /api/journal/{id}/photos/{uuid}         — serve full-res photo
    GET    /api/journal/{id}/photos/{uuid}/thumb   — serve thumbnail
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
from pydantic import BaseModel, Field
from sqlmodel import select

from api.deps import get_current_user
from api.project_access import (
    OwnerParam,
    assert_project_access,
    journal_visible_row_positions,
    resolve_project,
    translate_insert_after,
)
from models.project_db import DBJournalEntry, DBProjectItem

router = APIRouter(prefix="/api/journal", tags=["journal"])

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_THUMB_SIZE = (400, 400)


# ── Response schemas ──────────────────────────────────────────────────────────

class IDOut(BaseModel):
    id: int = Field(description="ID of the newly created resource")


class UUIDOut(BaseModel):
    uuid: str = Field(description="UUID of the uploaded photo")


class QueuedOut(BaseModel):
    queued: bool = Field(description="True when the background download was scheduled")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _photo_dir(user_id: str, journal_id: int) -> Path:
    p = Path(_DATA_DIR) / "users" / user_id / "journal" / str(journal_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _get_owned_journal(sess, journal_id: int, user_info_id: int) -> DBJournalEntry:
    """Return the entry iff the caller is its author (issue #106).

    Order matters: 404 for an unknown entry, 403 when the caller has no access
    to the parent project, and 403 again when the entry belongs to another
    editor — only the author may read/update/delete an entry or manage its
    photos. A NULL author is a legacy row owned by the project owner.
    """
    row = sess.get(DBJournalEntry, journal_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Journal entry not found")
    project_row = assert_project_access(sess, user_info_id, row.project_id)
    author = row.user_info_id if row.user_info_id is not None else project_row.user_info_id
    if author != user_info_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return row


def _resolve_geo(sess, project_id: int, date: str, geo_mode: str):
    if geo_mode == "custom":
        return None, None
    from models.project_db import DBActivity
    items = sess.exec(
        select(DBProjectItem).where(
            DBProjectItem.project_id == project_id,
            DBProjectItem.item_type == "activity",
        )
    ).all()
    if not items:
        return None, None
    activity_ids = [i.activity_id for i in items if i.activity_id is not None]
    if not activity_ids:
        return None, None
    act_rows = sess.exec(select(DBActivity).where(DBActivity.id.in_(activity_ids))).all()
    day_acts = [r for r in act_rows if (r.start_date_local or "")[:10] == date]
    if not day_acts:
        return None, None
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


def _save_photo_files(user_id: str, journal_id: int, uuid_str: str, raw: bytes) -> None:
    photo_path = _photo_dir(user_id, journal_id)
    (photo_path / f"{uuid_str}.jpg").write_bytes(raw)
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    img.thumbnail(_THUMB_SIZE, Image.LANCZOS)
    img.save(str(photo_path / f"{uuid_str}_thumb.jpg"), "JPEG", quality=85)


def _append_photo(journal_id: int, uuid_str: str) -> None:
    with get_session() as sess:
        row = sess.get(DBJournalEntry, journal_id)
        if row is None:
            return
        photos: List[str] = json.loads(row.photos_json or "[]")
        photos.append(uuid_str)
        row.photos_json = json.dumps(photos)
        sess.add(row)
        sess.commit()


def _download_photo_from_url(journal_id: int, url: str, user_id: str) -> None:
    import requests as _req
    try:
        resp = _req.get(url, timeout=30)
        resp.raise_for_status()
    except Exception:
        return
    uuid_str = str(uuid_lib.uuid4())
    _save_photo_files(user_id, journal_id, uuid_str, resp.content)
    _append_photo(journal_id, uuid_str)


# ── Schemas ───────────────────────────────────────────────────────────────────

class JournalBody(BaseModel):
    project_name: str = Field(description="Project the journal entry belongs to")
    date: str = Field(description="Date of the entry (YYYY-MM-DD)")
    geo_mode: str = Field("start_of_day", description="How to resolve coordinates: 'start_of_day', 'end_of_day', or 'custom'")
    time: Optional[str] = Field(None, description="Optional time of day (HH:MM)")
    description: Optional[str] = Field(None, description="Journal entry text")
    lat: Optional[float] = Field(None, description="Latitude (required when geo_mode='custom')")
    lon: Optional[float] = Field(None, description="Longitude (required when geo_mode='custom')")
    insert_after_index: Optional[int] = Field(None, description="Position in the project item list to insert after")


class JournalUpdateBody(BaseModel):
    date: str = Field(description="Date of the entry (YYYY-MM-DD)")
    geo_mode: str = Field("start_of_day", description="How to resolve coordinates")
    time: Optional[str] = Field(None, description="Optional time of day (HH:MM)")
    description: Optional[str] = Field(None, description="Journal entry text")
    lat: Optional[float] = Field(None, description="Latitude (required when geo_mode='custom')")
    lon: Optional[float] = Field(None, description="Longitude (required when geo_mode='custom')")


class PhotoFromUrlIn(BaseModel):
    url: str = Field(description="Public URL of the image to download")


# ── CRUD ─────────────────────────────────────────────────────────────────────

@router.post("/", status_code=status.HTTP_201_CREATED, response_model=IDOut,
             summary="Create a journal entry")
def create_journal(
    body: JournalBody,
    current_user: Annotated[dict, Depends(get_current_user)],
    owner: OwnerParam = None,
):
    """Create a new private journal entry and insert it at the requested position."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        project_row = resolve_project(sess, user_info_id, body.project_name, owner)
        project_id = project_row.id
        owner_id = project_row.user_info_id

        lat, lon = body.lat, body.lon
        if body.geo_mode != "custom":
            lat, lon = _resolve_geo(sess, project_id, body.date, body.geo_mode)

        row = DBJournalEntry(
            project_id=project_id,
            user_info_id=user_info_id,
            date=body.date,
            time=body.time,
            description=body.description,
            photos_json="[]",
            geo_mode=body.geo_mode,
            lat=lat,
            lon=lon,
        )
        sess.add(row)
        sess.flush()

        existing_items = sess.exec(
            select(DBProjectItem)
            .where(DBProjectItem.project_id == project_id)
            .order_by(DBProjectItem.position)
        ).all()
        # insert_after_index is an index into the caller's *visible* item list
        # (other users' journal items are hidden) — translate it (issue #106).
        visible = journal_visible_row_positions(sess, existing_items, user_info_id, owner_id)
        insert_at = translate_insert_after(visible, body.insert_after_index, len(existing_items))

        for item in existing_items:
            if item.position >= insert_at:
                item.position += 1
                sess.add(item)

        db_item = DBProjectItem(
            project_id=project_id,
            position=insert_at,
            item_type="journal",
            journal_id=row.id,
        )
        sess.add(db_item)
        sess.commit()
        journal_id = row.id

    return {"id": journal_id}


@router.put("/{journal_id}", status_code=status.HTTP_204_NO_CONTENT,
            summary="Update a journal entry")
def update_journal(
    journal_id: int,
    body: JournalUpdateBody,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Update the text and metadata of an existing journal entry."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = _get_owned_journal(sess, journal_id, user_info_id)

        lat, lon = body.lat, body.lon
        if body.geo_mode != "custom":
            lat, lon = _resolve_geo(sess, row.project_id, body.date, body.geo_mode)

        row.date = body.date
        row.time = body.time
        row.description = body.description
        row.geo_mode = body.geo_mode
        row.lat = lat
        row.lon = lon
        sess.add(row)
        sess.commit()


@router.delete("/{journal_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Delete a journal entry")
def delete_journal(
    journal_id: int,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Delete a journal entry and all its photos from disk."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = _get_owned_journal(sess, journal_id, user_info_id)

        photos: List[str] = json.loads(row.photos_json or "[]")
        photo_path = Path(_DATA_DIR) / "users" / current_user["sub"] / "journal" / str(journal_id)
        for photo_uuid in photos:
            for suffix in ["", "_thumb"]:
                f = photo_path / f"{photo_uuid}{suffix}.jpg"
                f.unlink(missing_ok=True)
        if photo_path.exists():
            try:
                photo_path.rmdir()
            except OSError:
                pass

        item_row = sess.exec(
            select(DBProjectItem).where(DBProjectItem.journal_id == journal_id)
        ).first()
        if item_row:
            sess.delete(item_row)

        sess.delete(row)
        sess.commit()


# ── Photos ────────────────────────────────────────────────────────────────────

@router.post("/{journal_id}/photos", status_code=status.HTTP_201_CREATED,
             response_model=UUIDOut, summary="Upload a photo")
async def upload_photo(
    journal_id: int,
    file: Annotated[UploadFile, File()],
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Upload a JPEG photo to a journal entry; a 400×400 thumbnail is generated automatically."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        _get_owned_journal(sess, journal_id, user_info_id)
    raw = await file.read()
    photo_uuid = str(uuid_lib.uuid4())
    _save_photo_files(current_user["sub"], journal_id, photo_uuid, raw)
    _append_photo(journal_id, photo_uuid)
    return {"uuid": photo_uuid}


@router.post("/{journal_id}/photos/from-url", status_code=202,
             response_model=QueuedOut, summary="Queue a photo download from URL")
async def queue_photo_from_url(
    journal_id: int,
    body: PhotoFromUrlIn,
    background_tasks: BackgroundTasks,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Enqueue a background download of a photo from a public URL."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        _get_owned_journal(sess, journal_id, user_info_id)
    background_tasks.add_task(_download_photo_from_url, journal_id, body.url, current_user["sub"])
    return {"queued": True}


@router.delete("/{journal_id}/photos/{photo_uuid}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Delete a photo")
def delete_photo(
    journal_id: int,
    photo_uuid: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Remove a photo from a journal entry and delete its files from disk."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = _get_owned_journal(sess, journal_id, user_info_id)
        photos: List[str] = json.loads(row.photos_json or "[]")
        if photo_uuid not in photos:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Photo not found")

        photo_path = _photo_dir(current_user["sub"], journal_id)
        for suffix in ["", "_thumb"]:
            f = photo_path / f"{photo_uuid}{suffix}.jpg"
            f.unlink(missing_ok=True)

        photos.remove(photo_uuid)
        row.photos_json = json.dumps(photos)
        sess.add(row)
        sess.commit()


@router.put("/{journal_id}/photos/{old_uuid}/replace", status_code=status.HTTP_200_OK,
            response_model=UUIDOut, summary="Replace a photo")
async def replace_photo(
    journal_id: int,
    old_uuid: str,
    file: Annotated[UploadFile, File()],
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Replace a photo's bytes with a higher-quality upload, keeping its position in photos_json."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = _get_owned_journal(sess, journal_id, user_info_id)
        photos: List[str] = json.loads(row.photos_json or "[]")
        if old_uuid not in photos:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Photo not found")

    raw = await file.read()
    new_uuid = str(uuid_lib.uuid4())
    _save_photo_files(current_user["sub"], journal_id, new_uuid, raw)

    with get_session() as sess:
        row = sess.get(DBJournalEntry, journal_id)
        photos: List[str] = json.loads(row.photos_json or "[]")
        # In-place index replacement, not remove+append: photos_json order is display order.
        photos[photos.index(old_uuid)] = new_uuid
        row.photos_json = json.dumps(photos)
        sess.add(row)
        sess.commit()

    photo_path = _photo_dir(current_user["sub"], journal_id)
    for suffix in ["", "_thumb"]:
        f = photo_path / f"{old_uuid}{suffix}.jpg"
        f.unlink(missing_ok=True)

    return {"uuid": new_uuid}


@router.get("/{journal_id}/photos/{photo_uuid}", summary="Serve full-resolution photo")
def serve_photo(
    journal_id: int,
    photo_uuid: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Return the full-resolution JPEG for a journal photo."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = _get_owned_journal(sess, journal_id, user_info_id)
        photos: List[str] = json.loads(row.photos_json or "[]")
        if photo_uuid not in photos:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Photo not found")

    photo_path = Path(_DATA_DIR) / "users" / current_user["sub"] / "journal" / str(journal_id)
    full_path = photo_path / f"{photo_uuid}.jpg"
    if not full_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return FileResponse(str(full_path), media_type="image/jpeg")


@router.get("/{journal_id}/photos/{photo_uuid}/thumb", summary="Serve photo thumbnail")
def serve_photo_thumb(
    journal_id: int,
    photo_uuid: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Return the 400×400 thumbnail JPEG; falls back to full-res if thumb is missing."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = _get_owned_journal(sess, journal_id, user_info_id)
        photos: List[str] = json.loads(row.photos_json or "[]")
        if photo_uuid not in photos:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Photo not found")

    photo_path = Path(_DATA_DIR) / "users" / current_user["sub"] / "journal" / str(journal_id)
    thumb_path = photo_path / f"{photo_uuid}_thumb.jpg"
    if not thumb_path.exists():
        full_path = photo_path / f"{photo_uuid}.jpg"
        if full_path.exists():
            return FileResponse(str(full_path), media_type="image/jpeg")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return FileResponse(str(thumb_path), media_type="image/jpeg")
