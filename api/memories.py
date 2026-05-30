"""REST memories endpoints — CRUD and photo management for project memories.

Routes:
    POST   /api/memories                            — create a memory
    PUT    /api/memories/{id}                       — update a memory
    DELETE /api/memories/{id}                       — delete a memory + its photos
    POST   /api/memories/{id}/photos                — upload a photo
    DELETE /api/memories/{id}/photos/{uuid}         — delete a specific photo
    GET    /api/memories/{id}/photos/{uuid}         — serve full-res photo
    GET    /api/memories/{id}/photos/{uuid}/thumb   — serve thumbnail
    GET    /api/memories/{id}/comments              — list comments (threaded)
    POST   /api/memories/{id}/comments              — add a comment
    DELETE /api/memories/{id}/comments/{cid}        — delete a comment
    GET    /api/memories/{id}/likes                 — get like count and likers
    POST   /api/memories/{id}/like                  — like a memory
    DELETE /api/memories/{id}/like                  — unlike a memory
    GET    /api/memories/{id}/translations/{lang}   — get translated memory text
"""
from __future__ import annotations

import io
import json
import os
import uuid as uuid_lib
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from models.db import get_session
from PIL import Image
from pydantic import BaseModel, Field
from sqlmodel import select

from api.deps import get_current_user
from api.translations import translate_text
from models.project_db import DBMemory, DBMemoryComment, DBMemoryLike, DBMemoryTranslation, DBProject, DBProjectItem
from models.user import UserInfo
from src.models.memory import Memory

router = APIRouter(prefix="/api/memories", tags=["memories"])

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_THUMB_SIZE = (400, 400)


# ── Response schemas ──────────────────────────────────────────────────────────

class IDOut(BaseModel):
    id: int = Field(description="ID of the newly created resource")


class UUIDOut(BaseModel):
    uuid: str = Field(description="UUID of the uploaded photo")


class QueuedOut(BaseModel):
    queued: bool = Field(description="True when the background download was scheduled")


class LikerOut(BaseModel):
    name: str = Field(description="Display name of the user who liked this memory")
    user_info_id: int = Field(description="Internal user ID")


class LikesOut(BaseModel):
    count: int = Field(description="Total number of likes")
    liked_by_me: bool = Field(description="True if the authenticated user has liked this memory")
    likers: List[LikerOut] = Field(description="Users who liked this memory")


class CommentOut(BaseModel):
    id: int = Field(description="Comment ID")
    user_info_id: int = Field(description="Author's internal user ID")
    commenter_name: str = Field(description="Display name of the commenter")
    text: str = Field(description="Comment body")
    created_at: str = Field(description="ISO-8601 UTC timestamp")
    replies: List["CommentOut"] = Field(default_factory=list, description="Nested replies")


