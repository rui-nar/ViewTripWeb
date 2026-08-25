"""Tests for photo-upload processing safety on memories and journal entries.

Covers two fixes to `upload_photo`/`replace_photo` in api/memories.py and
api/journal.py:

  * the CPU-bound `_save_photo_files` call (JPEG decode + LANCZOS thumbnail
    resize + disk writes) is offloaded to a thread via `run_in_threadpool`
    instead of blocking the shared asyncio event loop inline;
  * a corrupt/non-image upload returns a clean 422, not a raw 500 from an
    uncaught PIL.UnidentifiedImageError.
"""
from __future__ import annotations

import io
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import api.journal as journal_mod
import api.memories as mem_mod
import models.db as db_module
from api.deps import get_current_user
from api.journal import router as journal_router
from api.memories import router as memories_router
from models.project_db import DBJournalEntry, DBMemory, DBProject
from models.user import UserInfo


def _jpeg_bytes(size=(20, 20), color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture
def env(monkeypatch, tmp_path):
    """In-memory DB + TestClient wired to one user and one project.

    Both the memories and journal routers are mounted so both content types
    can be exercised. Yields (client, user_id, project_id, engine).
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(mem_mod, "_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(journal_mod, "_DATA_DIR", str(tmp_path))

    SQLModel.metadata.create_all(engine)

    with Session(engine) as sess:
        user = UserInfo(display_name="Alice", email="alice@example.com")
        sess.add(user)
        sess.commit()
        sess.refresh(user)
        user_id = user.id

        project = DBProject(user_info_id=user_id, name="My Trip")
        sess.add(project)
        sess.commit()
        sess.refresh(project)
        project_id = project.id

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(user_id), "email": "alice@example.com"}
    app.include_router(memories_router)
    app.include_router(journal_router)
    client = TestClient(app)
    yield client, user_id, project_id, engine


def _insert_memory(engine, project_id, photos=None) -> int:
    with Session(engine) as sess:
        row = DBMemory(project_id=project_id, date="2025-06-01", geo_mode="custom",
                        photos_json=json.dumps(photos or []))
        sess.add(row)
        sess.commit()
        sess.refresh(row)
        return row.id


def _insert_journal(engine, project_id, photos=None) -> int:
    with Session(engine) as sess:
        row = DBJournalEntry(project_id=project_id, date="2025-06-01", geo_mode="custom",
                              photos_json=json.dumps(photos or []))
        sess.add(row)
        sess.commit()
        sess.refresh(row)
        return row.id


def _spy_run_in_threadpool(monkeypatch, module):
    """Replace `module.run_in_threadpool` with a spy that still runs the call
    synchronously, and return the list it records calls into."""
    calls = []

    async def fake(func, *args, **kwargs):
        calls.append(func)
        return func(*args, **kwargs)

    monkeypatch.setattr(module, "run_in_threadpool", fake)
    return calls


# ── Fix 1: the blocking image work is offloaded to a thread ───────────────────

class TestUploadOffloadsToThread:
    def test_memory_upload_uses_run_in_threadpool(self, env, monkeypatch):
        client, _, project_id, engine = env
        memory_id = _insert_memory(engine, project_id)
        calls = _spy_run_in_threadpool(monkeypatch, mem_mod)

        resp = client.post(
            f"/api/memories/{memory_id}/photos",
            files={"file": ("p.jpg", _jpeg_bytes(), "image/jpeg")},
        )
        assert resp.status_code == 201, resp.text
        assert calls == [mem_mod._save_photo_files]

    def test_memory_replace_uses_run_in_threadpool(self, env, monkeypatch):
        client, _, project_id, engine = env
        memory_id = _insert_memory(engine, project_id, ["old-uuid"])
        calls = _spy_run_in_threadpool(monkeypatch, mem_mod)

        resp = client.put(
            f"/api/memories/{memory_id}/photos/old-uuid/replace",
            files={"file": ("p.jpg", _jpeg_bytes(), "image/jpeg")},
        )
        assert resp.status_code == 200, resp.text
        assert calls == [mem_mod._save_photo_files]

    def test_journal_upload_uses_run_in_threadpool(self, env, monkeypatch):
        client, _, project_id, engine = env
        journal_id = _insert_journal(engine, project_id)
        calls = _spy_run_in_threadpool(monkeypatch, journal_mod)

        resp = client.post(
            f"/api/journal/{journal_id}/photos",
            files={"file": ("p.jpg", _jpeg_bytes(), "image/jpeg")},
        )
        assert resp.status_code == 201, resp.text
        assert calls == [journal_mod._save_photo_files]

    def test_journal_replace_uses_run_in_threadpool(self, env, monkeypatch):
        client, _, project_id, engine = env
        journal_id = _insert_journal(engine, project_id, ["old-uuid"])
        calls = _spy_run_in_threadpool(monkeypatch, journal_mod)

        resp = client.put(
            f"/api/journal/{journal_id}/photos/old-uuid/replace",
            files={"file": ("p.jpg", _jpeg_bytes(), "image/jpeg")},
        )
        assert resp.status_code == 200, resp.text
        assert calls == [journal_mod._save_photo_files]


# ── Fix 3: corrupt/non-image uploads get a clean 422, not a 500 ───────────────

class TestCorruptImageUpload:
    def test_memory_upload_rejects_corrupt_file(self, env, tmp_path):
        client, user_id, project_id, engine = env
        memory_id = _insert_memory(engine, project_id)

        resp = client.post(
            f"/api/memories/{memory_id}/photos",
            files={"file": ("bad.jpg", b"not an image", "image/jpeg")},
        )
        assert resp.status_code == 422

        # No orphaned files left behind for the rejected upload.
        photo_dir = tmp_path / "users" / str(user_id) / "memories" / str(memory_id)
        assert list(photo_dir.glob("*.jpg")) == []

    def test_memory_replace_rejects_corrupt_file(self, env):
        client, _, project_id, engine = env
        memory_id = _insert_memory(engine, project_id, ["old-uuid"])

        resp = client.put(
            f"/api/memories/{memory_id}/photos/old-uuid/replace",
            files={"file": ("bad.jpg", b"not an image", "image/jpeg")},
        )
        assert resp.status_code == 422

        # The original photo list is untouched by the failed replace.
        with Session(engine) as sess:
            row = sess.get(DBMemory, memory_id)
        assert json.loads(row.photos_json) == ["old-uuid"]

    def test_journal_upload_rejects_corrupt_file(self, env, tmp_path):
        client, user_id, project_id, engine = env
        journal_id = _insert_journal(engine, project_id)

        resp = client.post(
            f"/api/journal/{journal_id}/photos",
            files={"file": ("bad.jpg", b"not an image", "image/jpeg")},
        )
        assert resp.status_code == 422

        photo_dir = tmp_path / "users" / str(user_id) / "journal" / str(journal_id)
        assert list(photo_dir.glob("*.jpg")) == []

    def test_journal_replace_rejects_corrupt_file(self, env):
        client, _, project_id, engine = env
        journal_id = _insert_journal(engine, project_id, ["old-uuid"])

        resp = client.put(
            f"/api/journal/{journal_id}/photos/old-uuid/replace",
            files={"file": ("bad.jpg", b"not an image", "image/jpeg")},
        )
        assert resp.status_code == 422

        with Session(engine) as sess:
            row = sess.get(DBJournalEntry, journal_id)
        assert json.loads(row.photos_json) == ["old-uuid"]
