"""Tests for the per-share content key feature (issue #28 Part B).

Covers: uploading share-encrypted memory content, retrieving it through
shared_project/shared_project_meta, revoke clearing it (+ the no-op-on-
already-empty case), and full/no-memories token independence. Mirrors the
_seed/env fixture pattern in tests/test_project_shares_api.py.
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import models.db as db_module
from api.deps import get_current_user, get_optional_current_user
from api.project_shares import router as project_shares_router
from api.share import invalidate_share_cache, router as share_router
from models.project_db import DBMemory, DBProject, DBProjectItem, DBShareMemoryContent
from models.user import UserInfo

_ENVELOPE_NAME = "v1.YWJj.ZGVm"
_ENVELOPE_DESC = "v1.eGl6.enp6"


def _seed(engine) -> tuple[int, int, int]:
    """Seed a user + project with one encrypted and one plaintext memory.

    Returns (user_info_id, encrypted_memory_id, plaintext_memory_id).
    """
    with Session(engine) as sess:
        u = UserInfo(display_name="A", email="a@e.com")
        sess.add(u); sess.commit(); sess.refresh(u)
        proj = DBProject(user_info_id=u.id, name="My Trip")
        sess.add(proj); sess.commit(); sess.refresh(proj)

        enc_mem = DBMemory(project_id=proj.id, date="2024-06-01",
                           name=_ENVELOPE_NAME, description=_ENVELOPE_DESC)
        sess.add(enc_mem); sess.commit(); sess.refresh(enc_mem)

        plain_mem = DBMemory(project_id=proj.id, date="2024-06-02",
                             name="A place", description="Some notes")
        sess.add(plain_mem); sess.commit(); sess.refresh(plain_mem)

        sess.add(DBProjectItem(project_id=proj.id, position=0,
                               item_type="memory", memory_id=enc_mem.id))
        sess.add(DBProjectItem(project_id=proj.id, position=1,
                               item_type="memory", memory_id=plain_mem.id))
        sess.commit()
        return u.id, enc_mem.id, plain_mem.id


@pytest.fixture
def env(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_module, "engine", engine)
    SQLModel.metadata.create_all(engine)
    uid, enc_mem_id, plain_mem_id = _seed(engine)

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(uid), "email": "a@e.com"}
    app.dependency_overrides[get_optional_current_user] = lambda: None
    app.include_router(project_shares_router)
    app.include_router(share_router)
    client = TestClient(app)
    return client, engine, uid, enc_mem_id, plain_mem_id


# ── Upload / upsert ─────────────────────────────────────────────────────────

class TestUploadShareMemoryContent:
    def test_uploads_content_for_encrypted_memory(self, env):
        client, engine, _uid, enc_mem_id, _plain_id = env
        resp = client.put("/api/projects/My Trip/share/content", json={
            "items": [{"memory_id": enc_mem_id,
                      "name_ciphertext": "v1.aaa.bbb",
                      "description_ciphertext": "v1.ccc.ddd"}],
        })
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"updated": 1}

        with Session(engine) as sess:
            row = sess.exec(
                select(DBShareMemoryContent).where(
                    DBShareMemoryContent.memory_id == enc_mem_id,
                )
            ).first()
        assert row is not None
        assert row.token_type == "full"
        assert row.name_ciphertext == "v1.aaa.bbb"
        assert row.description_ciphertext == "v1.ccc.ddd"

    def test_skips_plaintext_memory(self, env):
        client, engine, _uid, _enc_id, plain_mem_id = env
        resp = client.put("/api/projects/My Trip/share/content", json={
            "items": [{"memory_id": plain_mem_id,
                      "name_ciphertext": "v1.aaa.bbb"}],
        })
        assert resp.status_code == 200
        assert resp.json() == {"updated": 0}
        with Session(engine) as sess:
            rows = sess.exec(select(DBShareMemoryContent)).all()
        assert rows == []

    def test_skips_memory_not_in_project(self, env):
        client, engine, uid, _enc_id, _plain_id = env
        with Session(engine) as sess:
            other_proj = DBProject(user_info_id=uid, name="Other Trip")
            sess.add(other_proj); sess.commit(); sess.refresh(other_proj)
            other_mem = DBMemory(project_id=other_proj.id, date="2024-01-01",
                                 name=_ENVELOPE_NAME)
            sess.add(other_mem); sess.commit(); sess.refresh(other_mem)
            other_mem_id = other_mem.id

        resp = client.put("/api/projects/My Trip/share/content", json={
            "items": [{"memory_id": other_mem_id, "name_ciphertext": "v1.aaa.bbb"}],
        })
        assert resp.status_code == 200
        assert resp.json() == {"updated": 0}

    def test_upsert_overwrites_existing_content(self, env):
        client, engine, _uid, enc_mem_id, _plain_id = env
        client.put("/api/projects/My Trip/share/content", json={
            "items": [{"memory_id": enc_mem_id, "name_ciphertext": "v1.old.old"}],
        })
        resp = client.put("/api/projects/My Trip/share/content", json={
            "items": [{"memory_id": enc_mem_id, "name_ciphertext": "v1.new.new"}],
        })
        assert resp.json() == {"updated": 1}
        with Session(engine) as sess:
            rows = sess.exec(
                select(DBShareMemoryContent).where(DBShareMemoryContent.memory_id == enc_mem_id)
            ).all()
        assert len(rows) == 1
        assert rows[0].name_ciphertext == "v1.new.new"

    def test_project_not_found(self, env):
        client, *_ = env
        resp = client.put("/api/projects/No Such Trip/share/content", json={"items": []})
        assert resp.status_code == 404


# ── Retrieval through shared_project / shared_project_meta ────────────────────

class TestSharedViewSurfacesShareContent:
    def test_shared_project_includes_share_ciphertext(self, env):
        client, engine, _uid, enc_mem_id, _plain_id = env
        with Session(engine) as sess:
            proj = sess.exec(select(DBProject).where(DBProject.name == "My Trip")).first()
            proj.share_token = "tok_full"
            sess.add(proj); sess.commit()

        client.put("/api/projects/My Trip/share/content", json={
            "items": [{"memory_id": enc_mem_id,
                      "name_ciphertext": "v1.aaa.bbb",
                      "description_ciphertext": "v1.ccc.ddd"}],
        })
        invalidate_share_cache("tok_full")

        resp = client.get("/api/share/tok_full")
        assert resp.status_code == 200
        mem = next(
            it["memory"] for it in resp.json()["items"]
            if it["item_type"] == "memory" and it["memory"]["id"] == enc_mem_id
        )
        assert mem["name"] is None
        assert mem["description"] is None
        assert mem["share_name_ciphertext"] == "v1.aaa.bbb"
        assert mem["share_description_ciphertext"] == "v1.ccc.ddd"

    def test_shared_project_meta_includes_share_ciphertext(self, env):
        client, engine, _uid, enc_mem_id, _plain_id = env
        with Session(engine) as sess:
            proj = sess.exec(select(DBProject).where(DBProject.name == "My Trip")).first()
            proj.share_token = "tok_full"
            sess.add(proj); sess.commit()

        client.put("/api/projects/My Trip/share/content", json={
            "items": [{"memory_id": enc_mem_id, "name_ciphertext": "v1.aaa.bbb"}],
        })
        invalidate_share_cache("tok_full")

        resp = client.get("/api/share/tok_full/meta")
        mem = next(
            it["memory"] for it in resp.json()["items"]
            if it["item_type"] == "memory" and it["memory"]["id"] == enc_mem_id
        )
        assert mem["share_name_ciphertext"] == "v1.aaa.bbb"

    def test_without_share_content_row_field_is_stripped_not_substituted(self, env):
        """No DBShareMemoryContent row uploaded — the memory is still stripped
        to None (Part A) but no share_name_ciphertext key is added."""
        client, engine, _uid, enc_mem_id, _plain_id = env
        with Session(engine) as sess:
            proj = sess.exec(select(DBProject).where(DBProject.name == "My Trip")).first()
            proj.share_token = "tok_full"
            sess.add(proj); sess.commit()
        invalidate_share_cache("tok_full")

        resp = client.get("/api/share/tok_full")
        mem = next(
            it["memory"] for it in resp.json()["items"]
            if it["item_type"] == "memory" and it["memory"]["id"] == enc_mem_id
        )
        assert mem["name"] is None
        assert "share_name_ciphertext" not in mem


# ── Revocation lifecycle ────────────────────────────────────────────────────

class TestRevokeClearsShareContent:
    def test_revoke_deletes_share_memory_content(self, env):
        client, engine, _uid, enc_mem_id, _plain_id = env
        client.post("/api/projects/My Trip/share")
        client.put("/api/projects/My Trip/share/content", json={
            "items": [{"memory_id": enc_mem_id, "name_ciphertext": "v1.aaa.bbb"}],
        })
        with Session(engine) as sess:
            assert sess.exec(select(DBShareMemoryContent)).all() != []

        resp = client.delete("/api/projects/My Trip/share")
        assert resp.status_code == 204

        with Session(engine) as sess:
            assert sess.exec(select(DBShareMemoryContent)).all() == []

    def test_revoke_without_share_content_is_noop(self, env):
        client, *_ = env
        client.post("/api/projects/My Trip/share")
        resp = client.delete("/api/projects/My Trip/share")
        assert resp.status_code == 204  # no share content ever uploaded — no-op

    def test_revoke_without_existing_token_is_noop(self, env):
        """Never having created a share link at all — the existing revoke
        no-op semantics extend cleanly to the content table."""
        client, *_ = env
        resp = client.delete("/api/projects/My Trip/share")
        assert resp.status_code == 204

    def test_no_memories_token_revoke_leaves_full_content_untouched(self, env):
        """The no-memories token never carries memory content, so revoking it
        must not touch DBShareMemoryContent rows tied to the full token."""
        client, engine, _uid, enc_mem_id, _plain_id = env
        client.post("/api/projects/My Trip/share")
        client.post("/api/projects/My Trip/share/no-memories")
        client.put("/api/projects/My Trip/share/content", json={
            "items": [{"memory_id": enc_mem_id, "name_ciphertext": "v1.aaa.bbb"}],
        })

        resp = client.delete("/api/projects/My Trip/share/no-memories")
        assert resp.status_code == 204

        with Session(engine) as sess:
            rows = sess.exec(select(DBShareMemoryContent)).all()
        assert len(rows) == 1  # untouched by revoking the other token