class TranslationOut(BaseModel):
    lang_code: str = Field(description="BCP-47 language code, e.g. 'fr' or 'de'")
    name: Optional[str] = Field(None, description="Translated memory name")
    description: Optional[str] = Field(None, description="Translated memory description")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _photo_dir(user_id: str, memory_id: int) -> Path:
    p = Path(_DATA_DIR) / "users" / user_id / "memories" / str(memory_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _resolve_geo(
    sess, project_id: int, date: str, geo_mode: str
) -> tuple[Optional[float], Optional[float]]:
    """Resolve (lat, lon) from activities on *date* according to *geo_mode*."""
    if geo_mode == "custom":
        return None, None

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

    def _date_of(row) -> str:
        return (row.start_date_local or "")[:10]

    day_acts = [r for r in act_rows if _date_of(r) == date]
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
    project_name: str = Field(description="Project the memory belongs to")
    date: str = Field(description="Date of the memory (YYYY-MM-DD)")
    geo_mode: str = Field("start_of_day", description="How to resolve coordinates: 'start_of_day', 'end_of_day', or 'custom'")
    name: Optional[str] = Field(None, description="Optional memory title")
    time: Optional[str] = Field(None, description="Optional time of day (HH:MM)")
    description: Optional[str] = Field(None, description="Free-text notes")
    lat: Optional[float] = Field(None, description="Latitude (required when geo_mode='custom')")
    lon: Optional[float] = Field(None, description="Longitude (required when geo_mode='custom')")
    insert_after_index: Optional[int] = Field(None, description="Position in the project item list to insert after")
    polarsteps_step_id: Optional[int] = Field(None, description="Polarsteps step ID for deduplication during import")


@router.post("/", status_code=status.HTTP_201_CREATED, response_model=IDOut,
             summary="Create a memory")
def create_memory(
    body: MemoryBody,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Create a new memory in a project and insert it at the requested position."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        project_id = _get_project_id(sess, user_info_id, body.project_name)

        if body.polarsteps_step_id is not None:
            existing = sess.exec(
                select(DBMemory).where(
                    DBMemory.project_id == project_id,
                    DBMemory.polarsteps_step_id == body.polarsteps_step_id,
                )
            ).first()
            if existing:
                return {"id": existing.id}

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
        sess.flush()

        existing_items = sess.exec(
            select(DBProjectItem)
            .where(DBProjectItem.project_id == project_id)
            .order_by(DBProjectItem.position)
        ).all()
        insert_at = len(existing_items)
        if body.insert_after_index is not None:
            insert_at = max(0, min(len(existing_items), body.insert_after_index + 1))

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
    date: str = Field(description="Date of the memory (YYYY-MM-DD)")
    geo_mode: str = Field("start_of_day", description="How to resolve coordinates")
    name: Optional[str] = Field(None, description="Optional memory title")
    time: Optional[str] = Field(None, description="Optional time of day (HH:MM)")
    description: Optional[str] = Field(None, description="Free-text notes")
    lat: Optional[float] = Field(None, description="Latitude (required when geo_mode='custom')")
    lon: Optional[float] = Field(None, description="Longitude (required when geo_mode='custom')")


@router.put("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT,
            summary="Update a memory")
def update_memory(
    memory_id: int,
    body: MemoryUpdateBody,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Update the metadata of an existing memory."""
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


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Delete a memory")
def delete_memory(
    memory_id: int,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Delete a memory and all its photos from disk."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        mem_row = _get_owned_memory(sess, memory_id, user_info_id)

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
    url: str = Field(description="Public URL of the image to download")


@router.post("/{memory_id}/photos", status_code=status.HTTP_201_CREATED,
             response_model=UUIDOut, summary="Upload a photo")
async def upload_photo(
    memory_id: int,
    file: Annotated[UploadFile, File()],
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Upload a JPEG photo; a 400×400 thumbnail is generated automatically."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        _get_owned_memory(sess, memory_id, user_info_id)
    raw = await file.read()
    photo_uuid = str(uuid_lib.uuid4())
    _save_photo_files(current_user["sub"], memory_id, photo_uuid, raw)
    _append_photo_to_memory(memory_id, photo_uuid)
    return {"uuid": photo_uuid}


@router.post("/{memory_id}/photos/from-url", status_code=202,
             response_model=QueuedOut, summary="Queue a photo download from URL")
async def queue_photo_from_url(
    memory_id: int,
    body: PhotoFromUrlIn,
    background_tasks: BackgroundTasks,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Enqueue a background download of a photo from a public URL."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        _get_owned_memory(sess, memory_id, user_info_id)
    background_tasks.add_task(_download_photo_from_url, memory_id, body.url, current_user["sub"])
    return {"queued": True}


@router.delete("/{memory_id}/photos/{photo_uuid}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Delete a photo")
def delete_photo(
    memory_id: int,
    photo_uuid: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Remove a photo from a memory and delete its files from disk."""
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


@router.get("/{memory_id}/photos/{photo_uuid}", summary="Serve full-resolution photo")
def serve_photo(
    memory_id: int,
    photo_uuid: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Return the full-resolution JPEG for a memory photo."""
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


@router.get("/{memory_id}/photos/{photo_uuid}/thumb", summary="Serve photo thumbnail")
def serve_photo_thumb(
    memory_id: int,
    photo_uuid: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Return the 400×400 thumbnail JPEG; falls back to full-res if thumb is missing."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        mem_row = _get_owned_memory(sess, memory_id, user_info_id)
        photos: List[str] = json.loads(mem_row.photos_json or "[]")
        if photo_uuid not in photos:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Photo not found")

    photo_path = Path(_DATA_DIR) / "users" / current_user["sub"] / "memories" / str(memory_id)
    thumb_path = photo_path / f"{photo_uuid}_thumb.jpg"
    if not thumb_path.exists():
        full_path = photo_path / f"{photo_uuid}.jpg"
        if full_path.exists():
            return FileResponse(str(full_path), media_type="image/jpeg")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return FileResponse(str(thumb_path), media_type="image/jpeg")


# ── Comments ──────────────────────────────────────────────────────────────────

def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_comment_tree(rows: List[DBMemoryComment]) -> List[Dict]:
    """Convert flat comment rows into a fully recursive tree."""
    by_id: Dict[int, Dict] = {}
    for r in rows:
        by_id[r.id] = {
            "id": r.id,
            "user_info_id": r.user_info_id,
            "commenter_name": r.commenter_name,
            "text": r.text,
            "created_at": r.created_at,
            "replies": [],
        }
    roots: List[Dict] = []
    for r in rows:
        node = by_id[r.id]
        if r.parent_comment_id is not None and r.parent_comment_id in by_id:
            by_id[r.parent_comment_id]["replies"].append(node)
        else:
            roots.append(node)
    return roots


class CommentBody(BaseModel):
    text: str = Field(description="Comment body text")
    parent_comment_id: Optional[int] = Field(None, description="ID of the parent comment for threaded replies")


@router.get("/{memory_id}/comments", response_model=List[CommentOut],
            summary="List comments")
def list_comments(
    memory_id: int,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Return all comments on a memory as a recursive tree (replies nested under parents)."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        _get_owned_memory(sess, memory_id, user_info_id)
        rows = sess.exec(
            select(DBMemoryComment)
            .where(DBMemoryComment.memory_id == memory_id)
            .order_by(DBMemoryComment.created_at)
        ).all()
        return _build_comment_tree(list(rows))


@router.post("/{memory_id}/comments", status_code=status.HTTP_201_CREATED,
             response_model=IDOut, summary="Add a comment")
def add_comment(
    memory_id: int,
    body: CommentBody,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Add a top-level comment or a threaded reply to an existing comment."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        _get_owned_memory(sess, memory_id, user_info_id)
        user_row = sess.get(UserInfo, user_info_id)
        commenter_name = user_row.display_name if user_row else ""

        if body.parent_comment_id is not None:
            parent = sess.get(DBMemoryComment, body.parent_comment_id)
            if parent is None or parent.memory_id != memory_id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid parent comment")

        row = DBMemoryComment(
            memory_id=memory_id,
            parent_comment_id=body.parent_comment_id,
            user_info_id=user_info_id,
            commenter_name=commenter_name,
            text=body.text,
            created_at=_utc_now(),
        )
        sess.add(row)
        sess.commit()
        return {"id": row.id}


@router.delete("/{memory_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Delete a comment")
def delete_comment(
    memory_id: int,
    comment_id: int,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Delete a comment and all its replies. Allowed for the comment author or project owner."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        mem_row = _get_owned_memory(sess, memory_id, user_info_id)
        comment_row = sess.get(DBMemoryComment, comment_id)
        if comment_row is None or comment_row.memory_id != memory_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")

        project_row = sess.get(DBProject, mem_row.project_id)
        is_owner = project_row is not None and project_row.user_info_id == user_info_id
        is_author = comment_row.user_info_id == user_info_id
        if not (is_owner or is_author):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

        _delete_comment_subtree(sess, comment_id)
        sess.commit()


def _delete_comment_subtree(sess, comment_id: int) -> None:
    """Delete a comment and all its descendants (BFS)."""
    queue = [comment_id]
    while queue:
        current = queue.pop(0)
        children = sess.exec(
            select(DBMemoryComment).where(DBMemoryComment.parent_comment_id == current)
        ).all()
        for child in children:
            queue.append(child.id)
            sess.delete(child)
        row = sess.get(DBMemoryComment, current)
        if row is not None:
            sess.delete(row)


# ── Likes ─────────────────────────────────────────────────────────────────────

@router.get("/{memory_id}/likes", response_model=LikesOut, summary="Get likes")
def get_likes(
    memory_id: int,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Return the like count, whether the caller has liked this memory, and the list of likers."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        _get_owned_memory(sess, memory_id, user_info_id)
        like_rows = sess.exec(
            select(DBMemoryLike).where(DBMemoryLike.memory_id == memory_id)
        ).all()
        liked_by_me = any(r.user_info_id == user_info_id for r in like_rows)
        return {
            "count": len(like_rows),
            "liked_by_me": liked_by_me,
            "likers": [{"name": r.liker_name, "user_info_id": r.user_info_id} for r in like_rows],
        }


@router.post("/{memory_id}/like", status_code=status.HTTP_204_NO_CONTENT,
             summary="Like a memory")
def like_memory(
    memory_id: int,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Like a memory. Idempotent — calling this twice has no effect."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        _get_owned_memory(sess, memory_id, user_info_id)
        existing = sess.exec(
            select(DBMemoryLike).where(
                DBMemoryLike.memory_id == memory_id,
                DBMemoryLike.user_info_id == user_info_id,
            )
        ).first()
        if existing:
            return
        user_row = sess.get(UserInfo, user_info_id)
        liker_name = user_row.display_name if user_row else ""
        sess.add(DBMemoryLike(
            memory_id=memory_id,
            user_info_id=user_info_id,
            liker_name=liker_name,
            created_at=_utc_now(),
        ))
        sess.commit()


@router.delete("/{memory_id}/like", status_code=status.HTTP_204_NO_CONTENT,
               summary="Unlike a memory")
def unlike_memory(
    memory_id: int,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Remove the caller's like from a memory. No-op if not liked."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        _get_owned_memory(sess, memory_id, user_info_id)
        existing = sess.exec(
            select(DBMemoryLike).where(
                DBMemoryLike.memory_id == memory_id,
                DBMemoryLike.user_info_id == user_info_id,
            )
        ).first()
        if existing:
            sess.delete(existing)
            sess.commit()


# ── Translations ──────────────────────────────────────────────────────────────

import json as _json


@router.get("/{memory_id}/translations/{lang_code}", response_model=TranslationOut,
            summary="Get memory translation")
async def get_translation(
    memory_id: int,
    lang_code: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Return a translated version of the memory's name and description.

    Translations are generated on first request via Google Translate and cached
    in the database. Subsequent calls for the same memory + language return
    instantly from cache. The language must be enabled in the project's settings.
    """
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        mem_row = _get_owned_memory(sess, memory_id, user_info_id)
        project_row = sess.get(DBProject, mem_row.project_id)
        allowed_langs = _json.loads(getattr(project_row, 'languages_json', None) or "[]")
        if lang_code not in allowed_langs:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Language not enabled for this project")

        cached = sess.exec(
            select(DBMemoryTranslation).where(
                DBMemoryTranslation.memory_id == memory_id,
                DBMemoryTranslation.lang_code == lang_code,
            )
        ).first()
        if cached:
            return {"lang_code": lang_code, "name": cached.name, "description": cached.description}

    try:
        translated_name = await translate_text(mem_row.name, lang_code) if mem_row.name else None
        translated_desc = await translate_text(mem_row.description, lang_code) if mem_row.description else None
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Translation service error: {exc}") from exc

    with get_session() as sess:
        row = DBMemoryTranslation(
            memory_id=memory_id,
            lang_code=lang_code,
            name=translated_name,
            description=translated_desc,
            created_at=_utc_now(),
        )
        sess.add(row)
        sess.commit()

    return {"lang_code": lang_code, "name": translated_name, "description": translated_desc}
